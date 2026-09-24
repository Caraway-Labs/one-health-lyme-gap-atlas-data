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
from lyme_gap_atlas_data.tick_normalization import load_registry

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
        assert safe["county_relationship"]["mapping_status"] == status
        assert safe["source_geography"] == _safe(SAMPLING, [row])["source_geography"]
        assert safe["site"]["source_site_id"] == row["sampling_site"]["source_site_id"]
        assert safe["tick_species"] == row["tick_species"]
        assert safe["life_stage"] == row["life_stage"]
        assert safe["collection_method"] == row["collection_method"]


@pytest.mark.parametrize(
    ("field", "alternate"),
    [
        ("tick_species", "Ixodes pacificus"),
        ("life_stage", "Adult"),
        ("collection_method", "Flag cloth"),
        ("date", "2016-06-01"),
    ],
)
def test_collection_comparability_dimensions_separate_cohorts(field: str, alternate: str) -> None:
    first = _case("sampled-zero")
    second = deepcopy(first)
    second[field] = alternate
    a = evaluate_surveillance_priority(first)
    b = evaluate_surveillance_priority(second)
    assert a["comparison_cohort_id"] is not None
    assert b["comparison_cohort_id"] is not None
    assert a["comparison_cohort_id"] != b["comparison_cohort_id"]
    assert (
        serialize_surveillance_priority(a)["result_id"]
        != serialize_surveillance_priority(b)["result_id"]
    )
    with pytest.raises(ValueError, match="cross-cohort"):
        stable_display_order([a, b])


def test_source_version_testing_target_and_scope_separate_cohorts() -> None:
    first = _case("testing-positive-zero-detected")
    baseline = evaluate_surveillance_priority(first)
    safe = serialize_surveillance_priority(baseline)
    assert safe["pathogen_name"] == first["pathogen_name"]
    assert safe["testing_scope"] == "INDIVIDUAL_PATHOGEN_TEST"
    assert safe["source_geography"] == first["source_geography"]
    for field, value in (("pathogen_name", "Other target"), ("testing_scope", "OTHER_SCOPE")):
        changed = deepcopy(first)
        changed[field] = value
        different = evaluate_surveillance_priority(changed)
        assert different["comparison_cohort_id"] is None
        assert different["disposition"] == NOT_DEFENSIBLE
    for field in ("source_dataset_id", "source_version_id", "source_vintage"):
        changed = deepcopy(first)
        changed["source_scope"][field] = "different-version"
        assert (
            evaluate_surveillance_priority(changed)["comparison_cohort_id"]
            != baseline["comparison_cohort_id"]
        )
    assert (
        evaluate_surveillance_priority({**first, "life_stage": None})["comparison_cohort_id"]
        == baseline["comparison_cohort_id"]
    )
    incompatible_time = evaluate_surveillance_priority(
        {**first, "temporal_semantics": "CUMULATIVE_THROUGH_DATE"}
    )
    assert incompatible_time["comparison_cohort_id"] is None
    assert incompatible_time["disposition"] == NOT_DEFENSIBLE


@pytest.mark.parametrize("field", ["tick_species", "life_stage", "collection_method"])
def test_missing_collection_dimension_fails_closed(field: str) -> None:
    changed = deepcopy(_case("sampled-zero"))
    changed[field] = None
    result = evaluate_surveillance_priority(changed)
    assert result["comparison_cohort_id"] is None
    assert result["disposition"] == NOT_DEFENSIBLE


@pytest.mark.parametrize("construct", [SAMPLING, EFFORT])
@pytest.mark.parametrize(
    "method",
    [
        None,
        "",
        "UNKNOWN",
        "AMBIGUOUS",
        "UNRESOLVED",
        "NOT_REPORTED",
        "NOT_APPLICABLE",
        "UNSUPPORTED",
    ],
)
def test_unresolved_collection_method_has_no_scientific_identity(
    construct: str, method: str | None
) -> None:
    coverage = deepcopy(_case("sampled-zero" if construct == SAMPLING else "effort-positive"))
    coverage["collection_method"] = method
    result = evaluate_surveillance_priority(coverage)
    safe = serialize_surveillance_priority(result)
    assert safe["comparison_cohort"] is None
    assert safe["comparison_cohort_id"] is None
    assert safe["tie_group_id"] is None
    assert safe["disposition"] == NOT_DEFENSIBLE
    assert "COMPARISON_COHORT_UNPROVEN" in safe["reason_codes"]
    assert safe["result_id"].startswith("surveillance-priority-result:v1:")
    assert safe["result_revision"]


