"""CDC/Socrata x5j9-wybp evidence acquisition; never full-ingests before approval."""

# ruff: noqa: E501

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
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
from .cdc_historical import validate_historical_evidence
from .cdc_incidents import record_incident
from .cdc_policy import metadata_fingerprint, transient_source_error
from .cdc_publication import cdc_operation, publication_context, publish_snapshot
from .cdc_quality import CdcQualityError, record_cdc_quality
from .redaction import redact_mapping
from .settings import PipelineSettings

CDC_RESOURCE_ID = "cdc_lyme_x5j9_wybp"
SOURCE_CONFIG = Path(__file__).resolve().parents[2] / "config" / "sources" / "cdc_x5j9_wybp.yml"
logger = logging.getLogger(__name__)


class CdcDbtBuildError(RuntimeError):
    """A dbt failure represented only by a controlled, non-secret category."""

    def __init__(self, classification: str) -> None:
        self.classification = classification
        super().__init__(f"CDC dbt build failed [{classification}]")


def _dbt_failure_classification(result: subprocess.CompletedProcess[str]) -> str:
    """Classify dbt output without retaining or emitting its sensitive text."""
    output = f"{result.stdout}\n{result.stderr}".lower()
    if any(
        marker in output
        for marker in (
            "private key",
            "private_key",
            "encrypted private key",
            "bad decrypt",
            "incorrect password",
            "could not deserialize key data",
        )
    ):
        return "PRIVATE_KEY_AUTH"
    if "not authorized" in output or "insufficient privileges" in output:
        return "SNOWFLAKE_AUTHORIZATION"
    if "database error" in output:
        return "SNOWFLAKE_DATABASE"
    if "compilation error" in output or "parsing error" in output:
        return "DBT_COMPILATION"
    if "could not connect" in output or "connection" in output:
        return "SNOWFLAKE_CONNECTION"
    return "DBT_BUILD_NONZERO"


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
        except Exception as error:
            if not transient_source_error(error) or attempt == retries - 1:
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


