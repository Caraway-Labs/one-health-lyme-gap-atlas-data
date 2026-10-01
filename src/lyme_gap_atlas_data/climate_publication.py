"""Read-only, run-pinned January climate candidate projection (DATA #443).

This prepares a review artifact. It does not publish a release, create a view,
grant access, promote DEV captures, or change ingestion state.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from .ingestion.identity import canonical_source_row, deterministic_record_id, source_row_hash
from .ingestion.nclimgrid_coverage import canonical_counties

RUN_ID = "c2eb2146-005d-44d2-bac4-e2805ca42577"
RESOURCE_KEY = "noaa_nclimgrid_daily_202501"
NOAA_SHA = "809a58714578ce654e61e094e5f7d0ee704d332f1ff6a86c644e56de4ee4da31"
TIGER_SHA = "9c6e9d9076abce2670d1de255de3710c35ecca00a7005d88e012dec52d95f763"
CONTRACT = "atlas-nclimgrid-county-day-candidate-v1"
COUNTIES = canonical_counties()
NOAA_ARTIFACT_ID = f"{RESOURCE_KEY}:{RUN_ID}:658d13370fbec2095b1d601473cc5ce3"
MEASURES = {
    "PRCP": "mm",
    "TMIN": "degree_Celsius",
    "TMAX": "degree_Celsius",
    "TAVG": "degree_Celsius",
}
AREAS = ("expected_area_m2", "intersected_area_m2", "source_supported_area_m2", "valid_area_m2")
FRACTIONS = ("source_coverage_fraction", "valid_fraction_of_supported_area")
LIMITATIONS = (
    "January 2025 descriptive context only; no Lyme causal, risk or ML claim.",
    "2025 TIGER geometry over canonical Atlas counties; NOAA supports CONUS only.",
    "Monthly source support is inferred from retained finite grid values, not a NOAA land polygon.",
    "Observation day is not publication time; historical first availability is unavailable.",
    "95% completeness applies to valid/source-supported area, not full county area.",
)

# Execute only with an existing authorized reader; all statements are SELECT.
# Do not replace this exact capture with the latest capture or current mutable RAW projection.
CAPTURE_QUERY = """SELECT capture_record_id, record_revision, record_id, source_id,
dataset_id, resource_key, source_definition_version, ingestion_run_id,
artifact_id, artifact_sha256, source_row_hash, normalized_sha256,
transformation_version, payload, retrieved_at
FROM GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS
WHERE ingestion_run_id = %s
ORDER BY payload:record:county_fips::VARCHAR,
payload:record:observation_date::VARCHAR, payload:record:measure::VARCHAR"""


class ClimatePublicationBlocked(ValueError):
    """Finite diagnostic only: never interpolate warehouse/provider payloads."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ClimatePublicationBlocked(code)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _timestamp(value: Any) -> str:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, "RETRIEVAL_TIME")
        return parsed.astimezone(UTC).isoformat()
    except (TypeError, ValueError):
        raise ClimatePublicationBlocked("RETRIEVAL_TIME") from None


