"""CDC/Socrata x5j9-wybp evidence acquisition; never full-ingests before approval."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import boto3  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from .artifacts import Artifact, create_artifact
from .assessment import Assessment
from .redaction import redact_mapping
from .settings import PipelineSettings

CDC_RESOURCE_ID = "cdc_lyme_x5j9_wybp"
SOURCE_CONFIG = Path(__file__).resolve().parents[2] / "config" / "sources" / "cdc_x5j9_wybp.yml"


def load_cdc_profile(path: Path = SOURCE_CONFIG) -> dict[str, Any]:
    """Load the version-controlled CDC source access profile."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("resource_key") != CDC_RESOURCE_ID:
        raise ValueError("Invalid CDC x5j9-wybp source profile")
    if document.get("deterministic_order_clause") != ":id ASC":
        raise ValueError("CDC sample and ingestion require deterministic :id ASC order")
    return document


def _fetch_json(url: str, token: str | None = None, retries: int = 3) -> Any:
    headers = {"Accept": "application/json"}
    if token:
        headers["X-App-Token"] = token
    for attempt in range(retries):
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as response:  # nosec B310: CDC HTTPS endpoint
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


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


def _save_artifact(
    s3: Any, settings: PipelineSettings, resource_key: str, run_id: str, payload: bytes
) -> Artifact:
    artifact = create_artifact(
        payload=payload, environment=settings.topx_env, resource_key=resource_key, run_id=run_id
    )
    s3.put_object(
        Bucket=settings.spaces_bucket,
        Key=f"{settings.spaces_prefix}/{artifact.object_key}",
        Body=payload,
        ContentType="application/json",
    )
    return artifact


