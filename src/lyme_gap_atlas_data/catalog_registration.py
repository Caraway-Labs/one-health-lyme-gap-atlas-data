"""Normalize immutable catalog-discovery artifacts into governed candidates.

This module deliberately stops at candidate registration.  It never follows a
publisher URL, collects a sample, scores a candidate, or authorizes ingestion.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from io import TextIOWrapper
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from .settings import PipelineSettings

_SENSITIVE_QUERY_PARAMETERS = {
    "access_token",
    "api_key",
    "apikey",
    "key",
    "signature",
    "sig",
    "token",
}

# Bound every JSON-backed Snowflake MERGE independently of the size of an
# immutable discovery artifact. These limits protect the X-Small runtime from
# a single unusually large catalog response while retaining resumable offsets.
REGISTRATION_DATASET_CHUNK_SIZE = 50
REGISTRATION_RESOURCE_CHUNK_SIZE = 1_000


@dataclass(frozen=True)
class CatalogResource:
    """One normalized, non-authoritative publisher-resource candidate."""

    resource_type: str
    resource_url: str | None
    canonical_source_url: str | None
    api_dataset_id: str | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class CatalogDataset:
    """One normalized catalog record with its candidate resources."""

    catalog_id: str
    catalog_record_id: str
    dataset_key: str
    payload: dict[str, Any]
    resources: tuple[CatalogResource, ...]


@dataclass(frozen=True)
class RegistrationDataset:
    """One dataset and the immutable discovery evidence required to register it."""

    dataset: CatalogDataset
    artifact_id: str
    ingestion_run_id: str
    ingestion_request_id: str
    term: str


def _stable_id(*values: str) -> str:
    return hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()


def canonicalize_public_url(value: object) -> str | None:
    """Normalize a public HTTP(S) URL without retaining secret query values."""
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return None
    public_query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in _SENSITIVE_QUERY_PARAMETERS
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            path,
            urlencode(public_query, doseq=True),
            "",
        )
    )


def _resource_type(*, access_level: object, hint: str) -> str:
    if isinstance(access_level, str) and access_level.casefold() not in {"public", "open"}:
        return "CONTROLLED_ACCESS"
    return hint


def _resource(
    *,
    resource_type: str,
    url: object,
    access_level: object,
    api_dataset_id: object,
    payload: dict[str, Any],
) -> CatalogResource | None:
    canonical_url = canonicalize_public_url(url)
    if canonical_url is None:
        return None
    return CatalogResource(
        resource_type=_resource_type(access_level=access_level, hint=resource_type),
        resource_url=canonical_url,
        canonical_source_url=canonical_url,
        api_dataset_id=str(api_dataset_id) if api_dataset_id else None,
        payload=payload,
    )


def _datagov_datasets(payload: dict[str, Any]) -> list[CatalogDataset]:
    datasets: list[CatalogDataset] = []
    results = payload.get("results", [])
    if not isinstance(results, list):
        return datasets
    for result in results:
        if not isinstance(result, dict):
            continue
        dcat_value = result.get("dcat")
        dcat: dict[str, Any] = dcat_value if isinstance(dcat_value, dict) else {}
        record_id = str(result.get("identifier") or dcat.get("identifier") or "")
        if not record_id:
            record_id = _stable_id(str(result.get("title", "")), str(result.get("landingPage", "")))
        title = str(result.get("title") or dcat.get("title") or "Untitled catalog record")
        access_level = result.get("accessLevel", dcat.get("accessLevel"))
        base_payload = {
            "title": title,
            "description": result.get("description", dcat.get("description")),
            "publisher": result.get("publisher", dcat.get("publisher")),
            "keywords": result.get("keyword", dcat.get("keyword", [])),
            "catalog_record": result,
        }
        resources: list[CatalogResource] = []
        landing_page = result.get("landingPage", dcat.get("landingPage"))
        landing = _resource(
            resource_type="LANDING_PAGE",
            url=landing_page,
            access_level=access_level,
            api_dataset_id=None,
            payload={**base_payload, "resource_role": "landing_page"},
        )
        if landing is not None:
            resources.append(landing)
        for distribution in dcat.get("distribution") or []:
            if not isinstance(distribution, dict):
                continue
            distribution_payload = {**base_payload, "distribution": distribution}
            download = _resource(
                resource_type="DATA",
                url=distribution.get("downloadURL"),
                access_level=access_level,
                api_dataset_id=None,
                payload={**distribution_payload, "resource_role": "download"},
            )
            access = _resource(
                resource_type="API",
                url=distribution.get("accessURL"),
                access_level=access_level,
                api_dataset_id=None,
                payload={**distribution_payload, "resource_role": "access"},
            )
            resources.extend(item for item in (download, access) if item is not None)
        for documentation_url in [
            dcat.get("describedBy"),
            *([item for item in dcat.get("references") or [] if isinstance(item, str)]),
        ]:
            documentation = _resource(
                resource_type="DOCUMENTATION",
                url=documentation_url,
                access_level=access_level,
                api_dataset_id=None,
                payload={**base_payload, "resource_role": "documentation"},
            )
            if documentation is not None:
                resources.append(documentation)
        datasets.append(
            CatalogDataset(
                catalog_id="DATA_GOV",
                catalog_record_id=record_id,
                dataset_key=f"data_gov:{record_id}",
                payload=base_payload,
                resources=tuple(_deduplicate_resources(resources)),
            )
        )
    return datasets


def _socrata_datasets(catalog_id: str, payload: dict[str, Any]) -> list[CatalogDataset]:
    datasets: list[CatalogDataset] = []
    results = payload.get("results", [])
    if not isinstance(results, list):
        return datasets
    for result in results:
        if not isinstance(result, dict):
            continue
        resource_value = result.get("resource")
        resource: dict[str, Any] = resource_value if isinstance(resource_value, dict) else {}
        metadata_value = result.get("metadata")
        metadata: dict[str, Any] = metadata_value if isinstance(metadata_value, dict) else {}
        resource_id = resource.get("id")
        domain = metadata.get("domain")
        record_id = str(resource_id or result.get("id") or "")
        if not record_id:
            record_id = _stable_id(str(resource.get("name", "")), str(result.get("permalink", "")))
        title = str(resource.get("name") or result.get("name") or "Untitled catalog record")
        api_url = (
            f"https://{domain}/resource/{resource_id}.json"
            if isinstance(domain, str) and resource_id
            else None
        )
        landing_url = result.get("permalink") or result.get("link")
        base_payload = {
            "title": title,
            "description": resource.get("description"),
            "publisher": metadata.get("domain"),
            "keywords": metadata.get("tags", []),
            "catalog_record": result,
        }
        resources = [
            item
            for item in (
                _resource(
                    resource_type="API",
                    url=api_url,
                    access_level="public",
                    api_dataset_id=resource_id,
                    payload={**base_payload, "resource_role": "socrata_api"},
                ),
                _resource(
                    resource_type="LANDING_PAGE",
                    url=landing_url,
                    access_level="public",
                    api_dataset_id=resource_id,
                    payload={**base_payload, "resource_role": "landing_page"},
                ),
            )
            if item is not None
        ]
        datasets.append(
            CatalogDataset(
                catalog_id=catalog_id,
                catalog_record_id=record_id,
                dataset_key=f"{catalog_id.casefold()}:{record_id}",
                payload=base_payload,
                resources=tuple(_deduplicate_resources(resources)),
            )
        )
    return datasets


def normalize_catalog_payload(catalog_id: str, payload: dict[str, Any]) -> list[CatalogDataset]:
    """Normalize one already-captured catalog response without network access."""
    if catalog_id == "DATA_GOV":
        return _datagov_datasets(payload)
    if catalog_id in {"HEALTHDATA_GOV", "SOCRATA_ODN"}:
        return _socrata_datasets(catalog_id, payload)
    raise ValueError(f"Unsupported discovery catalog {catalog_id}")


def _deduplicate_resources(resources: list[CatalogResource]) -> list[CatalogResource]:
    unique: dict[tuple[str, str], CatalogResource] = {}
    for resource in resources:
        if resource.canonical_source_url is not None:
            unique.setdefault((resource.resource_type, resource.canonical_source_url), resource)
    return list(unique.values())


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


def _read_artifact_payload(
    s3: Any, settings: PipelineSettings, artifact_uri: str
) -> dict[str, Any]:
    parsed = urlsplit(artifact_uri)
    if parsed.scheme != "s3" or parsed.netloc != settings.spaces_bucket or not parsed.path:
        raise ValueError("Catalog artifact is outside the configured private bucket")
    # Decode directly from the streaming response.  Keeping an additional bytes
    # buffer and decoded string alongside a large immutable artifact can exceed
    # the small scheduled-job memory limit before the bounded checkpoint is made.
    body = s3.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))["Body"]
    stream = TextIOWrapper(body, encoding="utf-8")
    try:
        payload = json.load(stream)
    finally:
        stream.detach()
        body.close()
    if not isinstance(payload, dict):
        raise ValueError("Catalog artifact payload must be a JSON object")
    return payload


def _completed_artifacts(
    cursor: Any, config_sha256: str
) -> list[tuple[str, str, str, str, str, str]]:
    cursor.execute(
        """SELECT COUNT_IF(status = 'COMPLETED')
           FROM GOVERNANCE.INGESTION_RUNS
           WHERE resource_key = 'catalog_discovery' AND run_mode = 'DISCOVERY'
             AND config_sha256 = %s""",
        (config_sha256,),
    )
    (completed,) = cursor.fetchone()
    if int(completed or 0) < 1:
        raise ValueError("Discovery configuration has no completed run")
    cursor.execute(
        """WITH RECURSIVE completed_chain AS (
             SELECT ingestion_run_id, resumed_from_ingestion_run_id
             FROM GOVERNANCE.INGESTION_RUNS
             WHERE resource_key = 'catalog_discovery' AND run_mode = 'DISCOVERY'
               AND config_sha256 = %s AND status = 'COMPLETED'
             UNION ALL
             SELECT prior.ingestion_run_id, prior.resumed_from_ingestion_run_id
             FROM GOVERNANCE.INGESTION_RUNS prior
             JOIN completed_chain chain
               ON prior.ingestion_run_id = chain.resumed_from_ingestion_run_id
           )
           SELECT a.artifact_id, a.ingestion_run_id, q.ingestion_request_id, a.artifact_uri,
                  q.redacted_request:catalog_id::VARCHAR, q.redacted_request:term::VARCHAR
           FROM GOVERNANCE.RAW_ARTIFACTS a
           JOIN GOVERNANCE.INGESTION_REQUESTS q ON q.ingestion_request_id = a.ingestion_request_id
           JOIN completed_chain chain ON chain.ingestion_run_id = a.ingestion_run_id
           WHERE a.artifact_type = 'CATALOG_METADATA'
             AND q.status_code = 200
           ORDER BY a.created_at, a.artifact_id""",
        (config_sha256,),
    )
    return [
        (str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]), str(row[5]))
        for row in cursor.fetchall()
    ]


def latest_completed_discovery_config_sha256() -> str:
    """Return the configuration of the newest completed governed discovery run."""
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT config_sha256
               FROM GOVERNANCE.INGESTION_RUNS
               WHERE resource_key = 'catalog_discovery' AND run_mode = 'DISCOVERY'
                 AND status = 'COMPLETED' AND config_sha256 IS NOT NULL
               ORDER BY completed_at DESC, started_at DESC
               LIMIT 1"""
        )
        row = cursor.fetchone()
    if row is None or not isinstance(row[0], str):
        raise ValueError("No completed catalog-discovery run is available for registration")
    return row[0]