def project_capture_record(capture: Mapping[str, Any]) -> dict[str, Any]:
    """Validate immutable lineage and project an explicit safe field allowlist.

    A caller must separately prove live session identity, selected run success,
    artifact ledger membership, completed partitions and quality checkpoints.
    This function never claims a capture export is a live published release.
    """
    try:
        payload = capture["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        _require(isinstance(payload, dict) and isinstance(payload.get("record"), dict), "PAYLOAD")
        record = payload["record"]
        for name, expected in (
            ("ingestion_run_id", RUN_ID),
            ("resource_key", RESOURCE_KEY),
            ("source_id", "noaa_nclimgrid_daily"),
            ("dataset_id", "nclimgrid-daily-v1.0.0-scaled"),
            ("source_definition_version", 2),
            ("artifact_sha256", NOAA_SHA),
            ("artifact_id", NOAA_ARTIFACT_ID),
        ):
            _require(capture.get(name) == expected, "CAPTURE_SCOPE")
        for name in ("source_id", "dataset_id", "source_definition_version"):
            _require(payload.get(name) == capture[name], "PAYLOAD_SCOPE")
        _require(payload.get("geography_semantics") == "CONUS_COUNTY_FIPS_2025_ANALYSIS", "GRAIN")
        _require(payload.get("temporal_semantics") == "COUNTY_DAY", "GRAIN")
        source_hash = source_row_hash(record)
        normalized_hash = _digest(canonical_source_row(payload))
        record_id = deterministic_record_id(RESOURCE_KEY, 2, record)
        _require(capture.get("record_id") == record_id, "RECORD_ID")
        _require(capture.get("source_row_hash") == source_hash, "SOURCE_HASH")
        _require(capture.get("normalized_sha256") == normalized_hash, "NORMALIZED_HASH")
        _require(
            capture.get("capture_record_id") == _digest(f"capture:{RUN_ID}:{record_id}"),
            "CAPTURE_ID",
        )
        transform = capture.get("transformation_version")
        _require(isinstance(transform, str) and bool(transform), "CAPTURE_TRANSFORM")
        revision = _digest(
            f"record-revision:{record_id}:{NOAA_SHA}:{source_hash}:{normalized_hash}:{transform}"
        )
        _require(capture.get("record_revision") == revision, "REVISION")
        _require(
            record.get("noaa_sha256") == NOAA_SHA and record.get("tiger_sha256") == TIGER_SHA,
            "MEMBERS",
        )
        _require(record.get("source_year_month") == "202501", "MONTH")
        _require(
            record.get("transformation_version") == "atlas-nclimgrid-county-day/2", "TRANSFORM"
        )
        version = record.get("noaa_product_version")
        _require(isinstance(version, str) and version.startswith("v1-0-0"), "PRODUCT")
        _require(record.get("noaa_member_name") == "noaa-scaled-monthly-netcdf", "MEMBERS")
        _require(record.get("tiger_member_name") == "tiger-2025-analysis-county-zip", "MEMBERS")
        _require(record.get("grid_crs") == "EPSG:4326", "GRID")
        fips, day, measure = record["county_fips"], record["observation_date"], record["measure"]
        _require(isinstance(fips, str) and fips in COUNTIES, "COUNTY")
        parsed_day = date.fromisoformat(day)
        _require(parsed_day.isoformat() == day and parsed_day.strftime("%Y%m") == "202501", "DAY")
        _require(
            measure in MEASURES and record.get("source_variable") == measure.lower(), "MEASURE"
        )
        _require(record.get("unit") == MEASURES[measure], "UNIT")
        _require(
            record.get("source_unit") == ("millimeter" if measure == "PRCP" else MEASURES[measure]),
            "NATIVE_UNIT",
        )
        _require(isinstance(record.get("source_time_present"), bool), "TIME_PRESENCE")
        value, status = record.get("value"), record.get("coverage_status")
        out_of_scope = fips[:2] in {"02", "15"}
        if out_of_scope:
            _require(status == "OUT_OF_SOURCE_COVERAGE" and value is None, "OUT_OF_SCOPE")
            _require(
                _finite(record.get("valid_area_m2")) and record["valid_area_m2"] == 0,
                "OUT_OF_SCOPE",
            )
            _require(all(record.get(k) is None for k in (*AREAS[:3], *FRACTIONS)), "OUT_OF_SCOPE")
            state = "UNAVAILABLE"
        else:
            expected, intersected, supported, valid = (record.get(k) for k in AREAS)
            _require(all(_finite(v) for v in (expected, intersected, supported, valid)), "AREAS")
            _require(
                expected > 0 and 0 <= valid <= supported <= intersected <= expected * (1 + 1e-8),
                "AREAS",
            )
            source_fraction, daily_fraction = (record.get(k) for k in FRACTIONS)
            _require(
                _finite(source_fraction) and abs(source_fraction - supported / expected) < 1e-10,
                "SOURCE_FRACTION",
            )
            if supported > 0:
                _require(
                    _finite(daily_fraction) and abs(daily_fraction - valid / supported) < 1e-10,
                    "DAILY_FRACTION",
                )
            else:
                _require(daily_fraction is None, "DAILY_FRACTION")
            if status == "COMPLETE":
                _require(
                    record["source_time_present"]
                    and supported > 0
                    and daily_fraction + 1e-12 >= 0.95,
                    "COMPLETE",
                )
                _require(_finite(value) and (measure != "PRCP" or value >= 0), "VALUE")
                state = "ZERO" if value == 0 else "OBSERVED"
            else:
                _require(value is None, "MISSING_VALUE")
                _require(
                    (status == "SOURCE_MISSING" and valid == 0)
                    or (
                        status == "PARTIAL_COVERAGE"
                        and supported > 0
                        and 0 < daily_fraction < 0.95 - 1e-12
                    ),
                    "COVERAGE",
                )
                state = "MISSING"
                _require(record["source_time_present"] or valid == 0, "TIME_PRESENCE")
        for field in ("grid_id", "geometry_digest", "geometry_version"):
            _require(isinstance(record.get(field), str) and bool(record[field]), "GEOMETRY_LINEAGE")
        _require(
            record.get("weight_version") == "atlas-grid-county-area-weight/1", "WEIGHT_LINEAGE"
        )
        if not out_of_scope:
            _require(
                isinstance(record.get("weight_id"), str) and bool(record["weight_id"]),
                "WEIGHT_LINEAGE",
            )
        return {
            "contract_version": CONTRACT,
            "publication_status": "CANDIDATE_NOT_RELEASED",
            "measure_id": f"nclimgrid_{measure.lower()}_county_day",
            "county_fips": fips,
            "period_start": day,
            "period_end": day,
            "temporal_grain": "DAY",
            "value": value,
            "value_state": state,
            "unit": MEASURES[measure],
            "denominator": None,
            "coverage_status": status,
            "source_time_present": record["source_time_present"],
            **{k: record.get(k) for k in (*AREAS, *FRACTIONS)},
            "capture_run_id": RUN_ID,
            "capture_id": capture["capture_record_id"],
            "record_revision": revision,
            "normalized_sha256": normalized_hash,
            "noaa_sha256": NOAA_SHA,
            "tiger_sha256": TIGER_SHA,
            "atlas_acquired_at": _timestamp(capture["retrieved_at"]),
            "source_published_at": None,
            "upstream_date_modified": record.get("upstream_date_modified") or None,
            "methodology_version": record["transformation_version"],
            **{
                k: record.get(k)
                for k in (
                    "grid_id",
                    "grid_crs",
                    "weight_id",
                    "weight_version",
                    "geometry_digest",
                    "geometry_version",
                )
            },
            "limitations": list(LIMITATIONS),
        }
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, ClimatePublicationBlocked):
            raise
        raise ClimatePublicationBlocked("CAPTURE_INVALID") from None


