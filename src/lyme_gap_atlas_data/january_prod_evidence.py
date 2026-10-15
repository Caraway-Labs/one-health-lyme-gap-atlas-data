"""January binary-package support within the existing source-evidence collector."""
# ruff: noqa: E501

import hashlib
import json
import uuid
from dataclasses import replace
from datetime import datetime
from typing import Any

from .ingestion.adapters import AcquireResult, AcquisitionArtifact
from .ingestion.nclimgrid_daily import NOAA_MEMBER, TIGER_MEMBER, RetainedInputs
from .ingestion.types import SourceDefinition

NOAA_SHA = "809a58714578ce654e61e094e5f7d0ee704d332f1ff6a86c644e56de4ee4da31"
TIGER_SHA = "9c6e9d9076abce2670d1de255de3710c35ecca00a7005d88e012dec52d95f763"
REFERENCE = "census_tiger_2025_us_county_analysis"


def binary_evidence(
    definition: SourceDefinition, acquisition: AcquireResult
) -> tuple[AcquireResult, AcquisitionArtifact]:
    """Preserve both exact binary members; do not serialize NetCDF as JSON."""
    if (
        definition.resource_key != "noaa_nclimgrid_daily_202501"
        or definition.definition_version != 2
        or definition.extra.get("year_month") != "202501"
        or definition.extra.get("noaa_sha256") != NOAA_SHA
        or definition.extra.get("tiger_sha256") != TIGER_SHA
        or len(acquisition.artifacts) != 2
    ):
        raise ValueError("JANUARY_EVIDENCE_SCOPE")
    members = {member.name: member for member in acquisition.artifacts}
    if set(members) != {NOAA_MEMBER, TIGER_MEMBER}:
        raise ValueError("JANUARY_EVIDENCE_MEMBERS")
    noaa, tiger = members[NOAA_MEMBER], members[TIGER_MEMBER]
    if (
        hashlib.sha256(noaa.payload).hexdigest() != NOAA_SHA
        or hashlib.sha256(tiger.payload).hexdigest() != TIGER_SHA
        or acquisition.artifact_sha256 != NOAA_SHA
        or acquisition.payload != noaa.payload
        or noaa.request_purpose != "SOURCE_PAYLOAD"
        or tiger.request_purpose != "ANALYSIS_REFERENCE"
        or noaa.source_uri
        != "https://www.ncei.noaa.gov/data/nclimgrid-daily/access/grids/2025/ncdd-202501-grd-scaled.nc"
        or tiger.source_uri
        != "https://www2.census.gov/geo/tiger/TIGER2025/COUNTY/tl_2025_us_county.zip"
        or noaa.source_uri != definition.endpoint_template
        or tiger.source_uri != definition.extra["tiger_url"]
        or noaa.media_type != "application/x-netcdf"
        or tiger.media_type != "application/zip"
    ):
        raise ValueError("JANUARY_EVIDENCE_PIN")
    return replace(
        acquisition,
        payload=RetainedInputs(
            noaa.payload,
            tiger.payload,
            NOAA_SHA,
            TIGER_SHA,
            "EVIDENCE_NOT_CAPTURED",
            "EVIDENCE_NOT_CAPTURED",
        ),
        raw_payload=noaa.payload,
    ), tiger


def register_reference_candidate(
    cursor: Any,
    definition: SourceDefinition,
    run_id: str,
    artifact_id: str | None,
    checksum: str,
    now: datetime,
) -> None:
    """Register the retained reference for separate existing steward admission.

    Caller owns the same evidence transaction. No approval or version is inserted.
    """
    if checksum != TIGER_SHA or not artifact_id:
        raise ValueError("JANUARY_REFERENCE_PIN")
    metadata = {
        "year_month": "202501",
        "tiger_sha256": TIGER_SHA,
        "noaa_sha256": NOAA_SHA,
        "evidence_run_id": run_id,
        "reference_artifact_id": artifact_id,
        "adapter_kind": "nclimgrid_daily",
        "purpose": "ANALYSIS_REFERENCE",
    }
    encoded = json.dumps(metadata, sort_keys=True)
    dataset_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO GOVERNANCE.CATALOG_DATASETS (catalog_dataset_id,dataset_key,catalog_name,catalog_record_id,metadata_payload,metadata_sha256,discovered_at,is_current) SELECT %s,%s,'CENSUS',%s,PARSE_JSON(%s),%s,%s,TRUE",
        (
            dataset_id,
            "census-tiger-line-2025-us-county",
            "census-tiger-line-2025-us-county",
            encoded,
            hashlib.sha256(encoded.encode()).hexdigest(),
            now,
        ),
    )
    cursor.execute(
        "INSERT INTO GOVERNANCE.CATALOG_RESOURCES (catalog_resource_id,catalog_dataset_id,resource_key,resource_type,resource_url,canonical_source_url,api_dataset_id,resource_payload,registered_at,is_active) SELECT %s,%s,%s,'RETAINED_ANALYTICAL_INPUT',%s,%s,%s,PARSE_JSON(%s),%s,TRUE",
        (
            str(uuid.uuid4()),
            dataset_id,
            REFERENCE,
            definition.extra["tiger_url"],
            definition.extra["tiger_url"],
            "census-tiger-line-2025-us-county",
            encoded,
            now,
        ),
    )
    cursor.execute(
        "INSERT INTO GOVERNANCE.SOURCE_ACCESS_PROFILES (source_access_profile_id,resource_key,profile_version,connector_name,endpoint_template,deterministic_order_clause,incremental_strategy,configuration_sha256,effective_from) VALUES (%s,%s,1,'nclimgrid_daily',%s,'retained analysis reference','IMMUTABLE_MONTHLY_RECAPTURE',%s,%s)",
        (
            str(uuid.uuid4()),
            REFERENCE,
            definition.extra["tiger_url"],
            hashlib.sha256(encoded.encode()).hexdigest(),
            now,
        ),
    )
    cursor.execute(
        "INSERT INTO GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS (source_document_snapshot_id,resource_key,document_type,document_url,artifact_id,content_sha256,retrieved_at,is_material_change) VALUES (%s,%s,'ANALYSIS_REFERENCE',%s,%s,%s,%s,FALSE)",
        (str(uuid.uuid4()), REFERENCE, definition.extra["tiger_url"], artifact_id, checksum, now),
    )
    cursor.execute(
        "INSERT INTO GOVERNANCE.SCHEMA_SNAPSHOTS (schema_snapshot_id,resource_key,schema_fingerprint,schema_payload,retrieved_at) SELECT %s,%s,%s,PARSE_JSON('[]'),%s",
        (str(uuid.uuid4()), REFERENCE, hashlib.sha256(b"[]").hexdigest(), now),
    )
    cursor.execute(
        "INSERT INTO GOVERNANCE.DATASET_QUALITY_ASSESSMENTS (dataset_quality_assessment_id,resource_key,assessment_status,recommendation,limitations,assessed_at) VALUES (%s,%s,'PENDING_REVIEW','REVIEW','Exact retained TIGER analysis input; not a climate observation source',%s)",
        (str(uuid.uuid4()), REFERENCE, now),
    )
