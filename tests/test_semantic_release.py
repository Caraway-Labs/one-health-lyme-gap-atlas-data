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
    EvidenceOnlyCoverageClassification,
    PathogenParityClassification,
    SemanticManifest,
    SemanticReleaseBlocked,
    SemanticSource,
    SourceGate,
    TickParityClassification,
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


def test_release_generated_at_is_coerced_to_immutable_storage_type() -> None:
    class CapturingCursor:
        statement = ""

        def execute(self, statement: str, _parameters: tuple[object, ...]) -> None:
            self.statement = statement

    cursor = CapturingCursor()
    semantic_release._insert_release(cursor, _manifest(), "a" * 64)

    assert "TO_TIMESTAMP_LTZ(%s)" in cursor.statement


def test_bulk_semantic_rows_use_values_for_connector_batch_binding() -> None:
    module = Path("src/lyme_gap_atlas_data/semantic_release.py").read_text(encoding="utf-8")

    assert "PARSE_JSON($21),PARSE_JSON($22)\n        FROM VALUES" in module
    assert "PARSE_JSON($11),$12,$13,$14,$15,$16,$17,$18\n        FROM VALUES" in module


def test_bound_value_batches_keep_values_parameterized_and_bounded() -> None:
    class CapturingCursor:
        calls: list[tuple[str, tuple[object, ...]]] = []

        def execute(self, statement: str, parameters: tuple[object, ...]) -> None:
            self.calls.append((statement, parameters))

    cursor = CapturingCursor()
    semantic_release._execute_bound_value_batches(
        cursor,
        "INSERT INTO example SELECT $1, PARSE_JSON($2) FROM VALUES",
        [("one", "{}"), ("two", "{}")],
        row_width=2,
        batch_size=1,
    )

    assert len(cursor.calls) == 2
    assert cursor.calls[0][0].endswith("VALUES (%s,%s)")
    assert cursor.calls[0][1] == ("one", "{}")


def test_tick_and_pathogen_are_distinct_contract_slots() -> None:
    manifest = _manifest()
    assert manifest.source("tick").resource_key != manifest.source("pathogen").resource_key

    module = Path("src/lyme_gap_atlas_data/semantic_release.py").read_text(encoding="utf-8")
    assert "RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS" in module
    assert "RESTRICTED_CDC_TICK_COUNTY_STATUS" in module
    assert "PRIVATE_OPERATOR_VERIFIED_WORKBOOK" in module
    assert "RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS" in module

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


def test_prod_final_copy_gate_requires_every_restricted_source_attestation() -> None:
    class Cursor:
        def __init__(self, responses: list[tuple[int, ...]]) -> None:
            self.responses = iter(responses)
            self.statements: list[str] = []

        def execute(self, statement: str, _parameters: tuple[str, ...]) -> None:
            self.statements.append(statement)

        def fetchone(self) -> tuple[int, ...]:
            return next(self.responses)

    blocked_cursor = Cursor([(2,), (1,)])
    with pytest.raises(SemanticReleaseBlocked, match="final-copy"):
        semantic_release._verify_restricted_final_copy_attestations(
            blocked_cursor, "candidate-release"
        )

    allowed_cursor = Cursor([(2,), (2,)])
    semantic_release._verify_restricted_final_copy_attestations(allowed_cursor, "candidate-release")
    assert "RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS" in allowed_cursor.statements[1]


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
        "context_rucc": [
            _row({"FIPS": "08001", "Attribute": "RUCC_2023", "Value": "4"}),
            _row({"FIPS": "01001", "Attribute": "RUCC_2023", "Value": "8"}),
        ],
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


def test_assembly_rejects_a_missing_canonical_rucc_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantic_release, "EXPECTED_COUNTIES", 1)
    manifest = _manifest()
    gates = {
        source.source_key: SourceGate(source, datetime(2026, 9, 15, tzinfo=UTC))
        for source in manifest.sources
    }
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
        "context_rucc": [_row({"FIPS": "01001", "Attribute": "RUCC_2023", "Value": "8"})],
        "human": [],
        "tick": [],
        "pathogen": [],
    }

    with pytest.raises(SemanticReleaseBlocked, match="does not cover every"):
        _assemble_counties(manifest, source_rows, gates)