def _write_registration_dataset_batch(
    cursor: Any, datasets: list[RegistrationDataset], observed_at: datetime
) -> int:
    """Write a bounded dataset slice in three set-based merges before checkpointing it."""
    dataset_rows: list[dict[str, object]] = []
    resource_rows: list[dict[str, object]] = []
    for item in datasets:
        dataset = item.dataset
        dataset_payload = json.dumps(dataset.payload, sort_keys=True, separators=(",", ":"))
        dataset_sha256 = hashlib.sha256(dataset_payload.encode("utf-8")).hexdigest()
        dataset_id = _stable_id(dataset.catalog_id, dataset.catalog_record_id, dataset_sha256)
        dataset_rows.append(
            {
                "catalog_dataset_id": dataset_id,
                "dataset_key": dataset.dataset_key,
                "catalog_name": dataset.catalog_id,
                "catalog_record_id": dataset.catalog_record_id,
                "metadata_payload": dataset.payload,
                "metadata_sha256": dataset_sha256,
            }
        )
        for resource in dataset.resources:
            canonical = resource.canonical_source_url or f"catalog-record:{dataset.dataset_key}"
            resource_id = _stable_id(dataset_id, resource.resource_type, canonical)
            resource_rows.append(
                {
                    "catalog_resource_id": resource_id,
                    "catalog_dataset_id": dataset_id,
                    "resource_key": f"candidate:{_stable_id(canonical)[:32]}",
                    "resource_type": resource.resource_type,
                    "resource_url": resource.resource_url,
                    "canonical_source_url": resource.canonical_source_url,
                    "api_dataset_id": resource.api_dataset_id,
                    "resource_payload": resource.payload,
                    "observation_id": _stable_id(item.artifact_id, resource_id),
                    "ingestion_run_id": item.ingestion_run_id,
                    "ingestion_request_id": item.ingestion_request_id,
                    "artifact_id": item.artifact_id,
                    "catalog_id": dataset.catalog_id,
                    "catalog_record_id": dataset.catalog_record_id,
                    "matched_term": item.term,
                }
            )
    for start in range(0, len(dataset_rows), REGISTRATION_DATASET_CHUNK_SIZE):
        dataset_json = json.dumps(
            dataset_rows[start : start + REGISTRATION_DATASET_CHUNK_SIZE],
            sort_keys=True,
            separators=(",", ":"),
        )
        cursor.execute(
            """MERGE INTO GOVERNANCE.CATALOG_DATASETS target
           USING (
             SELECT value:catalog_dataset_id::VARCHAR AS catalog_dataset_id,
                    value:dataset_key::VARCHAR AS dataset_key,
                    value:catalog_name::VARCHAR AS catalog_name,
                    value:catalog_record_id::VARCHAR AS catalog_record_id,
                    value:metadata_payload AS metadata_payload,
                    value:metadata_sha256::VARCHAR AS metadata_sha256,
                    %s AS discovered_at
             FROM TABLE(FLATTEN(input => PARSE_JSON(%s)))
           ) source
           ON target.catalog_dataset_id = source.catalog_dataset_id
           WHEN NOT MATCHED THEN INSERT (catalog_dataset_id, dataset_key, catalog_name,
             catalog_record_id, metadata_payload, metadata_sha256, discovered_at, is_current)
             VALUES (source.catalog_dataset_id, source.dataset_key, source.catalog_name,
               source.catalog_record_id, source.metadata_payload, source.metadata_sha256,
               source.discovered_at, TRUE)""",
            (observed_at, dataset_json),
        )
    if not resource_rows:
        return 0
    for start in range(0, len(resource_rows), REGISTRATION_RESOURCE_CHUNK_SIZE):
        source_json = json.dumps(
            resource_rows[start : start + REGISTRATION_RESOURCE_CHUNK_SIZE],
            sort_keys=True,
            separators=(",", ":"),
        )
        cursor.execute(
            """MERGE INTO GOVERNANCE.CATALOG_RESOURCES target
           USING (
             SELECT value:catalog_resource_id::VARCHAR AS catalog_resource_id,
                    value:catalog_dataset_id::VARCHAR AS catalog_dataset_id,
                    value:resource_key::VARCHAR AS resource_key,
                    value:resource_type::VARCHAR AS resource_type,
                    value:resource_url::VARCHAR AS resource_url,
                    value:canonical_source_url::VARCHAR AS canonical_source_url,
                    value:api_dataset_id::VARCHAR AS api_dataset_id,
                    value:resource_payload AS resource_payload,
                    %s AS registered_at
             FROM TABLE(FLATTEN(input => PARSE_JSON(%s)))
           ) source
           ON target.catalog_resource_id = source.catalog_resource_id
           WHEN NOT MATCHED THEN INSERT (catalog_resource_id, catalog_dataset_id, resource_key,
             resource_type, resource_url, canonical_source_url, api_dataset_id, resource_payload,
             registered_at, is_active) VALUES (source.catalog_resource_id,
             source.catalog_dataset_id,
             source.resource_key, source.resource_type, source.resource_url,
             source.canonical_source_url, source.api_dataset_id, source.resource_payload,
             source.registered_at, TRUE)""",
            (observed_at, source_json),
        )
        cursor.execute(
            """MERGE INTO GOVERNANCE.CATALOG_DISCOVERY_OBSERVATIONS target
           USING (
             SELECT value:observation_id::VARCHAR AS observation_id,
                    value:ingestion_run_id::VARCHAR AS ingestion_run_id,
                    value:ingestion_request_id::VARCHAR AS ingestion_request_id,
                    value:artifact_id::VARCHAR AS artifact_id,
                    value:catalog_id::VARCHAR AS catalog_id,
                    value:catalog_record_id::VARCHAR AS catalog_record_id,
                    value:matched_term::VARCHAR AS matched_term,
                    value:catalog_dataset_id::VARCHAR AS catalog_dataset_id,
                    value:catalog_resource_id::VARCHAR AS catalog_resource_id,
                    value:resource_key::VARCHAR AS canonical_resource_key,
                    %s AS observed_at
             FROM TABLE(FLATTEN(input => PARSE_JSON(%s)))
           ) source
           ON target.observation_id = source.observation_id
           WHEN NOT MATCHED THEN INSERT (observation_id, ingestion_run_id, ingestion_request_id,
             artifact_id, catalog_id, catalog_record_id, matched_term, catalog_dataset_id,
             catalog_resource_id, canonical_resource_key, observed_at)
             VALUES (source.observation_id, source.ingestion_run_id, source.ingestion_request_id,
               source.artifact_id, source.catalog_id, source.catalog_record_id, source.matched_term,
               source.catalog_dataset_id, source.catalog_resource_id, source.canonical_resource_key,
               source.observed_at)""",
            (observed_at, source_json),
        )
    return len(resource_rows)


