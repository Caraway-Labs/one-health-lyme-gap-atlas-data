# ruff: noqa: E501  # Keep existing ledger SQL names readable.
"""Bounded MRLC extension of the existing immutable semantic release."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from importlib.resources import files
from typing import Any

from .ingestion.adapters import _normalized_record
from .ingestion.identity import canonical_source_row, deterministic_record_id, source_row_hash
from .ingestion.source_definition import source_definition_from_mapping
from .ingestion.types import SourceDefinition

CONTRACT = "atlas-mrlc-nlcd-reviewed-cohort-extension/1"
RESOURCE = "mrlc_annual_nlcd_c1v2_2025_demo_cohort"
SHA = "bdd2a4112769c894e069ae23021bb5a716313c3cfa821a7468aeaeebd2c451ee"
SOURCE_KEY = "context_nlcd_2025"
TRANSFORM = "retained_nlcd_cohort_envelope_v1"
MEASURES = {
    "FOREST_AREA_SHARE": "nlcd_forest_area_share_county_year",
    "DEVELOPED_AREA_SHARE": "nlcd_developed_area_share_county_year",
    "AGRICULTURE_AREA_SHARE": "nlcd_agriculture_area_share_county_year",
    "WETLAND_AREA_SHARE": "nlcd_wetland_area_share_county_year",
    "OPEN_WATER_AREA_SHARE": "nlcd_open_water_area_share_county_year",
    "MEAN_IMPERVIOUS_FRACTION": "nlcd_mean_impervious_fraction_county_year",
    "LAND_COVER_CHANGED_AREA_SHARE": "nlcd_changed_area_share_county_year",
}
LIMITATION = (
    "Selected 2025 TIGER geographies 09110 and 51013 only; unselected counties are not zero. "
    "COMPLETE describes valid source-supported area; preserve source coverage fraction. "
    "09110 is Capitol Planning Region, with no historical Connecticut county crosswalk. "
    "Official MRLC mosaic lineage, not USGS S3 tiles. Descriptive land-cover context only; "
    "no Lyme causal/risk estimate or automatic ML admission."
)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def retained_envelope() -> dict[str, Any]:
    body = (
        files("lyme_gap_atlas_data")
        .joinpath("data", "annual-nlcd-2025-demo-cohort.json")
        .read_bytes()
    )
    _require(hashlib.sha256(body).hexdigest() == SHA, "NLCD_RETAINED_BYTES")
    return dict(json.loads(body))


def retained_definition() -> SourceDefinition:
    return source_definition_from_mapping(
        {
            "resource_key": RESOURCE,
            "source_id": "mrlc_annual_nlcd_derived_county_aggregates",
            "dataset_id": "annual-nlcd-c1v2-2025-reviewed-demo-cohort",
            "definition_version": 1,
            "adapter_kind": "retained_annual_nlcd_aggregate",
            "endpoint_template": "file://retained/annual-nlcd-2025-demo-cohort.json",
            "deterministic_order_clause": "county_fips ASC, measure ASC",
            "incremental_strategy": "IMMUTABLE_REVIEWED_AGGREGATE_CAPTURE",
            "geography_semantics": "SELECTED_TIGER_2025_COUNTIES_AND_COUNTY_EQUIVALENTS",
            "temporal_semantics": "MAPPING_YEAR_2025",
        }
    )


def validate_extension(extension: Any) -> None:
    """Exact cohort identity; IDs come from actual governed execution receipts."""
    _require(
        isinstance(extension, Mapping)
        and set(extension)
        == {
            "contract_version",
            "artifact_sha256",
            "resource_key",
            "source_key",
            "source_version_id",
            "source_decision_id",
            "ingestion_run_id",
            "artifact_id",
            "definition_version",
            "row_count",
            "review_evidence",
        },
        "NLCD_EXTENSION_FIELDS",
    )
    _require(
        extension["contract_version"] == CONTRACT
        and extension["artifact_sha256"] == SHA
        and extension["resource_key"] == RESOURCE
        and extension["source_key"] == SOURCE_KEY
        and type(extension["definition_version"]) is int
        and extension["definition_version"] == 1
        and type(extension["row_count"]) is int
        and extension["row_count"] == 14,
        "NLCD_EXTENSION_SCOPE",
    )
    for name in ("source_version_id", "source_decision_id", "ingestion_run_id"):
        _require(
            isinstance(extension[name], str) and str(uuid.UUID(extension[name])) == extension[name],
            "NLCD_RECEIPT_UUID",
        )
    _require(
        isinstance(extension["artifact_id"], str) and bool(extension["artifact_id"]),
        "NLCD_ARTIFACT_ID",
    )
    review = extension["review_evidence"]
    _require(
        isinstance(review, Mapping)
        and set(review) == {"commit", "url", "reviewer"}
        and isinstance(review["commit"], str)
        and len(review["commit"]) == 40
        and all(c in "0123456789abcdef" for c in review["commit"])
        and isinstance(review["url"], str)
        and re.fullmatch(
            r"https://github\.com/Caraway-Labs/one-health-lyme-gap-atlas-data/pull/"
            r"[1-9][0-9]*#pullrequestreview-[1-9][0-9]*",
            review["url"],
        )
        is not None
        and isinstance(review["reviewer"], str)
        and bool(review["reviewer"].strip()),
        "NLCD_REVIEW_EVIDENCE",
    )


def _payload_matches(actual: Any, expected: Any) -> bool:
    """Snowflake can recover native JSON numbers as DECIMAL; preserve precision."""
    if isinstance(expected, float):
        return (
            isinstance(actual, (float, int))
            and not isinstance(actual, bool)
            and abs(actual - expected) <= max(1e-15, abs(expected) * 1e-15)
        )
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and set(actual) == set(expected)
            and all(_payload_matches(actual[key], value) for key, value in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_payload_matches(a, b) for a, b in zip(actual, expected, strict=True))
        )
    return type(actual) is type(expected) and bool(actual == expected)


def verify_extension(cursor: Any, extension: Any) -> list[dict[str, Any]]:
    """Prove approved source, completed run, quality and all immutable captures."""
    validate_extension(extension)
    cursor.execute(
        "SELECT status,approved_decision_id,retired_at FROM GOVERNANCE.DATA_SOURCE_VERSIONS WHERE data_source_version_id=%s AND resource_key=%s",
        (extension["source_version_id"], RESOURCE),
    )
    _require(
        cursor.fetchall()
        in [
            [("APPROVED", extension["source_decision_id"], None)],
            [("CONDITIONAL", extension["source_decision_id"], None)],
        ],
        "NLCD_SOURCE_APPROVAL",
    )
    cursor.execute(
        "SELECT resource_key,status FROM GOVERNANCE.INGESTION_RUNS WHERE ingestion_run_id=%s",
        (extension["ingestion_run_id"],),
    )
    _require(cursor.fetchall() == [(RESOURCE, "COMPLETED")], "NLCD_RUN_COMPLETED")
    cursor.execute(
        "SELECT sha256,byte_count FROM GOVERNANCE.RAW_ARTIFACTS WHERE artifact_id=%s AND ingestion_run_id=%s",
        (extension["artifact_id"], extension["ingestion_run_id"]),
    )
    _require(cursor.fetchall() == [(SHA, 29058)], "NLCD_ARTIFACT_RECEIPT")
    cursor.execute(
        "SELECT COUNT(*),COUNT_IF(severity='BLOCKING' AND status='FAILED') FROM GOVERNANCE.DATA_QUALITY_RESULTS WHERE ingestion_run_id=%s",
        (extension["ingestion_run_id"],),
    )
    quality = cursor.fetchone()
    _require(quality is not None and quality[0] >= 2 and quality[1] == 0, "NLCD_QUALITY")
    cursor.execute(
        "SELECT capture_record_id,record_revision,record_id,source_row_hash,normalized_sha256,transformation_version,payload,retrieved_at FROM GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS WHERE resource_key=%s AND source_definition_version=1 AND ingestion_run_id=%s AND artifact_id=%s AND artifact_sha256=%s ORDER BY record_id",
        (RESOURCE, extension["ingestion_run_id"], extension["artifact_id"], SHA),
    )
    captures = cursor.fetchall()
    definition = retained_definition()
    expected = {
        deterministic_record_id(RESOURCE, 1, row): row for row in retained_envelope()["records"]
    }
    _require(
        len(captures) == 14 and {row[2] for row in captures} == set(expected), "NLCD_CAPTURE_SET"
    )
    result = []
    for (
        capture_id,
        revision,
        record_id,
        source_hash,
        normalized_hash,
        transform,
        payload,
        retrieved_at,
    ) in captures:
        original = expected[record_id]
        normalized = _normalized_record(definition, original)
        digest = hashlib.sha256(canonical_source_row(normalized).encode()).hexdigest()
        _require(
            source_hash == source_row_hash(original)
            and normalized_hash == digest
            and transform == TRANSFORM,
            "NLCD_CAPTURE_HASHES",
        )
        _require(
            capture_id
            == hashlib.sha256(
                f"capture:{extension['ingestion_run_id']}:{record_id}".encode()
            ).hexdigest()
            and revision
            == hashlib.sha256(
                f"record-revision:{record_id}:{SHA}:{source_hash}:{digest}:{TRANSFORM}".encode()
            ).hexdigest(),
            "NLCD_CAPTURE_REVISION",
        )
        payload = json.loads(payload) if isinstance(payload, str) else payload
        _require(_payload_matches(payload, normalized), "NLCD_CAPTURE_PAYLOAD")
        result.append(
            {
                "record": original,
                "record_id": record_id,
                "capture_record_id": capture_id,
                "record_revision": revision,
                "source_row_hash": source_hash,
                "normalized_sha256": digest,
                "retrieved_at": retrieved_at,
            }
        )
    return result


def observation_rows(
    release_id: str, extension: Any, captures: list[dict[str, Any]]
) -> list[tuple[Any, ...]]:
    """Map the unchanged fourteen values into existing semantic observation storage."""
    validate_extension(extension)
    _require(len(captures) == 14, "NLCD_OBSERVATION_COUNT")
    return [
        (
            hashlib.sha256(f"semantic-nlcd:{release_id}:{item['record_id']}".encode()).hexdigest(),
            release_id,
            MEASURES[item["record"]["measure"]],
            item["record"]["county_fips"],
            SOURCE_KEY,
            extension["source_version_id"],
            extension["ingestion_run_id"],
            extension["artifact_id"],
            item["record_id"],
            item["source_row_hash"],
            json.dumps(item["record"]["value"], allow_nan=False),
            "ZERO" if item["record"]["value"] == 0 else "OBSERVED",
            item["retrieved_at"],
            "SELECTED_TIGER_2025_COUNTIES_AND_COUNTY_EQUIVALENTS",
            "2025",
            item["record"]["transformation_version"],
            "COMPLETE",
            LIMITATION,
        )
        for item in captures
    ]


def verify_persisted_extension(cursor: Any, release_id: str, *, manifest: Any = None) -> int:
    if manifest is None:
        cursor.execute(
            "SELECT source_manifest FROM PRESENTATION.SEMANTIC_RELEASES WHERE release_id=%s",
            (release_id,),
        )
        row = cursor.fetchone()
        _require(row is not None, "NLCD_RELEASE_MANIFEST")
        manifest = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    _require(isinstance(manifest, Mapping), "NLCD_RELEASE_MANIFEST")
    if "nlcd_extension" not in manifest:
        return 0
    extension = manifest["nlcd_extension"]
    captures = verify_extension(cursor, extension)
    cursor.execute(
        "SELECT resource_key,source_id,dataset_id,vintage,source_version_id,ingestion_run_id,artifact_id FROM PRESENTATION.SEMANTIC_DATA_SOURCES WHERE release_id=%s AND source_key=%s",
        (release_id, SOURCE_KEY),
    )
    _require(
        cursor.fetchall()
        == [
            (
                RESOURCE,
                "mrlc_annual_nlcd_derived_county_aggregates",
                "annual-nlcd-c1v2-2025-reviewed-demo-cohort",
                "C1V2-2025",
                extension["source_version_id"],
                extension["ingestion_run_id"],
                extension["artifact_id"],
            )
        ],
        "NLCD_SEMANTIC_SOURCE",
    )
    expected = observation_rows(release_id, extension, captures)
    cursor.execute(
        "SELECT observation_id,release_id,measure_id,fips,source_key,source_version_id,ingestion_run_id,artifact_id,source_record_id,source_row_hash,value,value_state,retrieved_at,geography_semantics,temporal_window,transformation_version,quality_state,limitations FROM PRESENTATION.SEMANTIC_OBSERVATIONS WHERE release_id=%s AND source_key=%s ORDER BY observation_id",
        (release_id, SOURCE_KEY),
    )
    actual = cursor.fetchall()
    _require(len(actual) == 14, "NLCD_SEMANTIC_COUNT")
    by_id = {row[0]: row for row in expected}
    _require(set(by_id) == {row[0] for row in actual}, "NLCD_SEMANTIC_IDENTITIES")
    for row in actual:
        planned = by_id[row[0]]
        _require(
            tuple(row[:10]) == planned[:10] and tuple(row[11:]) == planned[11:],
            "NLCD_SEMANTIC_LINEAGE",
        )
        value = json.loads(row[10]) if isinstance(row[10], str) else row[10]
        _require(_payload_matches(value, json.loads(planned[10])), "NLCD_SEMANTIC_VALUE")
    return 14


def insert_hierarchy(cursor: Any, release_id: str) -> None:
    cursor.execute(
        "INSERT INTO PRESENTATION.SEMANTIC_INDICATORS (release_id,indicator_id,label,description,limitation) VALUES (%s,'land_cover_context','Annual NLCD land-cover context','Seven frozen 2025 county-year context measures',%s)",
        (release_id, LIMITATION),
    )
    cursor.executemany(
        "INSERT INTO PRESENTATION.SEMANTIC_MEASURES (release_id,indicator_id,measure_id,label,data_type,unit,geography_semantics,temporal_resolution,missingness_semantics,methodology,limitation) VALUES (%s,'land_cover_context',%s,%s,'number','fraction','SELECTED_TIGER_2025_COUNTIES_AND_COUNTY_EQUIVALENTS','2025',%s,'atlas-annual-nlcd-mrlc-local-county/1',%s)",
        [
            (
                release_id,
                semantic,
                native.replace("_", " ").title(),
                "True zero stays zero; unselected counties have no observation",
                LIMITATION,
            )
            for native, semantic in MEASURES.items()
        ],
    )