def test_assembly_preserves_source_native_multipolygon_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantic_release, "EXPECTED_COUNTIES", 1)
    manifest = _manifest()
    gates = {
        source.source_key: SourceGate(source, datetime(2026, 9, 15, tzinfo=UTC))
        for source in manifest.sources
    }
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
                    "geometry": {"type": "MultiPolygon", "coordinates": []},
                }
            )
        ],
        "context_rucc": [_row({"FIPS": "08001", "Attribute": "RUCC_2023", "Value": "4"})],
        "human": [],
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

    counties, _ = _assemble_counties(manifest, source_rows, gates)

    assert '"type":"MultiPolygon"' in counties[0].values[20]


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


def test_explicitly_geography_unavailable_human_rows_are_not_allocated() -> None:
    identity = {"08001": {"state": "CO", "population": 100}}
    values = semantic_release._human_values(
        [
            {
                "county_fips": "Unknown",
                "report_year": 2023,
                "frequency": 1,
                "case_status": "Confirmed",
                "payload": {"state": "Unknown"},
            },
            {
                "county_fips": "Suppressed",
                "report_year": 2023,
                "frequency": 2,
                "case_status": "Probable",
                "payload": {"state": "Suppressed"},
            },
        ],
        identity,
    )

    assert values["08001"]["state_unallocated"] == 0


def test_pathogen_source_scope_superset_is_not_allocated_to_canonical_counties() -> None:
    source = _source("pathogen")
    identity = {"08001": {}}
    classification = PathogenParityClassification(
        "classification", 0, datetime(2026, 9, 15, tzinfo=UTC)
    )
    values = semantic_release._surveillance_values(
        [
            _row({"FIPSCode": "08001", "burgdorferi_status": "No records"}),
            _row({"FIPSCode": "01001", "burgdorferi_status": "Present"}),
        ],
        source,
        identity,
        kind="pathogen",
        pathogen_parity=classification,
    )
    assert set(values) == {"08001"}


def test_tick_source_scope_superset_is_not_allocated_to_canonical_counties() -> None:
    source = _source("tick")
    identity = {"08001": {}}
    values = semantic_release._surveillance_values(
        [
            _row(
                {
                    "FIPSCode": "08001",
                    "Ixodes_scapularis_County_Status": "Established",
                    "Ixodes_pacificus_county_status": "No records",
                }
            ),
            _row(
                {
                    "FIPSCode": "01001",
                    "Ixodes_scapularis_County_Status": "Reported",
                    "Ixodes_pacificus_county_status": "No records",
                }
            ),
        ],
        source,
        identity,
        kind="tick",
    )
    assert set(values) == {"08001"}


def test_value_states_and_scorecard_mapping_are_explicit() -> None:
    assert _value_state(None) == "MISSING"
    assert _value_state(0) == "ZERO"
    assert _value_state("No records") == "NO_RECORDS"
    assert _value_state("no_county_linked_record") == "NO_COUNTY_LINKED_RECORD"
    assert _value_state("Suppressed") == "SUPPRESSED"
    assert _tick_status("Established", "No records") == "Established"
    assert _tick_status("No records", "Reported") == "Reported"
    assert _tick_status("No records", "No records") == "No records"
    assert _tick_status("Unknown", "Unknown") == "Unknown"
    identity = {"svi_percentile": 0.1, "uninsured_percentile": 0.2}
    assert (
        _evidence_completeness("published_count_floor", "Established", "Present", identity, 3)
        == 100
    )
    assert (
        _evidence_completeness("no_county_linked_record", "No records", "No records", identity, 3)
        == 50
    )
    assert (
        _evidence_completeness("no_county_linked_record", "Unknown", "No records", identity, 3)
        == 50
    )