def _claim_registration_batch(
    cursor: Any,
    config_sha256: str,
    maximum_artifacts: int,
    registration_run_id: str,
) -> tuple[list[tuple[str, str, str, str, str, str, int]], int]:
    """Durably claim a short artifact batch before any Spaces reads occur."""
    artifacts = _completed_artifacts(cursor, config_sha256)
    artifact_json = json.dumps(
        [{"artifact_id": artifact[0]} for artifact in artifacts], separators=(",", ":")
    )
    cursor.execute(
        """MERGE INTO GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS target
           USING (
             SELECT value:artifact_id::VARCHAR AS artifact_id, %s AS config_sha256
             FROM TABLE(FLATTEN(input => PARSE_JSON(%s)))
           ) source
           ON target.artifact_id = source.artifact_id
           WHEN NOT MATCHED THEN INSERT (artifact_id, config_sha256, status, attempt_count)
             VALUES (source.artifact_id, source.config_sha256, 'PENDING', 0)""",
        (config_sha256, artifact_json),
    )
    # Select from the durable ledger rather than simply slicing the artifact
    # list.  A prior interrupted invocation can leave an unexpired lease at
    # the front of the discovery chain; later pending artifacts must still be
    # eligible for a bounded pass instead of every scheduled invocation doing
    # zero work until that lease expires.
    cursor.execute(
        """SELECT artifact_id
           FROM GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS
           WHERE config_sha256 = %s
             AND (status IN ('PENDING', 'FAILED')
                  OR (status = 'IN_PROGRESS' AND lease_expires_at <= CURRENT_TIMESTAMP()))
           ORDER BY CASE status WHEN 'PENDING' THEN 0 WHEN 'IN_PROGRESS' THEN 1 ELSE 2 END,
                    COALESCE(started_at, TO_TIMESTAMP_NTZ(0)), artifact_id
           LIMIT %s""",
        (config_sha256, maximum_artifacts),
    )
    candidate_ids = [str(row[0]) for row in cursor.fetchall()]
    candidate_json = json.dumps(candidate_ids, separators=(",", ":"))
    cursor.execute(
        """UPDATE GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS
           SET status = 'IN_PROGRESS', registration_run_id = %s,
               attempt_count = attempt_count + 1, started_at = CURRENT_TIMESTAMP(),
               lease_expires_at = DATEADD(minute, 25, CURRENT_TIMESTAMP()),
               completed_at = NULL, redacted_error = NULL
           WHERE config_sha256 = %s
             AND artifact_id IN (
               SELECT value::VARCHAR FROM TABLE(FLATTEN(input => PARSE_JSON(%s)))
             )
             AND (status IN ('PENDING', 'FAILED')
                  OR (status = 'IN_PROGRESS' AND lease_expires_at <= CURRENT_TIMESTAMP()))""",
        (registration_run_id, config_sha256, candidate_json),
    )
    cursor.execute(
        """SELECT artifact_id, next_dataset_offset
           FROM GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS
           WHERE registration_run_id = %s AND status = 'IN_PROGRESS'
             AND artifact_id IN (
               SELECT value::VARCHAR FROM TABLE(FLATTEN(input => PARSE_JSON(%s)))
             )""",
        (registration_run_id, candidate_json),
    )
    offsets = {str(row[0]): int(row[1] or 0) for row in cursor.fetchall()}
    claimed = [
        (*artifact, offsets[artifact[0]]) for artifact in artifacts if artifact[0] in offsets
    ]
    return claimed, len(artifacts)


