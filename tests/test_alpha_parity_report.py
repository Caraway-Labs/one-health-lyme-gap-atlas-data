"""Tests for the metadata-only, full-county Alpha parity report."""

from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from lyme_gap_atlas_data import alpha_parity
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


def test_candidate_reader_uses_only_release_scoped_semantic_relations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries: list[str] = []
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> CompletedProcess[str]:
        commands.append(command)
        query = command[command.index("-q") + 1]
        queries.append(query)
        stdout = (
            '[{"RELEASE_ID":"candidate-1","BUNDLE_SHA256":"a","STATUS":"CANDIDATE"}]'
            if "SEMANTIC_RELEASES" in query
            else "[]"
        )
        return CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(alpha_parity.subprocess, "run", fake_run)

    alpha_parity.fetch_current_semantic_rows(
        "ATLAS_PROD_MIGRATOR",
        "candidate-1",
        candidate=True,
        database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        warehouse="OH_LYME_PROD_INGEST_XS_WH",
    )
    alpha_parity.fetch_current_source_metadata("ATLAS_PROD_MIGRATOR", "candidate-1")
    alpha_parity.fetch_current_release_metadata("ATLAS_PROD_MIGRATOR", "candidate-1")

    assert "PRESENTATION.SEMANTIC_COUNTY_ATLAS" in queries[0]
    assert "PRESENTATION.SEMANTIC_DATA_SOURCES" in queries[1]
    assert "PRESENTATION.SEMANTIC_RELEASES" in queries[2]
    assert all("CURRENT_" not in query for query in queries)
    assert all("candidate-1" in query for query in queries)
    assert commands[0][-4:] == [
        "--database",
        "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        "--warehouse",
        "OH_LYME_PROD_INGEST_XS_WH",
    ]