def test_pathogen_parity_classification_preserves_unknown_not_no_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantic_release, "EXPECTED_COUNTIES", 2)
    source = _source("pathogen")
    identity = {"08001": {}, "08003": {}}
    values = semantic_release._surveillance_values(
        [_row({"FIPSCode": "08001", "burgdorferi_status": "Present"})],
        source,
        identity,
        kind="pathogen",
        pathogen_parity=PathogenParityClassification("classification-1", 1, datetime.now(UTC)),
    )
    assert values["08003"]["burgdorferi_status"] == "Unknown"
    assert values["08003"]["parity_classification_id"] == "classification-1"


def test_evidence_only_tick_coverage_preserves_unknown_not_no_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantic_release, "EXPECTED_COUNTIES", 2)
    source = _source("tick")
    identity = {"08001": {}, "08003": {}}
    values = semantic_release._surveillance_values(
        [],
        source,
        identity,
        kind="tick",
        evidence_only_coverage=EvidenceOnlyCoverageClassification(
            "classification-2", 2, datetime.now(UTC)
        ),
    )
    assert values["08001"]["scapularis_status"] == "Unknown"
    assert values["08003"]["pacificus_status"] == "Unknown"
    assert values["08003"]["coverage_classification_id"] == "classification-2"


def test_evidence_only_tick_coverage_cannot_mask_source_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantic_release, "EXPECTED_COUNTIES", 2)
    with pytest.raises(SemanticReleaseBlocked, match="count does not match"):
        semantic_release._surveillance_values(
            [
                _row(
                    {
                        "FIPSCode": "08001",
                        "Ixodes_scapularis_County_Status": "Established",
                        "Ixodes_pacificus_county_status": "No records",
                    }
                )
            ],
            _source("tick"),
            {"08001": {}, "08003": {}},
            kind="tick",
            evidence_only_coverage=EvidenceOnlyCoverageClassification(
                "classification-2", 2, datetime.now(UTC)
            ),
        )


def test_prod_tick_parity_classification_preserves_unknown_not_no_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantic_release, "EXPECTED_COUNTIES", 2)
    source = _source("tick")
    identity = {"08001": {}, "08003": {}}
    values = semantic_release._surveillance_values(
        [
            _row(
                {
                    "FIPSCode": "08001",
                    "Ixodes_scapularis_County_Status": "Established",
                    "Ixodes_pacificus_county_status": "No records",
                }
            )
        ],
        source,
        identity,
        kind="tick",
        tick_parity=TickParityClassification("classification-3", 1, datetime.now(UTC)),
    )
    assert values["08003"]["scapularis_status"] == "Unknown"
    assert values["08003"]["pacificus_status"] == "Unknown"
    assert values["08003"]["parity_classification_id"] == "classification-3"


def test_prod_tick_parity_classification_is_not_queried_in_dev() -> None:
    class Cursor:
        def execute(self, *_: object) -> None:
            raise AssertionError("DEV builds must not query the production parity ledger")

    assert (
        semantic_release._verify_tick_parity_classification(
            Cursor(), _source("tick"), enabled=False
        )
        is None
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
            "V073__semantic_release_pipeline_runtime_schema_usage.sql",
            "V081__dev_evidence_only_tick_coverage_classification.sql",
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
    runtime_access = (
        REPO / "migrations" / "V073__semantic_release_pipeline_runtime_schema_usage.sql"
    ).read_text(encoding="utf-8")
    assert "GRANT USAGE ON SCHEMA PRESENTATION" in runtime_access
    assert "OH_LYME_{{ ENV }}_PIPELINE_RUNTIME" in runtime_access
    assert "SEMANTIC_" not in runtime_access
    tick_coverage = (
        REPO / "migrations" / "V081__dev_evidence_only_tick_coverage_classification.sql"
    ).read_text(encoding="utf-8")
    assert "cdc_tick_ixodes_county_status" in tick_coverage
    assert "reported_county_count NUMBER NOT NULL" in tick_coverage
    assert "EVIDENCE_ONLY_SOURCE_COVERAGE_CLASSIFICATIONS" in tick_coverage


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


def test_quality_secret_scan_reports_only_non_secret_finding_metadata() -> None:
    workflow = (REPO / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")
    assert "--report-format json" in workflow
    assert ".RuleID, .File, .StartLine, .Commit, .Description" in workflow
    assert "Secret" not in workflow.split("- name: Scan Git history for secrets", 1)[1]