@pytest.mark.parametrize("field", ["tick_species", "life_stage"])
@pytest.mark.parametrize(
    "value",
    [
        "UNKNOWN",
        "AMBIGUOUS",
        "UNRESOLVED",
        "MIXED",
        "NOT_REPORTED",
        "Not reported",
        "NOT_APPLICABLE",
    ],
)
def test_unresolved_collection_taxon_and_stage_fail_closed(field: str, value: str) -> None:
    coverage = deepcopy(_case("sampled-zero"))
    coverage[field] = value
    assert evaluate_surveillance_priority(coverage)["comparison_cohort_id"] is None


@pytest.mark.parametrize("case", ["sampled-zero", "testing-positive-zero-detected"])
@pytest.mark.parametrize("field", ["source_dataset_id", "source_version_id", "source_vintage"])
@pytest.mark.parametrize(
    "value", [None, "", "UNKNOWN", "AMBIGUOUS", "MIXED", "AGGREGATE", "MIXED/AGGREGATE"]
)
def test_unresolved_source_context_fails_closed(case: str, field: str, value: str | None) -> None:
    coverage = deepcopy(_case(case))
    coverage["source_scope"][field] = value
    assert evaluate_surveillance_priority(coverage)["comparison_cohort_id"] is None


@pytest.mark.parametrize("field", ["pathogen_name", "testing_scope"])
@pytest.mark.parametrize("value", [None, "UNKNOWN", "AMBIGUOUS", "UNRESOLVED", "MIXED/AGGREGATE"])
def test_unresolved_testing_context_fails_closed(field: str, value: str | None) -> None:
    coverage = deepcopy(_case("testing-positive-zero-detected"))
    coverage[field] = value
    result = evaluate_surveillance_priority(coverage)
    assert result["comparison_cohort_id"] is None
    assert result["tie_group_id"] is None
    assert result["disposition"] == NOT_DEFENSIBLE


@pytest.mark.parametrize("case", ["sampled-zero", "testing-positive-zero-detected"])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("native_grain", None),
        ("native_grain", "UNKNOWN"),
        ("native_grain", "COUNTY"),
        ("native_grain", "MIXED/AGGREGATE"),
        ("temporal_semantics", "UNKNOWN"),
        ("temporal_semantics", "MIXED/AGGREGATE"),
        ("temporal_semantics", "CUMULATIVE_THROUGH_DATE"),
        ("date", "AMBIGUOUS"),
    ],
)
def test_unresolved_grain_or_time_fails_closed(case: str, field: str, value: str | None) -> None:
    coverage = deepcopy(_case(case))
    coverage[field] = value
    assert evaluate_surveillance_priority(coverage)["comparison_cohort_id"] is None


def test_mixed_vintage_preserves_safe_coverage_and_deterministic_identity() -> None:
    coverage = serialize_surveillance_coverage(
        evaluate_surveillance_coverage(
            SAMPLING,
            [_canonical(DENSITY)],
            source_context={**_active_context(), "source_vintage": "MIXED/AGGREGATE"},
        ),
        evidence_basis="SYNTHETIC_FIXTURE",
    )
    result = evaluate_surveillance_priority(coverage)
    safe = serialize_surveillance_priority(result)
    assert safe == serialize_surveillance_priority(evaluate_surveillance_priority(coverage))
    assert safe["source_scope"]["source_vintage"] == "MIXED/AGGREGATE"
    assert safe["comparison_cohort_id"] is None
    assert safe["tie_group_id"] is None
    assert safe["result_id"].startswith("surveillance-priority-result:v1:")
    assert safe["disposition"] == NOT_DEFENSIBLE
    assert "COMPARISON_COHORT_UNPROVEN" in safe["reason_codes"]
    assert safe["coverage_result_id"] == coverage["result_id"]


