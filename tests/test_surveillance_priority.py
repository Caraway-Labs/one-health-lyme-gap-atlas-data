"""Independent #172 expectations and safe derived-result boundaries."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from test_infected_tick_metrics import DENSITY, PREVALENCE, _canonical
from test_surveillance_coverage import _active_context, _county, _county_context

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    PROD_DATABASE,
    load_migrations,
    migration_plan,
)
from lyme_gap_atlas_data.semantic_release import load_manifest
from lyme_gap_atlas_data.surveillance_coverage import (
    COUNTY,
    EFFORT,
    SAMPLING,
    TESTING,
    evaluate_surveillance_coverage,
)
from lyme_gap_atlas_data.surveillance_coverage_results import serialize_surveillance_coverage
from lyme_gap_atlas_data.surveillance_priority import (
    EXPLAIN,
    FOLLOW_UP,
    NO_GAP,
    NOT_DEFENSIBLE,
    UNAVAILABLE,
    VERIFY,
    evaluate_surveillance_priority,
    stable_display_order,
)
from lyme_gap_atlas_data.surveillance_priority_result_store import stage_surveillance_priority
from lyme_gap_atlas_data.surveillance_priority_results import serialize_surveillance_priority

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures/tick_surveillance/surveillance-priority-v1-fixtures.json"
)


def _safe(
    construct: str, rows: list[dict], *, county: str = "01001", complete: bool = True
) -> dict:
    result = evaluate_surveillance_coverage(
        construct,
        rows,
        source_context=_county_context(complete)
        if construct == COUNTY
        else _active_context(construct == TESTING),
        county_fips=county if construct == COUNTY else None,
        dimension="Ixodes scapularis" if construct == COUNTY else None,
    )
    return serialize_surveillance_coverage(result, evidence_basis="SYNTHETIC_FIXTURE")


def _case(case_id: str) -> dict:
    if case_id == "county-reported":
        return _safe(COUNTY, [_county()])
    if case_id == "county-publisher-no-records":
        return _safe(COUNTY, [_county("NO_RECORDS")])
    if case_id == "county-proven-omission":
        return _safe(COUNTY, [], county="01003")
    if case_id == "county-unproven-omission":
        return _safe(COUNTY, [], county="01003", complete=False)
    if case_id == "county-unavailable":
        row = _county()
        row["source_agency"] = "unknown"
        return _safe(COUNTY, [row])
    if case_id == "county-out-of-scope":
        return _safe(COUNTY, [], county="99999")
    if case_id in {"sampled-zero", "sampling-impractical"}:
        row = _canonical(DENSITY)
        row["ticks_collected"] = 0
        if case_id == "sampling-impractical":
            row["quality_flags"] = ["SAMPLING_IMPRACTICAL"]
        return _safe(SAMPLING, [row])
    if case_id.startswith("effort-"):
        row = _canonical(DENSITY)
        if case_id == "effort-missing":
            row["collection_effort_value"] = None
            row["missingness"] = {"collection_effort_value": "UNKNOWN"}
        elif case_id == "effort-zero":
            row["collection_effort_value"] = 0
        return _safe(EFFORT, [row])
    if case_id.startswith("testing-"):
        row = _canonical(PREVALENCE)
        if case_id == "testing-missing":
            row["ticks_tested"] = None
        elif case_id == "testing-zero":
            row["ticks_tested"] = row["ticks_positive"] = 0
        else:
            row["ticks_positive"] = 0
            row["normalization"]["mappings"]["result"].update(
                {
                    "source_value": "negative",
                    "canonical_id": "NOT_DETECTED",
                    "canonical_label": "Not detected",
                    "mapping_rule_id": "RESULT_NEON_NEGATIVE_V1",
                }
            )
        return _safe(TESTING, [row])
    raise AssertionError(f"unknown independent case {case_id}")


@pytest.mark.parametrize(
    "case", json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"], ids=lambda x: x["id"]
)
def test_independent_state_disposition_matrix(case: dict) -> None:
    coverage = _case(case["id"])
    triage = evaluate_surveillance_priority(coverage)
    assert coverage["state"] == case["coverage_state"]
    assert triage["disposition"] == case["disposition"]
    assert triage["construct_id"] == case["construct"]
    safe = serialize_surveillance_priority(triage)
    assert safe["coverage_state"] == case["coverage_state"]
    assert safe["evidence_basis"] == "SYNTHETIC_FIXTURE"
    assert "artifact_id" not in str(safe)
    assert "priority_score" not in safe and "ordinal_position" not in safe
    assert safe["quality"] == coverage["quality"]
    if triage["disposition"] in {UNAVAILABLE, NOT_DEFENSIBLE}:
        assert safe["tie_group_id"] is None


def test_ties_are_scientific_and_display_is_only_lexical() -> None:
    one = _case("effort-missing")
    row = _canonical(DENSITY)
    row["canonical_observation_id"] = "second-canonical"
    row["sampling_event"]["source_event_id"] = "second-event"
    row["collection_effort_value"] = None
    row["missingness"] = {"collection_effort_value": "UNKNOWN"}
    two = _safe(EFFORT, [row])
    first_result = evaluate_surveillance_priority(one)
    second_result = evaluate_surveillance_priority(two)
    assert first_result["tie_group_id"] == second_result["tie_group_id"]
    assert first_result["disposition"] == second_result["disposition"] == FOLLOW_UP
    assert [
        x["display_key"] for x in stable_display_order([second_result, first_result])
    ] == sorted([one["result_id"], two["result_id"]])
    assert "rank" not in first_result and "position" not in first_result


def test_cross_cohort_and_incomplete_cohort_abstain() -> None:
    county = evaluate_surveillance_priority(_case("county-reported"))
    site = evaluate_surveillance_priority(_case("sampled-zero"))
    with pytest.raises(ValueError, match="cross-cohort"):
        stable_display_order([county, site])
    incomplete = deepcopy(_case("sampled-zero"))
    incomplete["collection_method"] = None
    assert evaluate_surveillance_priority(incomplete)["disposition"] == NOT_DEFENSIBLE
    assert county["comparison_cohort_id"] != site["comparison_cohort_id"]
    absent = _safe(SAMPLING, [])
    absent_result = evaluate_surveillance_priority(absent)
    assert absent_result["disposition"] == VERIFY
    assert absent_result["comparison_cohort_id"] is None
    assert absent_result["tie_group_id"] is None
    with pytest.raises(ValueError, match="cross-cohort"):
        stable_display_order([absent_result, absent_result])


def test_snapshot_revision_freshness_and_quality_are_explanatory() -> None:
    proven = evaluate_surveillance_priority(_case("county-proven-omission"))
    unproven = evaluate_surveillance_priority(_case("county-unproven-omission"))
    assert proven["disposition"] == FOLLOW_UP
    assert unproven["disposition"] == VERIFY
    bad_proof = deepcopy(_case("county-proven-omission"))
    bad_proof["source_scope"]["snapshot_evidence_id"] = None
    with pytest.raises(ValueError, match="snapshot proof"):
        evaluate_surveillance_priority(bad_proof)
    first = _case("sampled-zero")
    revised_row = _canonical(DENSITY)
    revised_row["source_record_id"] = "source-row-revision-two"
    revision = _safe(SAMPLING, [revised_row])
    assert (
        serialize_surveillance_priority(evaluate_surveillance_priority(first))["result_id"]
        != serialize_surveillance_priority(evaluate_surveillance_priority(revision))["result_id"]
    )
    flagged = deepcopy(first)
    flagged["reason_codes"] = [*first["reason_codes"], "STALE_OR_REVISION_SENSITIVE"]
    assert evaluate_surveillance_priority(flagged)["disposition"] == NO_GAP
    assert "STALE_OR_REVISION_SENSITIVE" in evaluate_surveillance_priority(flagged)["reason_codes"]


def test_site_geography_limits_never_become_county_priority() -> None:
    for status in ("MAPPED", "UNMAPPED", "AMBIGUOUS"):
        row = _canonical(DENSITY)
        row["county_relationship"]["mapping_status"] = status
        row["county_relationship"]["county_fips"] = "51003" if status == "MAPPED" else None
        safe = serialize_surveillance_priority(
            evaluate_surveillance_priority(_safe(SAMPLING, [row]))
        )
        assert safe["representativeness"] == "NOT_COUNTY_REPRESENTATIVE"
        assert safe["comparison_cohort"]["native_grain"] == "SITE_EVENT"
        assert safe["county_fips"] is None
        assert safe["county_relationship"]["county_fips"] == (
            "51003" if status == "MAPPED" else None
        )


def test_no_hidden_weights_and_separate_immutable_dev_store() -> None:
    assert (
        evaluate_surveillance_priority(_case("county-publisher-no-records"))["disposition"]
        == EXPLAIN
    )
    assert evaluate_surveillance_priority(_case("sampling-impractical"))["disposition"] == EXPLAIN
    assert (
        evaluate_surveillance_priority(_case("testing-positive-zero-detected"))["disposition"]
        == NO_GAP
    )
    result = evaluate_surveillance_priority(_case("sampled-zero"))
    safe = serialize_surveillance_priority(result)
    assert not any("weight" in key or "score" in key or "ordinal" in key for key in safe)
    assert "V102" in {item["version"] for item in migration_plan(DEV_DATABASE)}
    assert "V102" not in {item["version"] for item in migration_plan(PROD_DATABASE)}
    sql = next(item.source for item in load_migrations() if item.version == "V102")
    assert "PRESENTATION.SURVEILLANCE_PRIORITY_DERIVED_RESULTS" in sql
    for forbidden in (
        "SEMANTIC_OBSERVATIONS",
        "INFECTED_TICK_DERIVED_RESULTS",
        "SURVEILLANCE_COVERAGE_DERIVED_RESULTS",
        "OH_LYME_PROD",
    ):
        assert forbidden not in sql
    cursor = _MemoryCursor()
    result_id, state = stage_surveillance_priority(cursor, result)
    assert state == "STAGED"
    assert stage_surveillance_priority(cursor, result) == (result_id, "IDENTICAL_REPLAY")
    assert cursor.merges == 1
    cursor.rows[result_id] = "conflict"
    with pytest.raises(ValueError, match="conflicting"):
        stage_surveillance_priority(cursor, result)


def test_safe_examples_and_existing_county_score_boundary() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "docs/contracts/tick-surveillance/examples/surveillance-priority-v1-safe-examples.json"
    )
    examples = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(
        (path.parents[1] / "surveillance-priority-result-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema)
    assert examples["evidence_basis"] == "SYNTHETIC_FIXTURE"
    assert len(examples["examples"]) >= 10
    results = [item["result"] for item in examples["examples"]]
    assert {item["construct_id"] for item in results} == {
        COUNTY,
        SAMPLING,
        EFFORT,
        TESTING,
    }
    assert all(item["publication_status"] == "INTERNAL_DEV_ONLY" for item in results)
    assert all(not list(validator.iter_errors(item)) for item in results)
    assert all("artifact_id" not in str(item) for item in results)
    assert all("priority_score" not in item and "ordinal_position" not in item for item in results)
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "docs/contracts/semantic-release/governed-2026-09-15-manifest.json"
    )
    existing = load_manifest(manifest_path)
    frozen_score_defaults = deepcopy(existing.score_defaults)
    evaluate_surveillance_priority(_case("county-reported"))
    assert load_manifest(manifest_path).score_defaults == frozen_score_defaults
    assert "SURVEILLANCE_PRIORITY" not in str(frozen_score_defaults)


def test_serializer_rejects_spoofed_or_unsafe_projection() -> None:
    result = evaluate_surveillance_priority(_case("sampled-zero"))
    spoof = deepcopy(result)
    spoof["disposition"] = FOLLOW_UP
    with pytest.raises(ValueError, match="approved methodology"):
        serialize_surveillance_priority(spoof)
    unsafe = deepcopy(result)
    unsafe["coverage"]["site"]["source_site_id"] = "https://private.example/raw"
    with pytest.raises(ValueError, match="unsafe"):
        serialize_surveillance_priority(unsafe)


class _MemoryCursor:
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