def write_candidate_projection(
    captures: Iterable[Mapping[str, Any]], output: Path
) -> dict[str, Any]:
    """Atomically write a complete candidate; a partial/failed export never replaces it.

    The file is a review artifact, not an admission or publication receipt.
    Every canonical county/day/measure must be present exactly once.
    """
    seen: set[tuple[str, str, str]] = set()
    digest = hashlib.sha256()
    expected = len(COUNTIES) * 31 * len(MEASURES)
    previous: tuple[str, str, str] | None = None
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=output.parent, delete=False) as handle:
            temporary = Path(handle.name)
            for capture in captures:
                projected = project_capture_record(capture)
                key = (projected["county_fips"], projected["period_start"], projected["measure_id"])
                _require(key not in seen and len(seen) < expected, "DUPLICATE_OR_EXCESS")
                _require(previous is None or key > previous, "ORDER")
                previous = key
                seen.add(key)
                line = (
                    json.dumps(projected, sort_keys=True, separators=(",", ":"), allow_nan=False)
                    + "\n"
                ).encode()
                handle.write(line)
                digest.update(line)
            _require(len(seen) == expected, "INCOMPLETE_CAPTURE")
        os.replace(temporary, output)
        temporary = None
        return {
            "contract_version": CONTRACT,
            "capture_run_id": RUN_ID,
            "publication_status": "CANDIDATE_NOT_RELEASED",
            "rows": len(seen),
            "projection_sha256": digest.hexdigest(),
        }
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare_candidate(cursor: Any, output: Path) -> dict[str, Any]:
    """Read one existing DEV capture; all warehouse statements are SELECT."""
    cursor.execute("SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()")
    identity = cursor.fetchone()
    _require(
        identity is not None
        and tuple(identity)
        == (
            "OH_LYME_DEV_PIPELINE_SVC",
            "OH_LYME_DEV_RUNTIME",
            "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            "OH_LYME_DEV_INGEST_XS_WH",
        ),
        "RUNTIME_IDENTITY",
    )
    cursor.execute(
        "SELECT resource_key, status FROM GOVERNANCE.INGESTION_RUNS WHERE ingestion_run_id=%s",
        (RUN_ID,),
    )
    _require(cursor.fetchall() == [(RESOURCE_KEY, "COMPLETED")], "RUN_NOT_COMPLETED")
    cursor.execute(
        "SELECT sha256, byte_count FROM GOVERNANCE.RAW_ARTIFACTS WHERE ingestion_run_id=%s",
        (RUN_ID,),
    )
    _require(
        sorted(cursor.fetchall()) == sorted([(NOAA_SHA, 61013299), (TIGER_SHA, 83989800)]),
        "ARTIFACT_LEDGER",
    )
    cursor.execute(
        "SELECT stage, status FROM GOVERNANCE.INGESTION_RUN_CHECKPOINTS WHERE ingestion_run_id=%s",
        (RUN_ID,),
    )
    stages = list(cursor.fetchall())
    for stage in ("ACQUIRE", "VALIDATE", "NORMALIZE", "LOAD", "QUALITY", "PUBLISH_STAGE"):
        _require(
            [status for name, status in stages if name == stage] == ["COMPLETED"], "CHECKPOINTS"
        )
    cursor.execute(
        "SELECT partition_count FROM GOVERNANCE.INGESTION_RUN_PARTITION_COMPLETIONS "
        "WHERE ingestion_run_id=%s",
        (RUN_ID,),
    )
    _require(cursor.fetchall() == [(1560,)], "PARTITION_COMPLETION")
    cursor.execute(
        "SELECT COUNT(*), SUM(row_count), MIN(partition_ordinal), MAX(partition_ordinal), "
        "COUNT(DISTINCT partition_ordinal) FROM GOVERNANCE.INGESTION_RUN_NORMALIZED_PARTITIONS "
        "WHERE ingestion_run_id=%s",
        (RUN_ID,),
    )
    _require(
        cursor.fetchall() == [(1560, len(COUNTIES) * 31 * 4, 0, 1559, 1560)], "PARTITION_SCOPE"
    )
    cursor.execute(CAPTURE_QUERY, (RUN_ID,))
    columns = [str(column[0]).lower() for column in cursor.description]

    def records() -> Iterable[dict[str, Any]]:
        while batch := cursor.fetchmany(1000):
            for row in batch:
                yield dict(zip(columns, row, strict=True))

    return write_candidate_projection(records(), output)


