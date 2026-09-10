"""Evidence-only CDC Ixodes county-status onboarding for isolated DEV."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml  # type: ignore[import-untyped]
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect
from openpyxl import load_workbook  # type: ignore[import-untyped]

from .artifacts import Artifact, create_artifact
from .assessment import Assessment
from .cdc import _spaces_client
from .redaction import redact_mapping
from .settings import PipelineSettings

RESOURCE_KEY = "cdc_tick_ixodes_county_status"
SOURCE_DATASET_ID = "cdc-ixodes-county-status-2025"
PROFILE_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "sources" / "cdc_tick_ixodes_county_status.yml"
)
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXPECTED_HEADERS = (
    "FIPSCode",
    "State",
    "County",
    "Ixodes_scapularis_County_Status",
    "Ixodes_scapularis_data_source",
    "Ixodes_pacificus_county_status",
    "Ixodes_pacificus_data_source",
)


@dataclass(frozen=True)
class FetchResult:
    payload: bytes
    media_type: str
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True)
class WorkbookEvidence:
    sample: list[dict[str, object]]
    row_count: int
    schema: dict[str, object]


def load_tick_profile(path: Path = PROFILE_PATH) -> dict[str, Any]:
    """Load the pinned first-party CDC workbook evidence profile."""
    profile = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(profile, dict):
        raise ValueError("Invalid tick-surveillance source profile")
    expected = {
        "resource_key": RESOURCE_KEY,
        "source_dataset_id": SOURCE_DATASET_ID,
        "connector_name": "HTTP_XLSX_V1",
        "landing_page_url": "https://www.cdc.gov/ticks/data-research/facts-stats/tick-surveillance-data-sets.html",
        "endpoint_template": "https://www.cdc.gov/ticks/media/files/2026/04/Public_Use_Ixodes_County_Table_2026_03252026.xlsx",
        "workbook_sheet": "Ixodes records 2025",
        "header_row": 2,
        "deterministic_order_clause": "FIPSCode ASC",
        "incremental_strategy": "SNAPSHOT_DIFF",
    }
    if any(profile.get(key) != value for key, value in expected.items()):
        raise ValueError("Tick-surveillance source profile does not match the reviewed CDC source")
    if profile.get("onboarding_environments") != ["dev"]:
        raise ValueError("Tick-surveillance evidence onboarding must remain DEV-only")
    return profile


def _fetch_bytes(
    url: str,
    *,
    accept: str,
    maximum_bytes: int,
    referer: str | None = None,
    retries: int = 3,
) -> FetchResult:
    """Fetch one exact public CDC resource with a strict response bound."""
    if urlparse(url).scheme != "https" or urlparse(url).hostname != "www.cdc.gov":
        raise ValueError("Tick-surveillance evidence allows only first-party CDC HTTPS resources")
    headers = {"Accept": accept, "User-Agent": "AtlasGovernedEvidence/1.0"}
    if referer:
        headers["Referer"] = referer
    for attempt in range(retries):
        try:
            with (
                httpx.Client(follow_redirects=True, timeout=30) as client,
                client.stream("GET", url, headers=headers) as response,
            ):
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                final = urlparse(str(response.url))
                if final.scheme != "https" or final.hostname != "www.cdc.gov":
                    raise ValueError(
                        "CDC evidence request redirected outside the approved publisher"
                    )
                declared = response.headers.get("content-length")
                if declared and int(declared) > maximum_bytes:
                    raise ValueError("CDC evidence response exceeds the configured byte bound")
                payload = bytearray()
                for chunk in response.iter_bytes():
                    payload.extend(chunk)
                    if len(payload) > maximum_bytes:
                        raise ValueError("CDC evidence response exceeds the configured byte bound")
                media_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
                return FetchResult(
                    bytes(payload),
                    media_type,
                    response.headers.get("etag"),
                    response.headers.get("last-modified"),
                )
        except httpx.HTTPStatusError as error:
            if (
                error.response.status_code not in {429, 500, 502, 503, 504}
                or attempt == retries - 1
            ):
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def _validate_landing_page(result: FetchResult) -> None:
    if result.media_type != "text/html":
        raise ValueError("CDC tick-surveillance landing page did not return HTML")
    text = result.payload.decode("utf-8", errors="replace").lower()
    required = (
        "tick surveillance data sets",
        "public_use_ixodes_county_table_2026_03252026.xlsx",
        "no records",
        "established",
    )
    if any(value not in text for value in required):
        raise ValueError("CDC tick-surveillance landing-page semantics changed")


def _parse_workbook(payload: bytes, profile: dict[str, Any], sample_limit: int) -> WorkbookEvidence:
    if not zipfile.is_zipfile(BytesIO(payload)):
        raise ValueError("CDC tick-surveillance evidence is not a valid XLSX package")
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        if sum(member.file_size for member in archive.infolist()) > int(
            profile["maximum_uncompressed_bytes"]
        ):
            raise ValueError("CDC workbook exceeds the configured uncompressed byte bound")
        if any(
            member.filename.startswith(("/", "\\")) or ".." in Path(member.filename).parts
            for member in archive.infolist()
        ):
            raise ValueError("CDC workbook contains an invalid package member")
    workbook = load_workbook(BytesIO(payload), read_only=True, data_only=True)
    if len(workbook.sheetnames) > 10 or str(profile["workbook_sheet"]) not in workbook.sheetnames:
        raise ValueError("CDC workbook sheet structure changed")
    sheet = workbook[str(profile["workbook_sheet"])]
    if sheet.max_row is None or sheet.max_column is None or not 3 <= sheet.max_row <= 10_000:
        raise ValueError("CDC workbook row shape is outside the reviewed evidence bound")
    if sheet.max_column != len(EXPECTED_HEADERS):
        raise ValueError("CDC workbook column count changed")
    header_row = int(profile["header_row"])
    headers = tuple(
        str(value) if value is not None else ""
        for value in next(sheet.iter_rows(min_row=header_row, max_row=header_row, values_only=True))
    )
    if headers != EXPECTED_HEADERS:
        raise ValueError("CDC workbook schema changed; steward review is required")
    sample: list[dict[str, object]] = []
    prior_fips = ""
    allowed = set(str(value) for value in profile["allowed_status_values"])
    for values in sheet.iter_rows(min_row=header_row + 1, values_only=True):
        if not any(value is not None for value in values):
            continue
        row = dict(zip(headers, values, strict=True))
        fips = row["FIPSCode"]
        if not isinstance(fips, str) or re.fullmatch(r"[0-9]{5}", fips) is None:
            raise ValueError("CDC workbook sample does not preserve five-character county FIPS")
        if prior_fips and fips <= prior_fips:
            raise ValueError("CDC workbook sample is not deterministically ordered by county FIPS")
        prior_fips = fips
        for field in ("Ixodes_scapularis_County_Status", "Ixodes_pacificus_county_status"):
            if row[field] not in allowed:
                raise ValueError("CDC workbook contains an unreviewed county-status value")
        sample.append(row)
        if len(sample) == sample_limit:
            break
    if len(sample) != sample_limit:
        raise ValueError("CDC workbook does not contain the requested bounded sample")
    schema = {
        "contract_version": "tick-surveillance-v1",
        "workbook_sheet": sheet.title,
        "header_row": header_row,
        "headers": list(headers),
        "worksheet_rows_including_headers": sheet.max_row,
        "worksheet_columns": sheet.max_column,
        "dataset_as_of": str(profile["dataset_as_of"]),
        "temporal_semantics": str(profile["temporal_semantics"]),
        "allowed_status_values": list(profile["allowed_status_values"]),
        "full_dataset_quality_validated": False,
    }
    return WorkbookEvidence(sample, sheet.max_row - header_row, schema)


def _save_artifact(
    s3: Any,
    settings: PipelineSettings,
    run_id: str,
    payload: bytes,
    media_type: str,
) -> Artifact:
    artifact = create_artifact(
        payload=payload,
        environment=settings.topx_env,
        resource_key=RESOURCE_KEY,
        run_id=run_id,
    )
    s3.put_object(
        Bucket=settings.spaces_bucket,
        Key=f"{settings.spaces_prefix}/{artifact.object_key}",
        Body=payload,
        ContentType=media_type,
    )
    return artifact


def collect_tick_surveillance_evidence(sample_limit: int = 25) -> dict[str, object]:
    """Create a pending DEV candidate without RAW loading, approval, or transformation."""
    if not 1 <= sample_limit <= 100:
        raise ValueError("sample_limit must be between 1 and 100")
    settings = PipelineSettings()
    if settings.topx_env != "dev":
        raise ValueError("Tick-surveillance evidence capture is approved only for isolated DEV")
    profile = load_tick_profile()
    landing_url = str(profile["landing_page_url"])
    workbook_url = str(profile["endpoint_template"])
    landing = _fetch_bytes(landing_url, accept="text/html", maximum_bytes=2_000_000)
    _validate_landing_page(landing)
    workbook = _fetch_bytes(
        workbook_url,
        accept=XLSX_MEDIA_TYPE,
        maximum_bytes=int(profile["maximum_workbook_bytes"]),
        referer=landing_url,
    )
    if workbook.media_type != XLSX_MEDIA_TYPE:
        raise ValueError("CDC tick-surveillance workbook media type changed")
    evidence = _parse_workbook(workbook.payload, profile, sample_limit)

    run_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    profile_sha256 = hashlib.sha256(
        yaml.safe_dump(profile, sort_keys=True).encode("utf-8")
    ).hexdigest()
    schema_payload = json.dumps(evidence.schema, sort_keys=True, separators=(",", ":"))
    schema_sha256 = hashlib.sha256(schema_payload.encode()).hexdigest()
    sample_payload = json.dumps(evidence.sample, sort_keys=True, separators=(",", ":")).encode()
    metadata = {
        "title": "Blacklegged and western blacklegged tick county status",
        "publisher": "CDC National Center for Emerging and Zoonotic Infectious Diseases",
        "source_dataset_id": SOURCE_DATASET_ID,
        "landing_page_url": landing_url,
        "workbook_url": workbook_url,
        "dataset_as_of": str(profile["dataset_as_of"]),
        "workbook_etag": workbook.etag,
        "workbook_last_modified": workbook.last_modified,
        "workbook_rows": evidence.row_count,
        "sample_rows": len(evidence.sample),
        "county_status_semantics": {
            "Established": "Publisher cumulative established classification",
            "Reported": "Publisher cumulative reported classification",
            "No records": "No reported surveillance evidence; not evidence of absence",
        },
        "license_or_terms_status": "REVIEW_REQUIRED_EMBEDDED_DATA_USE_AGREEMENT",
        "full_dataset_quality_validated": False,
    }
    metadata_payload = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
    s3 = _spaces_client(settings)
    landing_artifact = _save_artifact(s3, settings, run_id, landing.payload, "text/html")
    workbook_artifact = _save_artifact(s3, settings, run_id, workbook.payload, XLSX_MEDIA_TYPE)
    metadata_artifact = _save_artifact(s3, settings, run_id, metadata_payload, "application/json")
    sample_artifact = _save_artifact(s3, settings, run_id, sample_payload, "application/json")
    assessment = Assessment(95, 95, 65, 90, 65)
    limitations = (
        "Cumulative county status through 2025-12-31; No records is not tick absence. "
        "The workbook does not provide collection effort, abundance, life stage, or pathogen "
        "testing. "
        "Evidence capture retained the byte-bounded publisher workbook because no row API exists, "
        "but inspected only a bounded sample and did not load RAW or validate full-dataset "
        "quality. "
        "The embedded data-use agreement and source citations require steward review."
    )
    artifact_ids = {
        name: str(uuid.uuid4()) for name in ("landing", "workbook", "metadata", "sample")
    }

    with connect(SnowflakeSettings()) as connection:
        connection.autocommit(False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO GOVERNANCE.INGESTION_RUNS
                    (ingestion_run_id, resource_key, run_mode, trigger_type, status, code_version,
                     config_sha256, started_at, completed_at)
                    VALUES (%s, %s, 'EVIDENCE_ONLY', 'MANUAL', 'COMPLETED',
                            'cdc-tick-ixodes-evidence-v1', %s, %s, %s)""",
                    (run_id, RESOURCE_KEY, profile_sha256, now, now),
                )
                catalog_dataset_id = str(uuid.uuid4())
                cursor.execute(
                    """INSERT INTO GOVERNANCE.CATALOG_DATASETS
                    (catalog_dataset_id, dataset_key, catalog_name, catalog_record_id,
                     metadata_payload, metadata_sha256, discovered_at, is_current)
                    SELECT %s, %s, 'CDC_WEB', %s, PARSE_JSON(%s), %s, %s, TRUE""",
                    (
                        catalog_dataset_id,
                        RESOURCE_KEY,
                        SOURCE_DATASET_ID,
                        json.dumps(metadata),
                        metadata_artifact.sha256,
                        now,
                    ),
                )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.CATALOG_RESOURCES
                    (catalog_resource_id, catalog_dataset_id, resource_key, resource_type,
                     resource_url, canonical_source_url, api_dataset_id, resource_payload,
                     registered_at, is_active)
                    SELECT %s, %s, %s, 'DATA', %s, %s, %s, PARSE_JSON(%s), %s, TRUE""",
                    (
                        str(uuid.uuid4()),
                        catalog_dataset_id,
                        RESOURCE_KEY,
                        workbook_url,
                        landing_url,
                        SOURCE_DATASET_ID,
                        json.dumps(
                            {
                                "title": metadata["title"],
                                "publisher": metadata["publisher"],
                                "media_type": XLSX_MEDIA_TYPE,
                                "terms_status": metadata["license_or_terms_status"],
                            }
                        ),
                        now,
                    ),
                )
                cursor.execute(
                    "UPDATE GOVERNANCE.SOURCE_ACCESS_PROFILES SET effective_to=%s "
                    "WHERE resource_key=%s AND effective_to IS NULL",
                    (now, RESOURCE_KEY),
                )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.SOURCE_ACCESS_PROFILES
                    (source_access_profile_id, resource_key, profile_version, connector_name,
                     endpoint_template, deterministic_order_clause, incremental_strategy,
                     configuration_sha256, effective_from)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        str(uuid.uuid4()),
                        RESOURCE_KEY,
                        int(profile["profile_version"]),
                        str(profile["connector_name"]),
                        workbook_url,
                        str(profile["deterministic_order_clause"]),
                        str(profile["incremental_strategy"]),
                        profile_sha256,
                        now,
                    ),
                )
                requests = (
                    (1, "SOURCE_LANDING_PAGE", landing_url, landing_artifact, 1),
                    (
                        2,
                        "SOURCE_WORKBOOK_EVIDENCE",
                        workbook_url,
                        workbook_artifact,
                        evidence.row_count,
                    ),
                )
                request_ids: dict[str, str] = {}
                for sequence, purpose, endpoint, artifact, row_count in requests:
                    request_id = str(uuid.uuid4())
                    request_ids[purpose] = request_id
                    cursor.execute(
                        """INSERT INTO GOVERNANCE.INGESTION_REQUESTS
                        (ingestion_request_id, ingestion_run_id, request_sequence, request_purpose,
                         endpoint, redacted_request, status_code, response_sha256,
                         retrieved_row_count, created_at)
                        SELECT %s, %s, %s, %s, %s, PARSE_JSON(%s), 200, %s, %s, %s""",
                        (
                            request_id,
                            run_id,
                            sequence,
                            purpose,
                            endpoint,
                            json.dumps(
                                redact_mapping({"endpoint": endpoint, "sample_limit": sample_limit})
                            ),
                            artifact.sha256,
                            row_count,
                            now,
                        ),
                    )
                raw_artifacts = (
                    (
                        "landing",
                        "SOURCE_LANDING_PAGE",
                        landing_artifact,
                        "text/html",
                        request_ids["SOURCE_LANDING_PAGE"],
                    ),
                    (
                        "workbook",
                        "SOURCE_WORKBOOK_EVIDENCE",
                        workbook_artifact,
                        XLSX_MEDIA_TYPE,
                        request_ids["SOURCE_WORKBOOK_EVIDENCE"],
                    ),
                    (
                        "metadata",
                        "NORMALIZED_SOURCE_METADATA",
                        metadata_artifact,
                        "application/json",
                        request_ids["SOURCE_LANDING_PAGE"],
                    ),
                    (
                        "sample",
                        "ORDERED_SOURCE_SAMPLE",
                        sample_artifact,
                        "application/json",
                        request_ids["SOURCE_WORKBOOK_EVIDENCE"],
                    ),
                )
                for name, artifact_type, artifact, media_type, request_id in raw_artifacts:
                    cursor.execute(
                        """INSERT INTO GOVERNANCE.RAW_ARTIFACTS
                        (artifact_id, ingestion_run_id, ingestion_request_id, artifact_uri,
                         artifact_type, media_type, byte_count, sha256, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            artifact_ids[name],
                            run_id,
                            request_id,
                            f"s3://{settings.spaces_bucket}/{settings.spaces_prefix}/{artifact.object_key}",
                            artifact_type,
                            media_type,
                            artifact.byte_count,
                            artifact.sha256,
                            now,
                        ),
                    )
                for document_type, document_url, artifact_name, artifact in (
                    ("LANDING_PAGE_AND_METHODOLOGY", landing_url, "landing", landing_artifact),
                    (
                        "DATA_USE_AGREEMENT_AND_SOURCE_WORKBOOK",
                        workbook_url,
                        "workbook",
                        workbook_artifact,
                    ),
                ):
                    cursor.execute(
                        """INSERT INTO GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS
                        (source_document_snapshot_id, resource_key, document_type, document_url,
                         artifact_id, content_sha256, retrieved_at, is_material_change)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)""",
                        (
                            str(uuid.uuid4()),
                            RESOURCE_KEY,
                            document_type,
                            document_url,
                            artifact_ids[artifact_name],
                            artifact.sha256,
                            now,
                        ),
                    )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.SCHEMA_SNAPSHOTS
                    (schema_snapshot_id, resource_key, schema_fingerprint, schema_payload,
                     retrieved_at)
                    SELECT %s, %s, %s, PARSE_JSON(%s), %s""",
                    (str(uuid.uuid4()), RESOURCE_KEY, schema_sha256, schema_payload, now),
                )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.DATASET_QUALITY_ASSESSMENTS
                    (dataset_quality_assessment_id, resource_key, assessment_status,
                     relevance_score, joinability_score, accessibility_score, documentation_score,
                     quality_score, overall_score, recommendation, limitations, assessed_at)
                    VALUES (%s, %s, 'PENDING_REVIEW', 95, 95, 65, 90, 65, %s, %s, %s, %s)""",
                    (
                        str(uuid.uuid4()),
                        RESOURCE_KEY,
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
        "resource_key": RESOURCE_KEY,
        "source_dataset_id": SOURCE_DATASET_ID,
        "sample_rows": len(evidence.sample),
        "workbook_rows": evidence.row_count,
        "landing_sha256": landing_artifact.sha256,
        "workbook_sha256": workbook_artifact.sha256,
        "sample_sha256": sample_artifact.sha256,
        "schema_sha256": schema_sha256,
        "full_dataset_quality_validated": False,
        "status": "PENDING_STEWARD_REVIEW",
    }