def collect_cdc_evidence(sample_limit: int = 25) -> dict[str, Any]:
    """Capture metadata and an ordered sample, then make a pending review candidate."""
    if not 1 <= sample_limit <= 100:
        raise ValueError("sample_limit must be between 1 and 100")
    settings = PipelineSettings()
    profile = load_cdc_profile()
    token = settings.socrata_app_token.get_secret_value() if settings.socrata_app_token else None
    metadata_url = str(profile["metadata_endpoint_template"])
    sample_url = (
        str(profile["endpoint_template"])
        + "?"
        + urlencode({"$limit": sample_limit, "$order": str(profile["deterministic_order_clause"])})
    )
    metadata = _fetch_json(metadata_url, token)
    sample = _fetch_json(sample_url, token)
    if not isinstance(sample, list) or not sample:
        raise ValueError("CDC sample was empty or malformed")
    columns = metadata.get("columns", []) if isinstance(metadata, dict) else []
    required = {"fips", "year", "case_status", "frequency"}
    observed = {str(key) for row in sample if isinstance(row, dict) for key in row}
    if not required.issubset(observed):
        raise ValueError("CDC sample does not meet the configured geography/time evidence contract")

    run_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    metadata_payload = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
    sample_payload = json.dumps(sample, sort_keys=True, separators=(",", ":")).encode()
    s3 = _spaces_client(settings)
    metadata_artifact = _save_artifact(s3, settings, CDC_RESOURCE_ID, run_id, metadata_payload)
    sample_artifact = _save_artifact(s3, settings, CDC_RESOURCE_ID, run_id, sample_payload)
    profile_sha256 = hashlib.sha256(
        yaml.safe_dump(profile, sort_keys=True).encode("utf-8")
    ).hexdigest()
    schema_payload = json.dumps(columns, sort_keys=True, separators=(",", ":"))
    schema_sha256 = hashlib.sha256(schema_payload.encode()).hexdigest()
    assessment = Assessment(95, 95, 95, 90, 90)
    metadata_raw_artifact_id = str(uuid.uuid4())
    sample_raw_artifact_id = str(uuid.uuid4())

    with connect(SnowflakeSettings()) as connection:
        connection.autocommit(False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO GOVERNANCE.INGESTION_RUNS
                    (ingestion_run_id, resource_key, run_mode, trigger_type, status, code_version,
                     config_sha256, started_at, completed_at)
                    VALUES (%s, %s, 'EVIDENCE_ONLY', 'MANUAL', 'COMPLETED', 'cdc-x5j9-evidence-v1',
                            %s, %s, %s)""",
                    (run_id, CDC_RESOURCE_ID, profile_sha256, now, now),
                )
                dataset_id = str(uuid.uuid4())
                cursor.execute(
                    """INSERT INTO GOVERNANCE.CATALOG_DATASETS
                    (catalog_dataset_id, dataset_key, catalog_name, catalog_record_id, metadata_payload,
                     metadata_sha256, discovered_at, is_current)
                    SELECT %s, %s, 'CDC_SOCRATA', 'x5j9-wybp', PARSE_JSON(%s), %s, %s, TRUE""",
                    (
                        dataset_id,
                        CDC_RESOURCE_ID,
                        json.dumps(metadata),
                        metadata_artifact.sha256,
                        now,
                    ),
                )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.CATALOG_RESOURCES
                    (catalog_resource_id, catalog_dataset_id, resource_key, resource_type, resource_url,
                     canonical_source_url, api_dataset_id, resource_payload, registered_at, is_active)
                    SELECT %s, %s, %s, 'API', %s, %s, 'x5j9-wybp', PARSE_JSON(%s), %s, TRUE""",
                    (
                        str(uuid.uuid4()),
                        dataset_id,
                        CDC_RESOURCE_ID,
                        str(profile["endpoint_template"]),
                        str(profile["endpoint_template"]),
                        json.dumps(
                            {"title": metadata.get("name"), "license": metadata.get("license")}
                        ),
                        now,
                    ),
                )
                cursor.execute(
                    "UPDATE GOVERNANCE.SOURCE_ACCESS_PROFILES SET effective_to = %s "
                    "WHERE resource_key = %s AND effective_to IS NULL",
                    (now, CDC_RESOURCE_ID),
                )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.SOURCE_ACCESS_PROFILES
                    (source_access_profile_id, resource_key, profile_version, connector_name,
                     endpoint_template, deterministic_order_clause, incremental_strategy,
                     configuration_sha256, effective_from)
                    VALUES (%s, %s, %s, 'SOCRATA_SODA2', %s, %s, %s, %s, %s)""",
                    (
                        str(uuid.uuid4()),
                        CDC_RESOURCE_ID,
                        int(profile["profile_version"]),
                        str(profile["endpoint_template"]),
                        str(profile["deterministic_order_clause"]),
                        str(profile["incremental_strategy"]),
                        profile_sha256,
                        now,
                    ),
                )
                for endpoint, purpose, artifact, raw_artifact_id in (
                    (metadata_url, "SOURCE_METADATA", metadata_artifact, metadata_raw_artifact_id),
                    (sample_url, "ORDERED_SOURCE_SAMPLE", sample_artifact, sample_raw_artifact_id),
                ):
                    request_id = str(uuid.uuid4())
                    cursor.execute(
                        """INSERT INTO GOVERNANCE.INGESTION_REQUESTS
                        (ingestion_request_id, ingestion_run_id, request_sequence, request_purpose,
                         endpoint, redacted_request, status_code, response_sha256, retrieved_row_count, created_at)
                        SELECT %s, %s, %s, %s, %s, PARSE_JSON(%s), 200, %s, %s, %s""",
                        (
                            request_id,
                            run_id,
                            1 if purpose == "SOURCE_METADATA" else 2,
                            purpose,
                            endpoint.split("?", maxsplit=1)[0],
                            json.dumps(
                                redact_mapping({"endpoint": endpoint, "sample_limit": sample_limit})
                            ),
                            artifact.sha256,
                            1 if purpose == "SOURCE_METADATA" else len(sample),
                            now,
                        ),
                    )
                    cursor.execute(
                        """INSERT INTO GOVERNANCE.RAW_ARTIFACTS
                        (artifact_id, ingestion_run_id, ingestion_request_id, artifact_uri, artifact_type,
                         media_type, byte_count, sha256, created_at)
                        VALUES (%s, %s, %s, %s, %s, 'application/json', %s, %s, %s)""",
                        (
                            raw_artifact_id,
                            run_id,
                            request_id,
                            f"s3://{settings.spaces_bucket}/{settings.spaces_prefix}/{artifact.object_key}",
                            purpose,
                            artifact.byte_count,
                            artifact.sha256,
                            now,
                        ),
                    )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS
                    (source_document_snapshot_id, resource_key, document_type, document_url, artifact_id,
                     content_sha256, retrieved_at, is_material_change)
                    VALUES (%s, %s, 'METADATA_AND_LICENSE', %s, %s, %s, %s, FALSE)""",
                    (
                        str(uuid.uuid4()),
                        CDC_RESOURCE_ID,
                        metadata_url,
                        metadata_raw_artifact_id,
                        metadata_artifact.sha256,
                        now,
                    ),
                )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.SCHEMA_SNAPSHOTS
                    (schema_snapshot_id, resource_key, schema_fingerprint, schema_payload, retrieved_at)
                    SELECT %s, %s, %s, PARSE_JSON(%s), %s""",
                    (str(uuid.uuid4()), CDC_RESOURCE_ID, schema_sha256, schema_payload, now),
                )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.DATASET_QUALITY_ASSESSMENTS
                    (dataset_quality_assessment_id, resource_key, assessment_status, relevance_score,
                     joinability_score, accessibility_score, documentation_score, quality_score, overall_score,
                     recommendation, limitations, assessed_at)
                    VALUES (%s, %s, 'PENDING_REVIEW', 95, 95, 95, 90, 90, %s, %s, %s, %s)""",
                    (
                        str(uuid.uuid4()),
                        CDC_RESOURCE_ID,
                        assessment.score,
                        assessment.recommendation,
                        "County-of-residence surveillance, 2022-current era; preserve null, zero, unknown, suppressed, and not-reported states.",
                        now,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "ingestion_run_id": run_id,
        "resource_key": CDC_RESOURCE_ID,
        "sample_rows": len(sample),
        "metadata_sha256": metadata_artifact.sha256,
        "sample_sha256": sample_artifact.sha256,
        "schema_sha256": schema_sha256,
        "status": "PENDING_STEWARD_REVIEW",
    }