def test_unresolved_method_real_coverage_to_priority_safe_result() -> None:
    row = _canonical(DENSITY)
    row["collection_method"] = "UNKNOWN"
    coverage = _safe(SAMPLING, [row])
    assert coverage["state"] == "UNKNOWN"
    assert "COLLECTION_METHOD_UNRESOLVED" in coverage["reason_codes"]
    result = evaluate_surveillance_priority(coverage)
    safe = serialize_surveillance_priority(result)
    assert safe["coverage_state"] == "UNKNOWN"
    assert safe["collection_method"] == "UNKNOWN"
    assert safe["safe_lineage"] == coverage["safe_lineage"]
    assert safe["quality"] == coverage["quality"]
    assert safe["source_geography"] == coverage["source_geography"]
    assert safe["comparison_cohort"] is None
    assert safe["comparison_cohort_id"] is None
    assert safe["tie_group_id"] is None
    assert safe["disposition"] == VERIFY
    assert "COLLECTION_METHOD_UNRESOLVED" in safe["reason_codes"]
    assert "COMPARISON_COHORT_UNPROVEN" in safe["reason_codes"]
    assert safe["result_id"] and safe["result_revision"]
    assert "priority_score" not in safe and "ordinal_position" not in safe


@pytest.mark.parametrize(
    ("family", "dataset", "field", "valid", "invalid"),
    [
        (
            "CDC_IXODES_COUNTY_STATUS",
            "cdc_tick_ixodes_county_status",
            "tick_species",
            "Ixodes scapularis",
            ("Ixodes scapularis or Ixodes pacificus", "UNKNOWN", "Borrelia mayonii"),
        ),
        (
            "CDC_PATHOGEN_COUNTY_STATUS",
            "cdc_tick_ixodes_pathogen_status",
            "pathogen_name",
            "Borrelia mayonii",
            ("UNKNOWN", "MIXED", "Ixodes scapularis"),
        ),
    ],
)
def test_county_scientific_dimension_requires_source_compatible_registry_value(
    family: str, dataset: str, field: str, valid: str, invalid: tuple[str, ...]
) -> None:
    context = {**_county_context(), "source_family": family, "source_dataset_id": dataset}
    row = _county()
    row.update(
        observation_type="VECTOR_PRESENCE_STATUS"
        if field == "tick_species"
        else "PATHOGEN_PRESENCE_STATUS",
        source_dataset_id=dataset,
    )
    row["tick_species"] = (
        "Ixodes scapularis or Ixodes pacificus" if field == "pathogen_name" else valid
    )
    row[field] = valid
    coverage = serialize_surveillance_coverage(
        evaluate_surveillance_coverage(
            COUNTY, [row], source_context=context, county_fips="01001", dimension=valid
        ),
        evidence_basis="SYNTHETIC_FIXTURE",
    )
    assert evaluate_surveillance_priority(coverage)["comparison_cohort_id"] is not None
    for dimension in invalid:
        changed = deepcopy(coverage)
        changed["dimension"] = dimension
        safe = serialize_surveillance_priority(evaluate_surveillance_priority(changed))
        assert safe["dimension"] == dimension
        assert safe["comparison_cohort_id"] is None
        assert safe["tie_group_id"] is None
        assert safe["result_id"] and safe["result_revision"]
        assert "COMPARISON_COHORT_UNPROVEN" in safe["reason_codes"]
    wrong_source = deepcopy(coverage)
    wrong_source["source_scope"]["source_dataset_id"] = "other-dataset"
    assert evaluate_surveillance_priority(wrong_source)["comparison_cohort_id"] is None