def create_candidate(output: Path) -> dict[str, Any]:
    """Use already configured DEV runtime access; never create credentials."""
    try:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            return prepare_candidate(cursor, output)
    except ClimatePublicationBlocked:
        raise
    except Exception:
        raise ClimatePublicationBlocked("CAPTURE_READ_BLOCKED") from None


def candidate_evidence(directory: Path) -> dict[str, Any]:
    """Read the frozen capture twice and emit counts and one safe example per state."""
    first = create_candidate(directory / "first.ndjson")
    second = create_candidate(directory / "second.ndjson")
    _require(first == second, "NONREPEATABLE_CANDIDATE")
    counts: dict[str, int] = {}
    examples: dict[str, dict[str, Any]] = {}
    with (directory / "first.ndjson").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            key = f"{row['coverage_status']}:{row['value_state']}"
            counts[key] = counts.get(key, 0) + 1
            if key not in examples:
                examples[key] = {
                    field: row[field]
                    for field in (
                        "county_fips",
                        "period_start",
                        "measure_id",
                        "value",
                        "value_state",
                        "coverage_status",
                        "unit",
                    )
                }
    _require(sum(counts.values()) == first["rows"] and len(examples) <= 8, "EVIDENCE_SCOPE")
    return first | {
        "repeat_projection_sha256": second["projection_sha256"],
        "coverage_value_state_counts": counts,
        "examples": examples,
        "writes_performed": False,
    }
