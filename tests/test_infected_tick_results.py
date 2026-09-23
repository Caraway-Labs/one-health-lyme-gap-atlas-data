"""Consumer contract assertions independent of metric arithmetic fixtures."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_infected_tick_metrics import _canonical

from lyme_gap_atlas_data.infected_tick_metrics import (
    DENSITY,
    PREVALENCE,
    calculate_infected_tick_metric,
)
from lyme_gap_atlas_data.infected_tick_result_store import stage_infected_tick_result
from lyme_gap_atlas_data.infected_tick_results import serialize_infected_tick_result
from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    PROD_DATABASE,
    load_migrations,
    migration_plan,
)


def _document(metric: str, observation: dict | None = None) -> dict:
    result = calculate_infected_tick_metric(metric, [observation or _canonical(metric)])
    return serialize_infected_tick_result(result, evidence_basis="SYNTHETIC_FIXTURE")


def test_m2_numeric_zero_and_governed_conversion() -> None:
    observation = _canonical(DENSITY)
    document = _document(DENSITY, observation)
    assert (document["value"], document["numerator"], document["denominator"]) == (2, 8, 4)
    assert document["unit"] == "ticks_per_square_metre"
    assert document["native_grain"] == "SITE_EVENT"
    assert document["site"]["source_site_id"] == "BLAN"
    assert document["event"]["source_event_id"] == "event-one"
    assert document["county_relationship"]["county_fips"] is None
    assert document["county_relationship"]["representativeness"] == "NOT_COUNTY_REPRESENTATIVE"
    assert "METHOD_COMPARABILITY_NOT_ESTABLISHED" in document["quality"]["inherited_limitations"]
    assert document["safe_lineage"][0]["normalization_registry_version"] == "1.0.4"
    assert document["evidence_status"]["calculation_basis"] == "SYNTHETIC_FIXTURE"
    assert document["evidence_status"]["current_code_source_backed_replay"] == "EVIDENCE_LIMITED"
    assert (
        document["evidence_status"]["historical_ingestion_context"]["relationship"]
        == "SEPARATE_162_EVIDENCE_NOT_RESULT_LINEAGE"
    )
    result = calculate_infected_tick_metric(DENSITY, [observation], output_unit="ticks_per_hectare")
    converted = serialize_infected_tick_result(result, evidence_basis="SYNTHETIC_FIXTURE")
    assert converted["result_id"] == document["result_id"]
    assert converted["value"] == 2
    assert converted["presentation_conversion"]["value"] == 20000
    observation["ticks_collected"] = 0
    zero = _document(DENSITY, observation)
    assert zero["state"] == "NUMERIC" and zero["value"] == 0
    assert zero["result_id"] != document["result_id"]


def test_m1_numeric_zero_and_current_neon_unavailable() -> None:
    observation = _canonical(PREVALENCE)
    numeric = _document(PREVALENCE, observation)
    assert numeric["value"] == 1 and numeric["unit"] == "proportion"
    assert numeric["safe_lineage"][0]["source_testing_id"] == "test-one"
    observation["ticks_positive"] = 0
    observation["normalization"]["mappings"]["result"]["canonical_id"] = "NOT_DETECTED"
    observation["normalization"]["mappings"]["result"]["canonical_label"] = "Not detected"
    observation["normalization"]["mappings"]["result"]["source_value"] = "negative"
    observation["normalization"]["mappings"]["result"]["mapping_rule_id"] = (
        "RESULT_NEON_NEGATIVE_V1"
    )
    assert _document(PREVALENCE, observation)["value"] == 0
    observation = _canonical(PREVALENCE)
    observation.pop("life_stage")
    observation["normalization"]["mappings"].pop("stage")
    unavailable = _document(PREVALENCE, observation)
    assert unavailable["state"] == "UNAVAILABLE" and unavailable["value"] is None
    assert "UNRESOLVED_LIFE_STAGE" in unavailable["unavailable_reasons"]


def test_m2_unavailable_and_safe_lineage() -> None:
    observation = _canonical(DENSITY)
    observation["collection_effort_value"] = 0
    observation["private_raw_payload"] = "top-secret"
    observation["artifact_uri"] = "s3://private/bucket"
    document = _document(DENSITY, observation)
    assert document["state"] == "UNAVAILABLE" and document["value"] is None
    assert "ZERO_EFFORT" in document["unavailable_reasons"]
    rendered = str(document).lower()
    assert "artifact_id" not in rendered
    assert "artifact_uri" not in rendered
    assert "s3://" not in rendered
    assert "raw_payload" not in rendered
    assert "top-secret" not in rendered


def test_unavailable_result_survives_missing_identity_and_provenance() -> None:
    observation = _canonical(DENSITY)
    observation["sampling_site"] = {}
    observation["artifact_id"] = ""
    observation["normalization"] = None
    document = _document(DENSITY, observation)
    assert document["state"] == "UNAVAILABLE"
    assert document["site"]["source_site_id"] is None
    assert document["safe_lineage"][0]["normalization_registry_id"] is None
    assert "MISSING_SITE_EVENT_IDENTITY" in document["unavailable_reasons"]
    assert "MISSING_REQUIRED_PROVENANCE" in document["unavailable_reasons"]


def test_identity_revision_and_mapped_site_remains_non_county() -> None:
    observation = _canonical(DENSITY)
    baseline = _document(DENSITY, observation)
    assert _document(DENSITY, observation) == baseline
    for field, replacement in (
        ("canonical_observation_id", "canonical-new"),
        ("source_record_id", "record-revised"),
        ("data_source_version_id", "RELEASE-2027"),
    ):
        changed = deepcopy(observation)
        changed[field] = replacement
        assert _document(DENSITY, changed)["result_id"] != baseline["result_id"]
    mapped = deepcopy(observation)
    mapped["county_relationship"]["mapping_status"] = "ATLAS_DERIVED_MATCH"
    mapped["county_relationship"]["county_fips"] = "51003"
    mapped["county_relationship"]["mapping_method"] = "fixture-crosswalk"
    mapped["county_relationship"]["mapping_version"] = "fixture-v1"
    assert _document(DENSITY, mapped)["county_relationship"] == {
        "mapping_status": "ATLAS_DERIVED_MATCH",
        "county_fips": "51003",
        "mapping_method": "fixture-crosswalk",
        "mapping_version": "fixture-v1",
        "representativeness": "NOT_COUNTY_REPRESENTATIVE",
    }


def test_rejects_invalid_grain_unit_state_and_unsafe_metadata() -> None:
    result = calculate_infected_tick_metric(DENSITY, [_canonical(DENSITY)])
    for field, invalid in (
        ("native_grain", "COUNTY"),
        ("unit", "ticks_per_hectare"),
        ("state", "UNKNOWN"),
    ):
        altered = deepcopy(result)
        altered[field] = invalid
        with pytest.raises(ValueError):
            serialize_infected_tick_result(altered, evidence_basis="SYNTHETIC_FIXTURE")
    unsafe = deepcopy(result)
    unsafe["source_lineage"][0]["source_record_id"] = "https://private.invalid/raw?token=secret"
    with pytest.raises(ValueError, match="unsafe"):
        serialize_infected_tick_result(unsafe, evidence_basis="SYNTHETIC_FIXTURE")
    with pytest.raises(ValueError):
        serialize_infected_tick_result(result, evidence_basis="CURRENT_CODE_SOURCE_REPLAY_VERIFIED")
    for version_field in ("methodology_version", "calculation_version"):
        future = deepcopy(result)
        future[version_field] = "unreviewed-v2"
        with pytest.raises(ValueError, match="version"):
            serialize_infected_tick_result(future, evidence_basis="SYNTHETIC_FIXTURE")


class _MemoryCursor:
    """Minimal SQL boundary fake; it asserts immutable storage call behavior."""

    def __init__(self) -> None:
        self.rows: dict[str, str] = {}
        self.current: list[tuple[str]] = []
        self.merges = 0

    def execute(self, sql: str, params: tuple) -> None:
        if sql.startswith("SELECT payload_sha256"):
            self.current = [(self.rows[params[0]],)] if params[0] in self.rows else []
        elif sql.startswith("MERGE INTO"):
            self.merges += 1
            self.rows.setdefault(params[0], params[1])
        else:
            raise AssertionError("unexpected SQL")

    def fetchall(self) -> list[tuple[str]]:
        return self.current


def test_immutable_store_duplicate_and_revision_behavior() -> None:
    cursor = _MemoryCursor()
    result = calculate_infected_tick_metric(DENSITY, [_canonical(DENSITY)])
    baseline_id, state = stage_infected_tick_result(
        cursor, result, evidence_basis="SYNTHETIC_FIXTURE"
    )
    assert state == "STAGED" and cursor.merges == 1
    assert stage_infected_tick_result(cursor, result, evidence_basis="SYNTHETIC_FIXTURE") == (
        baseline_id,
        "IDENTICAL_REPLAY",
    )
    assert cursor.merges == 1
    changed = _canonical(DENSITY)
    changed["canonical_observation_id"] = "canonical-revision"
    revised = calculate_infected_tick_metric(DENSITY, [changed])
    revision_id, state = stage_infected_tick_result(
        cursor, revised, evidence_basis="SYNTHETIC_FIXTURE"
    )
    assert state == "STAGED" and revision_id != baseline_id and len(cursor.rows) == 2
    with pytest.raises(ValueError, match="conflicting"):
        stage_infected_tick_result(
            cursor, result, evidence_basis="CURRENT_CODE_CI_TESTED_SOURCE_REPLAY_LIMITED"
        )
    assert cursor.merges == 2


def test_dev_migration_is_not_in_prod_plan() -> None:
    assert "V100" in {item["version"] for item in migration_plan(DEV_DATABASE)}
    assert "V100" not in {item["version"] for item in migration_plan(PROD_DATABASE)}
    migration = next(item for item in load_migrations() if item.version == "V100")
    assert "PRESENTATION.INFECTED_TICK_DERIVED_RESULTS" in migration.source
    assert "PRESENTATION.SEMANTIC_OBSERVATIONS" not in migration.source
    assert "OH_LYME_DEV_API_RUNTIME" not in migration.source


def test_committed_dev_fixture_is_synthetic_and_calculable() -> None:
    fixture_path = (
        Path(__file__).parent
        / "fixtures/tick_surveillance/infected-tick-derived-result-v1-dev-fixture.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture["canonical_observation_id"] == "canonical-one"
    assert fixture["ingestion_run_id"] == "run-one"
    assert fixture["artifact_id"] == "artifact-one"
    assert _document(DENSITY, fixture)["value"] == 2