def test_aggregate_county_observation_preserves_full_safe_path() -> None:
    aggregate = "Ixodes scapularis or Ixodes pacificus"
    row = _county()
    row["tick_species"] = aggregate
    coverage = serialize_surveillance_coverage(
        evaluate_surveillance_coverage(
            COUNTY,
            [row],
            source_context=_county_context(),
            county_fips="01001",
            dimension=aggregate,
        ),
        evidence_basis="SYNTHETIC_FIXTURE",
    )
    safe = serialize_surveillance_priority(evaluate_surveillance_priority(coverage))
    assert coverage["dimension"] == safe["dimension"] == aggregate
    assert safe == serialize_surveillance_priority(evaluate_surveillance_priority(coverage))
    assert safe["result_id"] and safe["result_revision"]
    assert safe["disposition"] == NOT_DEFENSIBLE
    assert "COMPARISON_COHORT_UNPROVEN" in safe["reason_codes"]
    assert safe["comparison_cohort_id"] is None
    assert safe["tie_group_id"] is None
    control = deepcopy(row)
    control["tick_species"] = "Ixodes scapularis"
    control_coverage = serialize_surveillance_coverage(
        evaluate_surveillance_coverage(
            COUNTY,
            [control],
            source_context=_county_context(),
            county_fips="01001",
            dimension="Ixodes scapularis",
        ),
        evidence_basis="SYNTHETIC_FIXTURE",
    )
    assert (
        serialize_surveillance_priority(evaluate_surveillance_priority(control_coverage))[
            "comparison_cohort_id"
        ]
        is not None
    )


@pytest.mark.parametrize(
    ("field", "registry_dataset"),
    [
        ("tick_taxon", "cdc-ixodes-county-status-2025"),
        ("pathogen_target", "cdc-ixodes-pathogen-status-2025"),
    ],
)
def test_governed_county_values_require_source_mapping_and_nonaggregate_identity(
    field: str, registry_dataset: str
) -> None:
    registry = load_registry()
    coverage = deepcopy(_case("county-reported"))
    if field == "pathogen_target":
        coverage["source_scope"]["source_family"] = "CDC_PATHOGEN_COUNTY_STATUS"
        coverage["source_scope"]["source_dataset_id"] = "cdc_tick_ixodes_pathogen_status"
    for entry in registry["canonical_values"][field]:
        approved = [
            rule
            for rule in registry["mappings"]
            if rule["field"] == field
            and rule["canonical_id"] == entry["id"]
            and rule["status"] == "APPROVED"
            and rule["source_context"]["dataset_id"] == registry_dataset
            and rule["source_context"]["source_version"] == "2025"
        ]
        expected = len(approved) == 1 and not entry.get("aggregate")
        for representation in (entry["id"], entry["label"]):
            coverage["dimension"] = representation
            result = evaluate_surveillance_priority(coverage)
            assert (result["comparison_cohort_id"] is not None) == expected
            if not expected:
                assert result["tie_group_id"] is None
    for unsupported in ("free text", "UNKNOWN", "MIXED"):
        coverage["dimension"] = unsupported
        assert evaluate_surveillance_priority(coverage)["comparison_cohort_id"] is None


def test_bounded_dev_county_aggregate_shape_is_safe_without_source_rows() -> None:
    context = _county_context()
    aggregate = "Ixodes scapularis or Ixodes pacificus"
    coverage = serialize_surveillance_coverage(
        evaluate_surveillance_coverage(
            COUNTY, [], source_context=context, county_fips="01001", dimension=aggregate
        ),
        evidence_basis="SYNTHETIC_FIXTURE",
    )
    result = evaluate_surveillance_priority(coverage)
    safe = serialize_surveillance_priority(result)
    assert safe["dimension"] == aggregate
    assert safe["comparison_cohort_id"] is None
    assert safe["tie_group_id"] is None
    assert "COMPARISON_COHORT_UNPROVEN" in safe["reason_codes"]
    cursor = _MemoryCursor()
    result_id, first = stage_surveillance_priority(cursor, result)
    assert first == "STAGED"
    assert stage_surveillance_priority(cursor, result) == (result_id, "IDENTICAL_REPLAY")


def test_safe_projection_excludes_restricted_fields() -> None:
    result = evaluate_surveillance_priority(_case("sampled-zero"))
    result["coverage"]["artifact_uri"] = "secret"
    result["coverage"]["credential"] = "secret"
    safe = serialize_surveillance_priority(result)
    assert "artifact_uri" not in str(safe)
    assert "credential" not in str(safe)


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