def _complete_registration_artifact(
    cursor: Any, artifact_id: str, registration_run_id: str
) -> None:
    cursor.execute(
        """UPDATE GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS
           SET status = 'COMPLETED', completed_at = CURRENT_TIMESTAMP(), lease_expires_at = NULL
           WHERE artifact_id = %s AND registration_run_id = %s""",
        (artifact_id, registration_run_id),
    )


def _advance_registration_dataset(
    cursor: Any, artifact_id: str, registration_run_id: str, next_dataset_offset: int
) -> None:
    cursor.execute(
        """UPDATE GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS
           SET next_dataset_offset = %s
           WHERE artifact_id = %s AND registration_run_id = %s AND status = 'IN_PROGRESS'""",
        (next_dataset_offset, artifact_id, registration_run_id),
    )


def _release_partial_registration_artifact(
    cursor: Any, artifact_id: str, registration_run_id: str
) -> None:
    cursor.execute(
        """UPDATE GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS
           SET status = 'PENDING', lease_expires_at = NULL
           WHERE artifact_id = %s AND registration_run_id = %s AND status = 'IN_PROGRESS'""",
        (artifact_id, registration_run_id),
    )


def _fail_registration_artifact(
    cursor: Any, artifact_id: str, registration_run_id: str, error: Exception
) -> None:
    """Retain a safe failure marker so a later bounded pass can resume."""
    cursor.execute(
        """UPDATE GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS
           SET status = 'FAILED', lease_expires_at = NULL, redacted_error = %s
           WHERE artifact_id = %s AND registration_run_id = %s""",
        (type(error).__name__, artifact_id, registration_run_id),
    )


