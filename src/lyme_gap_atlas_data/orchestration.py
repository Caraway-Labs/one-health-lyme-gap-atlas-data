"""Append-only catalog discovery orchestration for the governed DEV pipeline."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic, sleep
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from .artifacts import create_artifact
from .cdc import build_approved_cdc_models, ingest_approved_cdc
from .discovery import (
    DiscoveryRequest,
    fetch_json,
    initial_requests,
    load_search_configuration,
    next_page_request,
)
from .redaction import redact_mapping
from .settings import PipelineSettings


@dataclass(frozen=True)
class DiscoveryResume:
    """A non-secret checkpoint for a rate-limited catalog page."""

    prior_run_id: str
    original_request_index: int
    request: DiscoveryRequest
    offset: int


class DiscoveryTimeBudgetExceeded(Exception):
    """Raised before the App Platform job timeout can terminate the worker."""


def _catalog_request(request: DiscoveryRequest, settings: PipelineSettings) -> DiscoveryRequest:
    headers = dict(request.headers)
    if request.catalog_id == "DATA_GOV":
        if settings.data_gov_api_key is None:
            raise ValueError("DATA_GOV_API_KEY is required")
        headers["X-Api-Key"] = settings.data_gov_api_key.get_secret_value()
    elif settings.socrata_app_token is not None:
        headers["X-App-Token"] = settings.socrata_app_token.get_secret_value()
    return DiscoveryRequest(
        request.catalog_id, request.term, request.url, headers, request.pagination
    )


def _spaces_client(settings: PipelineSettings) -> Any:
    if settings.spaces_access_key_id is None or settings.spaces_secret_access_key is None:
        raise ValueError("Spaces credentials are required")
    return boto3.client(
        "s3",
        endpoint_url=settings.spaces_endpoint,
        aws_access_key_id=settings.spaces_access_key_id.get_secret_value(),
        aws_secret_access_key=settings.spaces_secret_access_key.get_secret_value(),
        region_name=settings.spaces_region,
        config=Config(signature_version="s3v4"),
    )


def _resource_key(request: DiscoveryRequest) -> str:
    term_digest = hashlib.sha256(request.term.casefold().encode()).hexdigest()[:16]
    return f"catalog:{request.catalog_id.lower()}:{term_digest}"


def _redacted_request_details(request: DiscoveryRequest) -> str:
    """Return reproducible request evidence without credentials."""
    return json.dumps(
        redact_mapping(
            {
                "catalog_id": request.catalog_id,
                "term": request.term,
                **request.headers,
            }
        )
    )


def _failure_status_code(error: Exception) -> int | None:
    """Extract an HTTP status without retaining response content."""
    return error.code if isinstance(error, HTTPError) else None


def _resume_state(resume: DiscoveryResume) -> str:
    """Serialize only public request state; never carry provider credentials."""
    return json.dumps(
        {
            "original_request_index": resume.original_request_index,
            "offset": resume.offset,
            "request": {
                "catalog_id": resume.request.catalog_id,
                "term": resume.request.term,
                "url": resume.request.url,
                "pagination": resume.request.pagination,
            },
        },
        sort_keys=True,
    )


def _decode_resume_state(prior_run_id: str, value: Any) -> DiscoveryResume:
    """Validate persisted continuation state before using it for a new run."""
    payload = json.loads(value) if isinstance(value, str) else value
    if not isinstance(payload, dict):
        raise ValueError("Discovery resume state is not an object")
    request_payload = payload.get("request")
    if not isinstance(request_payload, dict):
        raise ValueError("Discovery resume state has no request")
    catalog_id = request_payload.get("catalog_id")
    term = request_payload.get("term")
    url = request_payload.get("url")
    pagination = request_payload.get("pagination")
    index = payload.get("original_request_index")
    offset = payload.get("offset")
    if (
        not isinstance(catalog_id, str)
        or not isinstance(term, str)
        or not isinstance(url, str)
        or not isinstance(pagination, dict)
        or not isinstance(index, int)
        or not isinstance(offset, int)
    ):
        raise ValueError("Discovery resume state is incomplete")
    return DiscoveryResume(
        prior_run_id=prior_run_id,
        original_request_index=index,
        request=DiscoveryRequest(catalog_id, term, url, {}, pagination),
        offset=offset,
    )


def _request_index(requests: list[DiscoveryRequest], request: DiscoveryRequest) -> int:
    for index, candidate in enumerate(requests):
        if candidate.catalog_id == request.catalog_id and candidate.term == request.term:
            return index
    raise ValueError("Discovery resume request is not present in the active configuration")


def _read_artifact_payload(
    s3: Any, settings: PipelineSettings, artifact_uri: str
) -> dict[str, Any]:
    parsed = urlsplit(artifact_uri)
    if parsed.scheme != "s3" or parsed.netloc != settings.spaces_bucket or not parsed.path:
        raise ValueError("Discovery resume artifact is outside the configured private bucket")
    body = s3.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))["Body"].read()
    payload: dict[str, Any] = json.loads(body.decode("utf-8"))
    return payload


def _reconstruct_data_gov_resume(
    cursor: Any,
    s3: Any,
    settings: PipelineSettings,
    prior_run_id: str,
    requests: list[DiscoveryRequest],
    *,
    require_rate_limit: bool = True,
) -> DiscoveryResume:
    """Recover one legacy Data.gov checkpoint from its last immutable artifact."""
    cursor.execute(
        """SELECT redacted_request:catalog_id::VARCHAR, redacted_request:term::VARCHAR
        FROM GOVERNANCE.INGESTION_REQUESTS
        WHERE ingestion_run_id = %s AND status_code = 429
        ORDER BY request_sequence DESC LIMIT 1""",
        (prior_run_id,),
    )
    failed = cursor.fetchone()
    cursor.execute(
        """SELECT q.redacted_request:catalog_id::VARCHAR, q.redacted_request:term::VARCHAR,
                  a.artifact_uri
        FROM GOVERNANCE.INGESTION_REQUESTS q
        JOIN GOVERNANCE.RAW_ARTIFACTS a ON a.ingestion_request_id = q.ingestion_request_id
        WHERE q.ingestion_run_id = %s AND q.status_code = 200
        ORDER BY q.request_sequence DESC LIMIT 1""",
        (prior_run_id,),
    )
    previous = cursor.fetchone()
    if previous is None or previous[0] != "DATA_GOV":
        raise ValueError("Legacy discovery run cannot be resumed safely")
    if require_rate_limit and (
        failed is None or failed[:2] != previous[:2] or failed[0] != "DATA_GOV"
    ):
        raise ValueError("Legacy rate-limited discovery run cannot be resumed safely")
    base = next(
        request
        for request in requests
        if request.catalog_id == failed[0] and request.term == failed[1]
    )
    next_request = next_page_request(
        base, _read_artifact_payload(s3, settings, str(previous[2])), 0
    )
    if next_request is None:
        raise ValueError("Legacy rate-limited discovery run has no next page to resume")
    return DiscoveryResume(
        prior_run_id=prior_run_id,
        original_request_index=_request_index(requests, base),
        request=next_request,
        offset=0,
    )


def _has_legacy_rate_limit_failure(cursor: Any, prior_run_id: str) -> bool:
    """Identify a pre-checkpoint run that stopped on an HTTP 429."""
    cursor.execute(
        """SELECT 1 FROM GOVERNANCE.INGESTION_REQUESTS
        WHERE ingestion_run_id = %s AND status_code = 429
        LIMIT 1""",
        (prior_run_id,),
    )
    return cursor.fetchone() is not None


def _has_stale_running_discovery(prior: Any, runtime_seconds: int) -> bool:
    """Recognize a run that App Platform could already have terminated."""
    return (
        prior[3] == "RUNNING"
        and isinstance(prior[4], datetime)
        and prior[4] < datetime.now(UTC) - timedelta(seconds=runtime_seconds + 120)
    )


def _load_discovery_resume(
    cursor: Any,
    s3: Any,
    settings: PipelineSettings,
    config_sha256: str,
    requests: list[DiscoveryRequest],
) -> DiscoveryResume | None:
    """Return a continuation for checkpointed, rate-limited, or stale runs."""
    cursor.execute(
        """SELECT ingestion_run_id, resume_state, error_classification, status, started_at
        FROM GOVERNANCE.INGESTION_RUNS
        WHERE resource_key = 'catalog_discovery' AND run_mode = 'DISCOVERY'
          AND config_sha256 = %s
        ORDER BY started_at DESC LIMIT 1""",
        (config_sha256,),
    )
    prior = cursor.fetchone()
    if prior is None:
        return None
    if prior[1] is not None:
        if prior[2] not in {"RATE_LIMIT", "TIME_BUDGET"}:
            return None
        resume = _decode_resume_state(str(prior[0]), prior[1])
        if _request_index(requests, resume.request) != resume.original_request_index:
            raise ValueError("Discovery resume state does not match the active configuration")
        return resume
    stale_running = _has_stale_running_discovery(prior, settings.discovery_max_runtime_seconds)
    if (
        prior[2] == "RATE_LIMIT"
        or _has_legacy_rate_limit_failure(cursor, str(prior[0]))
        or stale_running
    ):
        return _reconstruct_data_gov_resume(
            cursor,
            s3,
            settings,
            str(prior[0]),
            requests,
            require_rate_limit=not stale_running,
        )
    return None


def _record_failed_request(
    cursor: Any,
    run_id: str,
    sequence: int,
    request: DiscoveryRequest,
    error: Exception,
) -> None:
    cursor.execute(
        """INSERT INTO GOVERNANCE.INGESTION_REQUESTS
        (ingestion_request_id, ingestion_run_id, request_sequence, request_purpose,
         endpoint, redacted_request, status_code, created_at)
        SELECT %s, %s, %s, 'CATALOG_DISCOVERY', %s, PARSE_JSON(%s), %s, %s""",
        (
            str(uuid.uuid4()),
            run_id,
            sequence,
            request.url.split("?", maxsplit=1)[0],
            _redacted_request_details(request),
            _failure_status_code(error),
            datetime.now(UTC),
        ),
    )


def run_discovery(*, maximum_requests: int | None = None) -> dict[str, Any]:
    """Discover catalog metadata, saving every response as an immutable artifact.

    This intentionally stops before candidate approval and full resource ingestion.
    """
    settings = PipelineSettings()
    config, config_sha256 = load_search_configuration(settings.catalog_search_terms_path)
    requests = initial_requests(config)
    if maximum_requests is not None:
        if maximum_requests < 1:
            raise ValueError("maximum_requests must be positive")
        requests = requests[:maximum_requests]

    run_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)
    deadline = monotonic() + settings.discovery_max_runtime_seconds
    s3 = _spaces_client(settings)
    with connect(SnowflakeSettings()) as connection:
        connection.autocommit(False)
        with connection.cursor() as cursor:
            resume = _load_discovery_resume(cursor, s3, settings, config_sha256, requests)
            cursor.execute(
                """INSERT INTO GOVERNANCE.INGESTION_RUNS
                (ingestion_run_id, resource_key, run_mode, trigger_type, status,
                 config_sha256, started_at, resumed_from_ingestion_run_id)
                VALUES (%s, %s, 'DISCOVERY', 'SCHEDULED', 'RUNNING', %s, %s, %s)""",
                (
                    run_id,
                    "catalog_discovery",
                    config_sha256,
                    started_at,
                    resume.prior_run_id if resume is not None else None,
                ),
            )
            connection.commit()
            sequence = 0
            request: DiscoveryRequest | None = None
            original_request_index: int | None = None
            offset = 0
            last_data_gov_request_started_at: float | None = None
            try:
                start_index = resume.original_request_index if resume is not None else 0
                for original_request_index, original_request in enumerate(
                    requests[start_index:], start=start_index
                ):
                    if resume is not None and original_request_index == start_index:
                        request = _catalog_request(resume.request, settings)
                        offset = resume.offset
                    else:
                        request = _catalog_request(original_request, settings)
                        offset = 0
                    while request is not None:
                        if monotonic() >= deadline:
                            raise DiscoveryTimeBudgetExceeded
                        sequence += 1
                        request_id = str(uuid.uuid4())
                        if request.catalog_id == "DATA_GOV":
                            if last_data_gov_request_started_at is not None:
                                elapsed = monotonic() - last_data_gov_request_started_at
                                sleep(max(0.0, 1.0 - elapsed))
                            last_data_gov_request_started_at = monotonic()
                        response = fetch_json(request)
                        payload = json.dumps(
                            response, sort_keys=True, separators=(",", ":")
                        ).encode()
                        artifact = create_artifact(
                            payload=payload,
                            environment=settings.topx_env,
                            resource_key=_resource_key(request),
                            run_id=run_id,
                        )
                        s3.put_object(
                            Bucket=settings.spaces_bucket,
                            Key=f"{settings.spaces_prefix}/{artifact.object_key}",
                            Body=payload,
                            ContentType="application/json",
                        )
                        response_sha256 = artifact.sha256
                        cursor.execute(
                            """INSERT INTO GOVERNANCE.INGESTION_REQUESTS
                        (ingestion_request_id, ingestion_run_id, request_sequence, request_purpose,
                         endpoint, redacted_request, status_code, response_sha256, created_at)
                        SELECT %s, %s, %s, 'CATALOG_DISCOVERY', %s, PARSE_JSON(%s), 200, %s, %s""",
                            (
                                request_id,
                                run_id,
                                sequence,
                                request.url.split("?", maxsplit=1)[0],
                                _redacted_request_details(request),
                                response_sha256,
                                datetime.now(UTC),
                            ),
                        )
                        cursor.execute(
                            """INSERT INTO GOVERNANCE.RAW_ARTIFACTS
                        (artifact_id, ingestion_run_id, ingestion_request_id, artifact_uri,
                         artifact_type,
                         media_type, byte_count, sha256, created_at)
                        VALUES (%s, %s, %s, %s, 'CATALOG_METADATA', 'application/json',
                                %s, %s, %s)""",
                            (
                                str(uuid.uuid4()),
                                run_id,
                                request_id,
                                f"s3://{settings.spaces_bucket}/{settings.spaces_prefix}/{artifact.object_key}",
                                artifact.byte_count,
                                artifact.sha256,
                                datetime.now(UTC),
                            ),
                        )
                        connection.commit()
                        next_request = next_page_request(request, response, offset)
                        if next_request is not None:
                            offset += int(
                                next_request.pagination.get("request_parameters", {}).get(
                                    "limit", 0
                                )
                            )
                        request = next_request
                cursor.execute(
                    """UPDATE GOVERNANCE.INGESTION_RUNS
                    SET status = 'COMPLETED', completed_at = %s WHERE ingestion_run_id = %s""",
                    (datetime.now(UTC), run_id),
                )
                connection.commit()
            except DiscoveryTimeBudgetExceeded:
                connection.rollback()
                if request is None or original_request_index is None:
                    raise RuntimeError(
                        "Discovery time budget ended without a resumable request"
                    ) from None
                checkpoint = DiscoveryResume(
                    prior_run_id=run_id,
                    original_request_index=original_request_index,
                    request=DiscoveryRequest(
                        request.catalog_id, request.term, request.url, {}, request.pagination
                    ),
                    offset=offset,
                )
                cursor.execute(
                    """UPDATE GOVERNANCE.INGESTION_RUNS
                    SET status = 'PAUSED', completed_at = %s,
                        error_classification = 'TIME_BUDGET', redacted_error = %s,
                        resume_state = PARSE_JSON(%s)
                    WHERE ingestion_run_id = %s""",
                    (
                        datetime.now(UTC),
                        (
                            "Discovery paused before the App Platform runtime limit; "
                            "the next run resumes from this page."
                        ),
                        _resume_state(checkpoint),
                        run_id,
                    ),
                )
                connection.commit()
                return {
                    "ingestion_run_id": run_id,
                    "status": "PAUSED",
                    "resumed_from_ingestion_run_id": resume.prior_run_id if resume else None,
                    "config_sha256": config_sha256,
                }
            except HTTPError as error:
                connection.rollback()
                if request is not None:
                    _record_failed_request(cursor, run_id, sequence, request, error)
                if error.code == 429 and request is not None and original_request_index is not None:
                    checkpoint = DiscoveryResume(
                        prior_run_id=run_id,
                        original_request_index=original_request_index,
                        request=DiscoveryRequest(
                            request.catalog_id,
                            request.term,
                            request.url,
                            {},
                            request.pagination,
                        ),
                        offset=offset,
                    )
                    cursor.execute(
                        """UPDATE GOVERNANCE.INGESTION_RUNS
                        SET status = 'PAUSED', completed_at = %s,
                            error_classification = 'RATE_LIMIT', redacted_error = %s,
                            resume_state = PARSE_JSON(%s)
                        WHERE ingestion_run_id = %s""",
                        (
                            datetime.now(UTC),
                            (
                                "Discovery paused after a provider rate limit; "
                                "the next run resumes from this page."
                            ),
                            _resume_state(checkpoint),
                            run_id,
                        ),
                    )
                    connection.commit()
                    return {
                        "ingestion_run_id": run_id,
                        "status": "PAUSED",
                        "resumed_from_ingestion_run_id": (
                            resume.prior_run_id if resume is not None else None
                        ),
                        "config_sha256": config_sha256,
                    }
                cursor.execute(
                    """UPDATE GOVERNANCE.INGESTION_RUNS
                    SET status = 'FAILED', completed_at = %s, error_classification = %s,
                        redacted_error = %s
                    WHERE ingestion_run_id = %s""",
                    (
                        datetime.now(UTC),
                        type(error).__name__,
                        "Catalog discovery request failed; inspect the redacted request ledger.",
                        run_id,
                    ),
                )
                connection.commit()
                raise
            except Exception as error:
                connection.rollback()
                if request is not None:
                    _record_failed_request(cursor, run_id, sequence, request, error)
                cursor.execute(
                    """UPDATE GOVERNANCE.INGESTION_RUNS
                    SET status = 'FAILED', completed_at = %s, error_classification = %s,
                        redacted_error = %s
                    WHERE ingestion_run_id = %s""",
                    (
                        datetime.now(UTC),
                        type(error).__name__,
                        "Catalog discovery request failed; inspect the redacted request ledger.",
                        run_id,
                    ),
                )
                connection.commit()
                raise
    return {
        "ingestion_run_id": run_id,
        "status": "COMPLETED",
        "request_count": len(requests),
        "config_sha256": config_sha256,
    }


def run_production_schedule() -> dict[str, Any]:
    """Run the production-only CDC refresh path after steward approval.

    The App Platform schedule is the caller.  Approval remains enforced inside
    ``ingest_approved_cdc`` by the active source-version lookup; this command
    never creates an approval or substitutes a DEV source version.
    """
    settings = PipelineSettings()
    if settings.topx_env != "prod":
        raise ValueError("The approved-source schedule may run only in production")
    ingestion = ingest_approved_cdc(trigger_type="SCHEDULED")
    promotion = build_approved_cdc_models(str(ingestion["source_version_id"]))
    return {"ingestion": ingestion, "promotion": promotion, "status": "COMPLETED"}
