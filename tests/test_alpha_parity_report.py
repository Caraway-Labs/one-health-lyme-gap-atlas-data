"""Tests for the metadata-only, full-county Alpha parity report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lyme_gap_atlas_data.alpha_parity import AlphaParityError, build_report


def _row(fips: str, *, tick: str = "No records") -> dict[str, object]:
    return {
        "fips": fips,
        "county": "Example",
        "state": "EX",
        "state_name": "Example",
        "population": 1,
        "in_contiguous_tick_scope": True,
        "human_status": "no_county_linked_record",
        "case_count_floor_2023": None,
        "incidence_floor_2023": None,
        "state_unallocated_records_2023": 0,
        "tick_status": tick,
        "scapularis_status": tick,
        "pacificus_status": "No records",
        "burgdorferi_status": "No records",
        "svi_percentile": 0.1,
        "uninsured_percentile": 0.1,
        "uninsured_percent": 1.0,
        "rucc_2023": 1,
        "evidence_completeness": 50,
        "geometry": {"type": "Polygon", "coordinates": []},
    }


def _bundle(path: Path) -> None:
    rows = [_row(f"{number:05d}") for number in range(1, 3145)]
    path.write_text(
        json.dumps(
            {
                "sources": [],
                "feature_collection": {
                    "features": [
                        {"properties": row, "geometry": row.pop("geometry")} for row in rows
                    ]
                },
            }
        ),
        encoding="utf-8",
    )


def test_report_classifies_known_unknown_coverage_difference(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha.json"
    _bundle(alpha)
    candidate = [_row(f"{number:05d}", tick="Unknown") for number in range(1, 3145)]
    report = build_report(
        alpha,
        candidate,
        release_id="candidate",
        bundle_sha256="a" * 64,
        methodology_version="semantic-1",
        source_metadata=[
            {"source_key": key}
            for key in ("human", "tick", "pathogen", "context_svi", "context_rucc")
        ],
        release_metadata={"release_id": "candidate", "bundle_sha256": "a" * 64},
    )
    tick = next(item for item in report["field_comparisons"] if item["field"] == "tick_status")
    assert tick["difference_count"] == 3144
    assert tick["category"] == "MISSINGNESS_VALUE_STATE"
    assert report["coverage"]["shared_count"] == 3144
    assert report["classification_complete"] is True
    assert report["cutover_eligible"] is False


def test_report_refuses_incomplete_county_coverage(tmp_path: Path) -> None:
    alpha = tmp_path / "alpha.json"
    _bundle(alpha)
    with pytest.raises(AlphaParityError, match="3,144"):
        build_report(
            alpha,
            [],
            release_id="candidate",
            bundle_sha256="a" * 64,
            methodology_version="semantic-1",
            source_metadata=[],
            release_metadata={},
        )