def _remaining_registration_artifacts(cursor: Any, config_sha256: str, total_artifacts: int) -> int:
    cursor.execute(
        """SELECT COUNT(*) FROM GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS
           WHERE config_sha256 = %s AND status = 'COMPLETED'""",
        (config_sha256,),
    )
    (completed_artifacts,) = cursor.fetchone()
    return max(total_artifacts - int(completed_artifacts or 0), 0)


def register_completed_discovery(
    config_sha256: str, maximum_artifacts: int = 100, maximum_datasets: int = 10_000
) -> dict[str, int | str]:
    """Register a resumable bounded dataset slice without acquiring source payloads."""
    if len(config_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in config_sha256
    ):
        raise ValueError("config_sha256 must be a lowercase SHA-256 digest")
    if not 1 <= maximum_artifacts <= 100:
        raise ValueError("maximum_artifacts must be between 1 and 100")
    if not 1 <= maximum_datasets <= 10_000:
        raise ValueError("maximum_datasets must be between 1 and 10,000")
    settings = PipelineSettings()
    s3 = _spaces_client(settings)
    registration_run_id = str(uuid4())
    registered_datasets = 0
    registered_resources = 0
    observed_artifacts = 0
    processed_datasets = 0
    failed_artifacts = 0
    with connect(SnowflakeSettings()) as connection:
        connection.autocommit(False)
        with connection.cursor() as cursor:
            artifacts, available_artifacts = _claim_registration_batch(
                cursor, config_sha256, maximum_artifacts, registration_run_id
            )
            connection.commit()
            for artifact_index, (
                artifact_id,
                run_id,
                request_id,
                artifact_uri,
                catalog_id,
                term,
                dataset_offset,
            ) in enumerate(artifacts):
                # Do not read or normalize further artifacts once this pass has
                # reached its declared dataset boundary.  Release their leases
                # immediately so another bounded pass can claim them.
                if registered_datasets >= maximum_datasets:
                    for deferred_artifact, *_ in artifacts[artifact_index:]:
                        _release_partial_registration_artifact(
                            cursor, deferred_artifact, registration_run_id
                        )
                    connection.commit()
                    break
                try:
                    datasets = normalize_catalog_payload(
                        catalog_id, _read_artifact_payload(s3, settings, artifact_uri)
                    )
                except Exception as error:
                    # A read/normalization failure has no pending writes for
                    # this artifact. Its failure marker is committed with the
                    # rest of this invocation's transaction.
                    _fail_registration_artifact(cursor, artifact_id, registration_run_id, error)
                    failed_artifacts += 1
                    continue
                remaining_capacity = maximum_datasets - registered_datasets
                selected = datasets[dataset_offset : dataset_offset + max(remaining_capacity, 0)]
                if not selected:
                    if dataset_offset >= len(datasets):
                        _complete_registration_artifact(cursor, artifact_id, registration_run_id)
                        observed_artifacts += 1
                    else:
                        _release_partial_registration_artifact(
                            cursor, artifact_id, registration_run_id
                        )
                    connection.commit()
                    continue
                next_offset = dataset_offset
                try:
                    for start in range(0, len(selected), REGISTRATION_DATASET_CHUNK_SIZE):
                        artifact_datasets = [
                            RegistrationDataset(dataset, artifact_id, run_id, request_id, term)
                            for dataset in selected[start : start + REGISTRATION_DATASET_CHUNK_SIZE]
                        ]
                        if not artifact_datasets:
                            continue
                        registered_resources += _write_registration_dataset_batch(
                            cursor, artifact_datasets, datetime.now(UTC)
                        )
                        registered_datasets += len(artifact_datasets)
                        next_offset += len(artifact_datasets)
                        if next_offset >= len(datasets):
                            _complete_registration_artifact(
                                cursor, artifact_id, registration_run_id
                            )
                            observed_artifacts += 1
                        else:
                            _advance_registration_dataset(
                                cursor, artifact_id, registration_run_id, next_offset
                            )
                        # A successfully merged chunk must survive a later timeout. The
                        # next invocation resumes from this durable offset rather than
                        # replaying a large artifact-level MERGE.
                        connection.commit()
                except Exception as error:
                    # The current uncommitted merge is rolled back, while prior chunk
                    # checkpoints remain durable and safe to resume.
                    connection.rollback()
                    _fail_registration_artifact(cursor, artifact_id, registration_run_id, error)
                    connection.commit()
                    raise
                if next_offset < len(datasets):
                    _release_partial_registration_artifact(cursor, artifact_id, registration_run_id)
                    connection.commit()
            processed_datasets = registered_datasets
            remaining_artifacts = _remaining_registration_artifacts(
                cursor, config_sha256, available_artifacts
            )
    return {
        "status": "COMPLETED" if remaining_artifacts == 0 else "PARTIAL",
        "config_sha256": config_sha256,
        "registration_run_id": registration_run_id,
        "observed_artifacts": observed_artifacts,
        "failed_artifacts": failed_artifacts,
        "processed_datasets": processed_datasets,
        "available_artifacts": available_artifacts,
        "remaining_artifacts": remaining_artifacts,
        "registered_datasets": registered_datasets,
        "registered_resources": registered_resources,
    }


def register_latest_completed_discovery(
    maximum_artifacts: int = 100, maximum_datasets: int = 10_000
) -> dict[str, int | str]:
    """Materialize the newest completed discovery chain without source acquisition."""
    return register_completed_discovery(
        latest_completed_discovery_config_sha256(), maximum_artifacts, maximum_datasets
    )