def collect_cdc_evidence(
    sample_limit: int = 25, *, dataset_id: str = "x5j9-wybp"
) -> dict[str, Any]:
    """Capture metadata and an ordered sample, then make a pending review candidate."""
    if not 1 <= sample_limit <= 100:
        raise ValueError("sample_limit must be between 1 and 100")
    settings = PipelineSettings()
    if dataset_id not in {"x5j9-wybp", "qtbi-xd4i"}:
        raise ValueError("Unsupported CDC evidence dataset")
    historical = dataset_id == "qtbi-xd4i"
    if historical and settings.topx_env not in {"dev", "prod"}:
        raise ValueError("Historical CDC onboarding requires isolated DEV or PROD")
    if historical:
        profile = yaml.safe_load(
            SOURCE_CONFIG.with_name("cdc_qtbi_xd4i.yml").read_text(encoding="utf-8")
        )
        if (
            profile.get("resource_key") != "cdc_lyme_qtbi_xd4i"
            or profile.get("endpoint_template") != "https://data.cdc.gov/resource/qtbi-xd4i.json"
            or profile.get("metadata_endpoint_template")
            != "https://data.cdc.gov/api/views/qtbi-xd4i"
            or profile.get("deterministic_order_clause") != ":id ASC"
        ):
            raise ValueError("Invalid historical CDC source profile")
    else:
        profile = load_cdc_profile()
    resource_key = str(profile["resource_key"])
    token = settings.socrata_app_token.get_secret_value() if settings.socrata_app_token else None
    metadata_url = str(profile["metadata_endpoint_template"])
    sample_url = (
        str(profile["endpoint_template"])
        + "?"
        + urlencode({"$limit": sample_limit, "$order": str(profile["deterministic_order_clause"])})
    )
    metadata = _fetch_json(metadata_url, token)
    sample = _fetch_json(sample_url, token)
    if historical:
        validate_historical_evidence(
            metadata, sample, environment=settings.topx_env, sample_limit=sample_limit
        )
    if not isinstance(sample, list) or not sample:
        raise ValueError("CDC sample was empty or malformed")
    columns = metadata.get("columns", []) if isinstance(metadata, dict) else []
    required = {"fips", "year", "case_status", "frequency"}
    observed = {str(key) for row in sample if isinstance(row, dict) for key in row}
    if not historical and not required.issubset(observed):
        raise ValueError("CDC sample does not meet the configured geography/time evidence contract")

    run_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    metadata_payload = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
    sample_payload = json.dumps(sample, sort_keys=True, separators=(",", ":")).encode()
    s3 = _spaces_client(settings)
    metadata_artifact = _save_artifact(s3, settings, resource_key, run_id, metadata_payload)
    sample_artifact = _save_artifact(s3, settings, resource_key, run_id, sample_payload)
    profile_sha256 = hashlib.sha256(
        yaml.safe_dump(profile, sort_keys=True).encode("utf-8")
    ).hexdigest()
    schema_payload = json.dumps(columns, sort_keys=True, separators=(",", ":"))
    schema_sha256 = hashlib.sha256(schema_payload.encode()).hexdigest()
    assessment = Assessment(95, 60, 95, 80, 50) if historical else Assessment(95, 95, 95, 90, 90)
    limitations = (
        "County-of-residence surveillance, 2008-2021 era; do not directly compare with 2022 onward. "
        "Bounded sample only: full coverage, county completeness, publisher keys and dataset-wide "
        "quality remain unverified. Preserve null, zero, unknown, suppressed and not-reported states."
        if historical
        else "County-of-residence surveillance, 2022-current era; preserve null, zero, unknown, suppressed, and not-reported states."
    )
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
                    VALUES (%s, %s, 'EVIDENCE_ONLY', 'MANUAL', 'COMPLETED', %s,
                            %s, %s, %s)""",
                    (
                        run_id,
                        resource_key,
                        f"cdc-{dataset_id}-evidence-v2",
                        profile_sha256,
                        now,
                        now,
                    ),
                )
                catalog_dataset_id = str(uuid.uuid4())
                cursor.execute(
                    """INSERT INTO GOVERNANCE.CATALOG_DATASETS
                    (catalog_dataset_id, dataset_key, catalog_name, catalog_record_id, metadata_payload,
                     metadata_sha256, discovered_at, is_current)
                    SELECT %s, %s, 'CDC_SOCRATA', %s, PARSE_JSON(%s), %s, %s, TRUE""",
                    (
                        catalog_dataset_id,
                        resource_key,
                        dataset_id,
                        json.dumps(metadata),
                        metadata_artifact.sha256,
                        now,
                    ),
                )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.CATALOG_RESOURCES
                    (catalog_resource_id, catalog_dataset_id, resource_key, resource_type, resource_url,
                     canonical_source_url, api_dataset_id, resource_payload, registered_at, is_active)
                    SELECT %s, %s, %s, 'API', %s, %s, %s, PARSE_JSON(%s), %s, TRUE""",
                    (
                        str(uuid.uuid4()),
                        catalog_dataset_id,
                        resource_key,
                        str(profile["endpoint_template"]),
                        str(profile["endpoint_template"]),
                        dataset_id,
                        json.dumps(
                            {"title": metadata.get("name"), "license": metadata.get("license")}
                        ),
                        now,
                    ),
                )
                cursor.execute(
                    "UPDATE GOVERNANCE.SOURCE_ACCESS_PROFILES SET effective_to = %s "
                    "WHERE resource_key = %s AND effective_to IS NULL",
                    (now, resource_key),
                )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.SOURCE_ACCESS_PROFILES
                    (source_access_profile_id, resource_key, profile_version, connector_name,
                     endpoint_template, deterministic_order_clause, incremental_strategy,
                     configuration_sha256, effective_from)
                    VALUES (%s, %s, %s, 'SOCRATA_SODA2', %s, %s, %s, %s, %s)""",
                    (
                        str(uuid.uuid4()),
                        resource_key,
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
                        resource_key,
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
                    (str(uuid.uuid4()), resource_key, schema_sha256, schema_payload, now),
                )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.DATASET_QUALITY_ASSESSMENTS
                    (dataset_quality_assessment_id, resource_key, assessment_status, relevance_score,
                     joinability_score, accessibility_score, documentation_score, quality_score, overall_score,
                     recommendation, limitations, assessed_at)
                    VALUES (%s, %s, 'PENDING_REVIEW', %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        str(uuid.uuid4()),
                        resource_key,
                        95,
                        60 if historical else 95,
                        95,
                        80 if historical else 90,
                        50 if historical else 90,
                        assessment.score,
                        assessment.recommendation,
                        limitations,
                        now,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "ingestion_run_id": run_id,
        "resource_key": resource_key,
        "sample_rows": len(sample),
        "metadata_sha256": metadata_artifact.sha256,
        "sample_sha256": sample_artifact.sha256,
        "schema_sha256": schema_sha256,
        "status": "PENDING_STEWARD_REVIEW",
    }


def ingest_approved_cdc(
    page_size: int = 5_000,
    *,
    trigger_type: str = "MANUAL",
    expected_metadata: str | None = None,
    expected_source_version_id: str | None = None,
    dataset_id: str = "x5j9-wybp",
) -> dict[str, Any]:
    """Fully acquire the approved CDC source through immutable artifacts and COPY.

    This command is intentionally explicit: Streamlit approval enables it, but
    never invokes it.  The caller must run it in the isolated governed runtime.
    """
    if trigger_type not in {"MANUAL", "SCHEDULED", "BACKFILL", "RETRY"}:
        raise ValueError("Unsupported ingestion trigger type")
    settings = PipelineSettings()
    if dataset_id == "qtbi-xd4i":
        if settings.topx_env != "dev":
            raise ValueError("Historical CDC ingestion is DEV-only")
        if expected_source_version_id is None or expected_metadata is None:
            raise ValueError("Historical ingestion requires explicit approval and metadata")
        profile = yaml.safe_load(
            SOURCE_CONFIG.with_name("cdc_qtbi_xd4i.yml").read_text(encoding="utf-8")
        )
        if (
            profile.get("endpoint_template") != "https://data.cdc.gov/resource/qtbi-xd4i.json"
            or profile.get("deterministic_order_clause") != ":id ASC"
        ):
            raise ValueError("Invalid historical access profile")
        resource_key = "cdc_lyme_qtbi_xd4i"
        raw_table = "RAW.CDC_LYME_QTBI_XD4I"
    elif dataset_id == "x5j9-wybp":
        profile = load_cdc_profile()
        resource_key = CDC_RESOURCE_ID
        raw_table = "RAW.CDC_LYME_X5J9_WYBP"
    else:
        raise ValueError("Unsupported CDC dataset")
    if page_size < 1 or page_size > 10_000:
        raise ValueError("page_size must be between 1 and 10,000")
    token = settings.socrata_app_token.get_secret_value() if settings.socrata_app_token else None
    run_id, now = str(uuid.uuid4()), datetime.now(UTC)
    s3 = _spaces_client(settings)
    rows_loaded = 0
    with connect(SnowflakeSettings()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO GOVERNANCE.INGESTION_RUNS
                (ingestion_run_id, resource_key, run_mode, trigger_type, status, code_version, started_at)
                VALUES (%s, %s, 'FULL_REFRESH', %s, 'RUNNING', %s, %s)""",
                (run_id, resource_key, trigger_type, f"cdc-{dataset_id}-full-v3", now),
            )
        connection.commit()
        connection.autocommit(False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT data_source_version_id FROM GOVERNANCE.DATA_SOURCE_VERSIONS
                    WHERE resource_key = %s AND status IN ('APPROVED', 'CONDITIONAL')
                      AND retired_at IS NULL ORDER BY created_at DESC LIMIT 1""",
                    (resource_key,),
                )
                source_version = cursor.fetchone()
                if source_version is None:
                    raise ValueError(
                        "CDC full ingestion requires an active steward-approved source version"
                    )
                source_version_id = str(source_version[0])
                if (
                    expected_source_version_id is not None
                    and source_version_id != expected_source_version_id
                ):
                    raise ValueError("Source approval changed; authorize a new refresh")
                with TemporaryDirectory(prefix="oh-lyme-cdc-") as directory:
                    offset, sequence = 0, 0
                    while True:
                        if dataset_id == "qtbi-xd4i" and offset >= 1_000_000:
                            raise ValueError("Historical acquisition exceeded its reviewed bound")
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
                        if dataset_id == "qtbi-xd4i":
                            from .cdc_historical_ingestion import validate_page

                            validate_page(page, page_size)
                        sequence += 1
                        payload = "\n".join(
                            json.dumps(row, separators=(",", ":")) for row in page
                        ).encode()
                        artifact = _save_artifact(s3, settings, resource_key, run_id, payload)
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
                            f"""COPY INTO {raw_table}
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
                if expected_metadata is not None:
                    after = metadata_fingerprint(
                        _fetch_json(str(profile["metadata_endpoint_template"]), token),
                        dataset_id=dataset_id,
                    )
                    if after != expected_metadata:
                        raise ValueError("Publisher changed during CDC acquisition")
                cursor.execute(
                    """UPDATE GOVERNANCE.INGESTION_RUNS SET status = 'COMPLETED', completed_at = %s
                    WHERE ingestion_run_id = %s""",
                    (datetime.now(UTC), run_id),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE GOVERNANCE.INGESTION_RUNS
                    SET status='FAILED', completed_at=%s,
                        error_classification='CDC_ACQUISITION_FAILED',
                        redacted_error='CDC acquisition failed; prior publication retained'
                    WHERE ingestion_run_id=%s""",
                    (datetime.now(UTC), run_id),
                )
            connection.commit()
            record_incident("ACQUISITION_FAILED", f"acquisition:{run_id}", run_id)
            raise
    return {
        "ingestion_run_id": run_id,
        "resource_key": resource_key,
        "source_version_id": source_version_id,
        "rows_loaded": rows_loaded,
        "status": "COMPLETED",
    }


def build_approved_cdc_models(
    source_version_id: str,
    *,
    lease_owner: str | None = None,
) -> dict[str, str]:
    """Build only the CDC dbt path after a successful governed RAW load."""
    if lease_owner is None:
        with cdc_operation() as owner:
            return build_approved_cdc_models(source_version_id, lease_owner=owner)
    ingestion_run_id, revision = publication_context(source_version_id)
    run_cdc_dbt("stg_cdc_lyme_x5j9_wybp+")
    try:
        quality = record_cdc_quality(
            source_version_id, ingestion_run_id=ingestion_run_id, candidate=True
        )
    except CdcQualityError as error:
        raise CdcDbtBuildError("DATA_QUALITY_FAILED") from error
    publication = publish_snapshot(
        source_version_id,
        ingestion_run_id,
        str(quality["validation_id"]),
        lease_owner,
        expected_revision=revision,
    )
    return {
        "source_version_id": source_version_id,
        "status": "COMPLETED",
        "publication_status": str(publication["status"]),
    }


def run_cdc_dbt(selector: str) -> None:
    """Build an allowlisted CDC path without exposing key material or dbt output."""
    if selector not in {"stg_cdc_lyme_x5j9_wybp+", "stg_cdc_lyme_qtbi_xd4i+"}:
        raise ValueError("Unsupported CDC model selector")
    if "qtbi" in selector and PipelineSettings().topx_env != "dev":
        raise ValueError("Historical CDC dbt is DEV-only")
    environment = os.environ.copy()
    key_b64 = environment.get("SNOWFLAKE_PRIVATE_KEY_B64")
    with TemporaryDirectory(prefix="oh-lyme-dbt-key-") as directory:
        if key_b64:
            try:
                key_bytes = base64.b64decode(key_b64, validate=True)
            except ValueError as error:
                raise RuntimeError("dbt private-key material is not valid base64") from error
            key_path = Path(directory) / "snowflake-dbt-key.p8"
            key_path.write_bytes(key_bytes)
            key_path.chmod(0o600)
            environment["SNOWFLAKE_PRIVATE_KEY_PATH"] = str(key_path)
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
                selector,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
    if result.returncode != 0:
        classification = _dbt_failure_classification(result)
        # This marker is the only dbt-failure detail the controlled recovery
        # workflow may retrieve from the transient provider log.
        logger.error("CDC_DBT_DIAGNOSTIC=%s", classification)
        raise CdcDbtBuildError(classification)


def confirm_approved_cdc_raw_load(source_version_id: str) -> dict[str, int | str]:
    """Confirm that a specific active source version has retained CDC RAW data.

    This is the guard for a dbt-only recovery.  It deliberately performs no
    source request, artifact write, or RAW-table mutation.
    """
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT status FROM GOVERNANCE.DATA_SOURCE_VERSIONS
            WHERE data_source_version_id = %s AND resource_key = %s
              AND retired_at IS NULL""",
            (source_version_id, CDC_RESOURCE_ID),
        )
        source_version = cursor.fetchone()
        if source_version is None or str(source_version[0]) not in {"APPROVED", "CONDITIONAL"}:
            raise ValueError(
                "CDC dbt recovery requires the specified active steward-approved source version"
            )
        cursor.execute(
            """SELECT COUNT(*) FROM RAW.CDC_LYME_X5J9_WYBP
            WHERE data_source_version_id = %s""",
            (source_version_id,),
        )
        raw_count = cursor.fetchone()
        if raw_count is None:
            raise RuntimeError("CDC dbt recovery could not read the RAW row count")
        raw_rows = int(raw_count[0])
        if raw_rows == 0:
            raise ValueError("CDC dbt recovery requires retained RAW rows for the source version")
    return {"source_version_id": source_version_id, "raw_rows": raw_rows}
