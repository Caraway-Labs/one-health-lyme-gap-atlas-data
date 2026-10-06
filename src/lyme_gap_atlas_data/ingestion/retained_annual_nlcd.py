"""Admit a checksum-pinned derived cohort through the existing orchestrator."""

from __future__ import annotations

import hashlib
import json
import math
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from .adapters import (
    AcquireResult,
    AcquisitionError,
    NormalizeResult,
    StreamingNormalizeResult,
    _normalized_record,
)
from .types import AdapterKind, FailureCategory, SourceDefinition, ValidationIssue, ValidationResult

_NAME = "annual-nlcd-2025-demo-cohort.json"
_ENDPOINT = "file://retained/" + _NAME
_MEASURES = {
    "FOREST_AREA_SHARE",
    "DEVELOPED_AREA_SHARE",
    "AGRICULTURE_AREA_SHARE",
    "WETLAND_AREA_SHARE",
    "OPEN_WATER_AREA_SHARE",
    "MEAN_IMPERVIOUS_FRACTION",
    "LAND_COVER_CHANGED_AREA_SHARE",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _checked_records(definition: SourceDefinition, payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("Retained aggregate envelope required")
    source_envelope = {
        key: value for key, value in payload.items() if key != "_acquisition_lineage"
    }
    if hashlib.sha256(_canonical(source_envelope) + b"\n").hexdigest() != definition.extra.get(
        "aggregate_artifact_sha256"
    ):
        raise ValueError("Pinned aggregate artifact differs")
    lineage = payload["calculation_lineage"]
    digest = hashlib.sha256(_canonical(lineage)).hexdigest()
    if (
        payload["format"] != "retained-annual-nlcd-county-cohort/1"
        or payload["distribution"] != "OFFICIAL_MRLC_HTTPS_ZIP"
        or payload["geographic_selection"] != "BOUNDED_COHORT_NOT_NATIONAL_PANEL"
        or payload["calculation_lineage_sha256"] != digest
        or payload["calculation_run_id"] != "mrlc2025_" + digest
        or payload["calculation_run_id"] != definition.extra.get("calculation_run_id")
        or lineage["code_revision"] != definition.extra.get("calculation_code_revision")
        or lineage["source"]["distribution"] != "OFFICIAL_MRLC_HTTPS_ZIP"
    ):
        raise ValueError("Approved calculation identity differs")
    selected = definition.extra.get("county_fips")
    if not isinstance(selected, list) or payload["selected_counties"] != selected:
        raise ValueError("Exact selected cohort differs")
    rows = payload["records"]
    if (
        not isinstance(rows, list)
        or len(rows) != len(selected) * 7
        or len(rows) != definition.maximum_rows
    ):
        raise ValueError("Exact seven-measure cohort count differs")
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict) or any(key not in row for key in definition.required_columns):
            raise ValueError("Required aggregate fields missing")
        key = (row["county_fips"], row["measure"])
        if key in seen or key[0] not in selected or key[1] not in _MEASURES:
            raise ValueError("Duplicate or unexpected county measure")
        seen.add(key)
        if (
            row["mapping_year"] != 2025
            or row["collection_version"] != "C1V2"
            or row["lineage_id"] != digest
            or row["unit"] != "fraction"
            or row["denominator"] != "valid_source_supported_area_m2"
            or row["geometry_version"] != "atlas-county-analysis-geometry/1"
            or row["weight_version"] != "atlas-grid-county-area-weight/1"
            or row["transformation_version"] != lineage["transform"]
        ):
            raise ValueError("Frozen source or measure semantics differ")
        if (
            row["coverage_status"] != "COMPLETE"
            or not math.isfinite(row["value"])
            or not 0 <= row["value"] <= 1
        ):
            raise ValueError("This reviewed numeric cohort has unexpected value state")
        if abs(row["valid_fraction_of_supported_area"] - 1) > 1e-12:
            raise ValueError("Observed source support has incomplete validity")
        if not 0 < row["source_coverage_fraction"] <= 1 + 1e-8:
            raise ValueError("Invalid preserved source coverage")
    if seen != {(fips, measure) for fips in selected for measure in _MEASURES}:
        raise ValueError("Selected cohort is not complete for all seven measures")
    return cast(list[dict[str, Any]], rows)


class RetainedAnnualNLCDAggregateAdapter:
    """Capture the real retained aggregate envelope, never reacquire rasters."""

    kind = AdapterKind.RETAINED_ANNUAL_NLCD_AGGREGATE

    def acquire(
        self, definition: SourceDefinition, *, fixture_dir: Path | None = None
    ) -> AcquireResult:
        if definition.endpoint_template != _ENDPOINT:
            raise AcquisitionError("Unreviewed retained endpoint", code="AGGREGATE_ENDPOINT")
        body = (
            (fixture_dir / _NAME).read_bytes()
            if fixture_dir
            else files("lyme_gap_atlas_data").joinpath("data", _NAME).read_bytes()
        )
        bound = definition.extra.get("maximum_artifact_bytes")
        if not isinstance(bound, int) or not 0 < len(body) <= bound <= 131072:
            raise AcquisitionError(
                "Retained artifact exceeds reviewed bound", code="AGGREGATE_BYTE_BOUND"
            )
        if hashlib.sha256(body).hexdigest() != definition.extra.get("aggregate_artifact_sha256"):
            raise AcquisitionError("Exact retained bytes differ", code="AGGREGATE_INTEGRITY")
        try:
            payload = json.loads(body)
            rows = _checked_records(definition, payload)
        except (ValueError, KeyError, TypeError) as error:
            raise AcquisitionError(
                "Retained cohort integrity failed", code="AGGREGATE_INTEGRITY"
            ) from error
        return AcquireResult(
            payload=payload,
            artifact_sha256=hashlib.sha256(body).hexdigest(),
            media_type="application/json",
            row_count=len(rows),
            raw_payload=body,
            detail={
                "source": "reviewed_retained_derived_aggregate",
                "calculation_run_id": payload["calculation_run_id"],
                "geographic_selection": payload["geographic_selection"],
            },
        )

    def validate_payload(self, definition: SourceDefinition, payload: Any) -> ValidationResult:
        try:
            _checked_records(definition, payload)
        except (ValueError, KeyError, TypeError) as error:
            return ValidationResult(
                ok=False,
                issues=[
                    ValidationIssue(
                        code="AGGREGATE_INTEGRITY",
                        message=str(error),
                        category=FailureCategory.SCHEMA,
                    )
                ],
            )
        return ValidationResult(ok=True)

    def normalize(self, definition: SourceDefinition, payload: Any) -> NormalizeResult:
        rows = _checked_records(definition, payload)
        return NormalizeResult(
            records=[_normalized_record(definition, row) for row in rows],
            transformation_version="retained_nlcd_cohort_envelope_v1",
            detail={
                "record_count": len(rows),
                "calculation_run_id": payload["calculation_run_id"],
                "geographic_selection": payload["geographic_selection"],
            },
        )

    def restore_raw_payload(self, definition: SourceDefinition, raw_payload: bytes) -> Any:
        payload = json.loads(raw_payload)
        _checked_records(definition, payload)
        return payload

    def normalize_iter(
        self, definition: SourceDefinition, payload: Any
    ) -> StreamingNormalizeResult:
        normalized = self.normalize(definition, payload)
        return StreamingNormalizeResult(
            iter(normalized.records), normalized.transformation_version, normalized.detail
        )
