"""Append-only catalog discovery orchestration for the governed DEV pipeline."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

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
    s3 = _spaces_client(settings)
    with connect(SnowflakeSettings()) as connection:
        connection.autocommit(False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO GOVERNANCE.INGESTION_RUNS
                    (ingestion_run_id, resource_key, run_mode, trigger_type, status,
                     config_sha256, started_at)
                    VALUES (%s, %s, 'DISCOVERY', 'SCHEDULED', 'RUNNING', %s, %s)""",
                    (run_id, "catalog_discovery", config_sha256, started_at),
                )
                sequence = 0
                for original_request in requests:
                    request: DiscoveryRequest | None = _catalog_request(original_request, settings)
                    offset = 0
                    while request is not None:
                        sequence += 1
                        request_id = str(uuid.uuid4())
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
                                json.dumps(
                                    redact_mapping(
                                        {
                                            "catalog_id": request.catalog_id,
                                            "term": request.term,
                                            **request.headers,
                                        }
                                    )
                                ),
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
        except Exception:
            connection.rollback()
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