def ingest_approved_cdc(page_size: int = 5_000, *, trigger_type: str = "MANUAL") -> dict[str, Any]:
    """Fully acquire the approved CDC source through immutable artifacts and COPY.

    This command is intentionally explicit: Streamlit approval enables it, but
    never invokes it.  The caller must run it in the isolated governed runtime.
    """
    if trigger_type not in {"MANUAL", "SCHEDULED", "BACKFILL", "RETRY"}:
        raise ValueError("Unsupported ingestion trigger type")
    profile = load_cdc_profile()
    if page_size < 1 or page_size > 10_000:
        raise ValueError("page_size must be between 1 and 10,000")
    settings = PipelineSettings()
    token = settings.socrata_app_token.get_secret_value() if settings.socrata_app_token else None
    run_id, now = str(uuid.uuid4()), datetime.now(UTC)
    s3 = _spaces_client(settings)
    rows_loaded = 0
    with connect(SnowflakeSettings()) as connection:
        connection.autocommit(False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT data_source_version_id FROM GOVERNANCE.DATA_SOURCE_VERSIONS
                    WHERE resource_key = %s AND status IN ('APPROVED', 'CONDITIONAL')
                      AND retired_at IS NULL ORDER BY created_at DESC LIMIT 1""",
                    (CDC_RESOURCE_ID,),
                )
                source_version = cursor.fetchone()
                if source_version is None:
                    raise ValueError(
                        "CDC full ingestion requires an active steward-approved source version"
                    )
                source_version_id = str(source_version[0])
                cursor.execute(
                    """INSERT INTO GOVERNANCE.INGESTION_RUNS
                    (ingestion_run_id, resource_key, run_mode, trigger_type, status, code_version, started_at)
                    VALUES (%s, %s, 'FULL_REFRESH', %s, 'RUNNING', 'cdc-x5j9-full-v1', %s)""",
                    (run_id, CDC_RESOURCE_ID, trigger_type, now),
                )
                with TemporaryDirectory(prefix="oh-lyme-cdc-") as directory:
                    offset, sequence = 0, 0
                    while True:
                        url = (
                            str(profile["endpoint_template"])
                            + "?"
                            + urlencode(
                                {
                                    "$limit": page_size,
                                    "$offset": offset,
                                    "$order": profile["deterministic_order_clause"],
                                }
                            )
                        )
                        page = _fetch_json(url, token)
                        if not isinstance(page, list):
                            raise ValueError("CDC full-ingestion page was malformed")
                        if not page:
                            break
                        sequence += 1
                        payload = "\n".join(
                            json.dumps(row, separators=(",", ":")) for row in page
                        ).encode()
                        artifact = _save_artifact(s3, settings, CDC_RESOURCE_ID, run_id, payload)
                        request_id, artifact_id = str(uuid.uuid4()), str(uuid.uuid4())
                        cursor.execute(
                            """INSERT INTO GOVERNANCE.INGESTION_REQUESTS
                            (ingestion_request_id, ingestion_run_id, request_sequence, request_purpose, endpoint,
                             redacted_request, status_code, response_sha256, retrieved_row_count, created_at)
                            SELECT %s, %s, %s, 'FULL_DATA_PAGE', %s, PARSE_JSON(%s), 200, %s, %s, %s""",
                            (
                                request_id,
                                run_id,
                                sequence,
                                str(profile["endpoint_template"]),
                                json.dumps(
                                    redact_mapping(
                                        {
                                            "offset": offset,
                                            "limit": page_size,
                                            "order": profile["deterministic_order_clause"],
                                        }
                                    )
                                ),
                                artifact.sha256,
                                len(page),
                                now,
                            ),
                        )
                        cursor.execute(
                            """INSERT INTO GOVERNANCE.RAW_ARTIFACTS
                            (artifact_id, ingestion_run_id, ingestion_request_id, artifact_uri, artifact_type,
                             media_type, byte_count, sha256, created_at)
                            VALUES (%s, %s, %s, %s, 'FULL_DATA_PAGE', 'application/x-ndjson', %s, %s, %s)""",
                            (
                                artifact_id,
                                run_id,
                                request_id,
                                f"s3://{settings.spaces_bucket}/{settings.spaces_prefix}/{artifact.object_key}",
                                artifact.byte_count,
                                artifact.sha256,
                                now,
                            ),
                        )
                        local_path = Path(directory) / f"{sequence}.jsonl"
                        local_path.write_bytes(payload)
                        stage_path = f"{run_id}/{artifact_id}.jsonl"
                        cursor.execute(
                            f"PUT {local_path.as_uri()} @RAW.INGESTION_TRANSIENT_STAGE/{stage_path} AUTO_COMPRESS=FALSE"
                        )
                        cursor.execute(
                            f"""COPY INTO RAW.CDC_LYME_X5J9_WYBP
                            (payload, data_source_version_id, ingestion_run_id, artifact_id, source_url,
                             redacted_source_query, source_record_id, source_row_hash, retrieved_at)
                            FROM (SELECT $1, %s, %s, %s, %s, %s, $1:":id"::VARCHAR,
                                         SHA2(TO_JSON($1), 256), %s
                                  FROM @RAW.INGESTION_TRANSIENT_STAGE/{stage_path})
                            FILE_FORMAT=(TYPE=JSON) ON_ERROR='ABORT_STATEMENT'""",
                            (
                                source_version_id,
                                run_id,
                                artifact_id,
                                str(profile["endpoint_template"]),
                                json.dumps({"offset": offset, "limit": page_size}),
                                now,
                            ),
                        )
                        rows_loaded += len(page)
                        if len(page) < page_size:
                            break
                        offset += page_size
                cursor.execute(
                    """UPDATE GOVERNANCE.INGESTION_RUNS SET status = 'COMPLETED', completed_at = %s
                    WHERE ingestion_run_id = %s""",
                    (datetime.now(UTC), run_id),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "ingestion_run_id": run_id,
        "resource_key": CDC_RESOURCE_ID,
        "source_version_id": source_version_id,
        "rows_loaded": rows_loaded,
        "status": "COMPLETED",
    }


def build_approved_cdc_models(source_version_id: str) -> dict[str, str]:
    """Build only the CDC dbt path after a successful governed RAW load."""
    result = subprocess.run(
        [
            "uv",
            "run",
            "dbt",
            "build",
            "--project-dir",
            "dbt",
            "--profiles-dir",
            "dbt",
            "--select",
            "stg_cdc_lyme_x5j9_wybp+",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("CDC dbt build failed; inspect the governed dbt logs")
    return {"source_version_id": source_version_id, "status": "COMPLETED"}
