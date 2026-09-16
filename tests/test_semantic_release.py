"""Contract and assembly tests for the governed semantic release boundary."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import lyme_gap_atlas_data.semantic_release as semantic_release
from lyme_gap_atlas_data.semantic_release import (
    CountyRow,
    SemanticManifest,
    SemanticReleaseBlocked,
    SemanticSource,
    SourceGate,
    _assemble_counties,
    _bundle_sha256,
    _evidence_completeness,
    _tick_status,
    _value_state,
    load_manifest,
)

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = (
    REPO / "docs" / "contracts" / "semantic-release" / "governed-2026-09-15-manifest.template.json"
)


def _source(source_key: str) -> SemanticSource:
    field_map: dict[str, tuple[str, ...]] = {}
    if source_key == "tick":
        field_map = {
            "fips": ("FIPSCode",),
            "scapularis_status": ("Ixodes_scapularis_County_Status",),
            "pacificus_status": ("Ixodes_pacificus_county_status",),
        }
    elif source_key == "pathogen":
        field_map = {
            "fips": ("FIPSCode",),
            "burgdorferi_status": ("burgdorferi_status",),
        }
    return SemanticSource(
        source_key=source_key,
        resource_key=f"resource-{source_key}",
        source_id=f"source-{source_key}",
        dataset_id=f"dataset-{source_key}",
        label=source_key,
        vintage="2023",
        source_url="https://example.test/source",
        note="test source",
        data_source_version_id=f"version-{source_key}",
        ingestion_run_id=f"run-{source_key}",
        artifact_id=f"artifact-{source_key}",
        artifact_sha256="a" * 64,
        definition_version=1,
        field_map=field_map,
    )


def _manifest() -> SemanticManifest:
    sources = tuple(
        _source(key) for key in ("human", "context_svi", "context_rucc", "tick", "pathogen")
    )
    return SemanticManifest(
        release_id="test-release",
        schema_version="1.0.0",
        methodology_version="semantic-test-1",
        generated_at="2026-09-15T00:00:00Z",
        scope="US_COUNTIES",
        score_defaults={key: {} for key in semantic_release.REQUIRED_SCORE_DEFAULT_KEYS},
        limitations="test limitation",
        sources=sources,
        raw={"manifest_schema": semantic_release.SEMANTIC_SCHEMA},
    )


def _row(payload: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "payload": payload,
        "source_record_id": "source-row",
        "source_row_hash": "b" * 64,
        "retrieved_at": datetime(2026, 9, 15, tzinfo=UTC),
        **extra,
    }


def test_template_is_not_executable_until_reviewed() -> None:
    with pytest.raises(SemanticReleaseBlocked, match="placeholder"):
        load_manifest(TEMPLATE)


def test_tick_and_pathogen_are_distinct_contract_slots() -> None:
    manifest = _manifest()
    assert manifest.source("tick").resource_key != manifest.source("pathogen").resource_key

    document = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    for source_index, source in enumerate(document["sources"]):
        for field, value in list(source.items()):
            if isinstance(value, str) and value.startswith("REPLACE_WITH_"):
                source[field] = (
                    "a" * 64 if field == "artifact_sha256" else f"reviewed-{source_index}-{field}"
                )
    document["sources"][-1]["resource_key"] = document["sources"][-2]["resource_key"]
    temporary = TEMPLATE.parent / ".test-semantic-release-manifest.json"
    try:
        temporary.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(SemanticReleaseBlocked, match="distinct"):
            load_manifest(temporary)
    finally:
        temporary.unlink(missing_ok=True)


def test_assembly_preserves_lineage_and_source_native_missingness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantic_release, "EXPECTED_COUNTIES", 1)
    manifest = _manifest()
    retrieved = datetime(2026, 9, 15, tzinfo=UTC)
    gates = {source.source_key: SourceGate(source, retrieved) for source in manifest.sources}
    source_rows = {
        "context_svi": [
            _row(
                {
                    "STCNTY": "08001",
                    "COUNTY": "Adams County",
                    "ST_ABBR": "CO",
                    "STATE": "Colorado",
                    "E_TOTPOP": 100,
                    "RPL_THEMES": 0.5,
                    "EPL_UNINSUR": 0.25,
                    "EP_UNINSUR": 5,
                    "geometry": {"type": "Polygon", "coordinates": []},
                }
            )
        ],
        "context_rucc": [_row({"FIPS": "08001", "Attribute": "RUCC_2023", "Value": "4"})],
        "human": [
            _row(
                {"state": "Colorado"},
                county_fips="08001",
                report_year=2023,
                case_status="Confirmed",
                frequency=2,
            )
        ],
        "tick": [
            _row(
                {
                    "FIPSCode": "08001",
                    "Ixodes_scapularis_County_Status": "Established",
                    "Ixodes_pacificus_county_status": "No records",
                }
            )
        ],
        "pathogen": [_row({"FIPSCode": "08001", "burgdorferi_status": "No records"})],
    }

    counties, observations = _assemble_counties(manifest, source_rows, gates)

    assert len(counties) == 1
    assert counties[0].values[7:12] == (
        "published_count_floor",
        2,
        2000.0,
        0,
        "Established",
    )
    assert counties[0].values[20][0:1] == "{"
    assert len(observations) == 14
    assert any(row[2] == "scapularis_status" and row[11] == "OBSERVED" for row in observations)
    assert any(row[2] == "burgdorferi_status" and row[11] == "NO_RECORDS" for row in observations)


def test_invalid_state_unallocated_human_row_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = {"08001": {"state": "CO", "population": 100}}
    with pytest.raises(SemanticReleaseBlocked, match="state-unallocated"):
        semantic_release._human_values(
            [
                {
                    "county_fips": "Unknown",
                    "report_year": 2023,
                    "frequency": 1,
                    "case_status": "Confirmed",
                    "payload": {},
                }
            ],
            identity,
        )


def test_value_states_and_scorecard_mapping_are_explicit() -> None:
    assert _value_state(None) == "MISSING"
    assert _value_state(0) == "ZERO"
    assert _value_state("No records") == "NO_RECORDS"
    assert _value_state("no_county_linked_record") == "NO_COUNTY_LINKED_RECORD"
    assert _value_state("Suppressed") == "SUPPRESSED"
    assert _tick_status("Established", "No records") == "Established"
    assert _tick_status("No records", "Reported") == "Reported"
    assert _tick_status("No records", "No records") == "No records"
    identity = {"svi_percentile": 0.1, "uninsured_percentile": 0.2}
    assert (
        _evidence_completeness("published_count_floor", "Established", "Present", identity, 3)
        == 100
    )
    assert (
        _evidence_completeness("no_county_linked_record", "No records", "No records", identity, 3)
        == 50
    )


def test_bundle_hash_is_deterministic() -> None:
    manifest = _manifest()
    county = CountyRow(values=("test-release", "08001", "Adams"), lineage={})
    assert _bundle_sha256(manifest, [county]) == _bundle_sha256(manifest, [county])


def test_migrations_and_contract_do_not_reference_alpha_database() -> None:
    migration_text = "\n".join(
        (REPO / "migrations" / filename).read_text(encoding="utf-8")
        for filename in (
            "V071__governed_semantic_release_storage.sql",
            "V072__governed_semantic_release_views.sql",
        )
    )
    assert "ONE_HEALTH_LYME_GAP_ATLAS.PRESENTATION" not in migration_text
    assert "CURRENT_RELEASE_V" in migration_text
    assert "SEMANTIC_RELEASE_STATUS_V" in migration_text
    assert "WITH county_counts AS" in migration_text
    assert "observation_counts AS" in migration_text
    assert "missing_observation_lineage" in migration_text
    storage = (REPO / "migrations" / "V071__governed_semantic_release_storage.sql").read_text(
        encoding="utf-8"
    )
    assert (
        "ALL TABLES IN SCHEMA PRESENTATION\n    TO ROLE OH_LYME_{{ ENV }}_API_RUNTIME"
        not in storage
    )


def test_semantic_release_workflow_is_protected_and_runs_post_operation_proof() -> None:
    workflow = (REPO / ".github" / "workflows" / "publish-semantic-release.yml").read_text(
        encoding="utf-8"
    )
    assert "environment: ${{ inputs.environment_name }}" in workflow
    assert "release_commit" in workflow
    assert "git merge-base --is-ancestor" in workflow
    assert "--confirm" in workflow
    assert "SEMANTIC_RELEASE_STATUS_V" in workflow
    assert "CURRENT_RELEASE_V" in workflow
    assert "SNOWFLAKE_RUNTIME_ROLE" not in workflow
