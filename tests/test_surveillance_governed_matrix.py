"""Registry-generated end-to-end #171/#172 scientific eligibility matrix."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from test_infected_tick_metrics import DENSITY, PREVALENCE
from test_surveillance_coverage import (
    _active_context,
    _canonical,
    _county,
    _county_context,
    _MemoryCursor,
)

from lyme_gap_atlas_data.surveillance_coverage import (
    COUNTY,
    EFFORT,
    SAMPLING,
    TESTING,
    evaluate_surveillance_coverage,
)
from lyme_gap_atlas_data.surveillance_coverage_result_store import stage_surveillance_coverage
from lyme_gap_atlas_data.surveillance_coverage_results import serialize_surveillance_coverage
from lyme_gap_atlas_data.surveillance_priority import evaluate_surveillance_priority
from lyme_gap_atlas_data.surveillance_priority_results import serialize_surveillance_priority
from lyme_gap_atlas_data.tick_normalization import load_registry

_FAMILIES = (
    ("VECTOR", COUNTY, "tick_taxon", "cdc-ixodes-county-status-2025"),
    ("PATHOGEN", COUNTY, "pathogen_target", "cdc-ixodes-pathogen-status-2025"),
    ("COLLECTION", SAMPLING, "tick_taxon", "DP1.10093.001"),
    ("COLLECTION", SAMPLING, "life_stage", "DP1.10093.001"),
    ("COLLECTION", SAMPLING, "collection_method", "DP1.10093.001"),
    ("COLLECTION", SAMPLING, "effort_unit", "DP1.10093.001"),
    ("EFFORT", EFFORT, "tick_taxon", "DP1.10093.001"),
    ("EFFORT", EFFORT, "life_stage", "DP1.10093.001"),
    ("EFFORT", EFFORT, "collection_method", "DP1.10093.001"),
    ("EFFORT", EFFORT, "effort_unit", "DP1.10093.001"),
    ("TESTING", TESTING, "pathogen_target", "DP1.10092.001"),
    ("TESTING", TESTING, "test_result", "DP1.10092.001"),
)
_KEYS = {
    "tick_taxon": ("tick_species", "taxon"),
    "life_stage": ("life_stage", "stage"),
    "collection_method": ("collection_method", "method"),
    "effort_unit": ("collection_effort_unit", "effort"),
    "pathogen_target": ("pathogen_name", "pathogen"),
    "test_result": ("test_result", "result"),
}
_POSITIVE = {
    COUNTY: {"REPORTED_STATUS", "PUBLISHER_NO_RECORDS"},
    SAMPLING: {"SAMPLED_EVENT"},
    EFFORT: {"DOCUMENTED_POSITIVE_EFFORT"},
    TESTING: {"DOCUMENTED_POSITIVE_TEST_DENOMINATOR"},
}


def _base(family: str) -> tuple[dict, dict]:
    if family == "VECTOR":
        return _county(), _county_context()
    if family == "PATHOGEN":
        row, context = _county(), _county_context()
        row["observation_type"] = "PATHOGEN_PRESENCE_STATUS"
        row["source_dataset_id"] = "cdc-ixodes-pathogen-status-2025"
        row["pathogen_name"] = "Borrelia mayonii"
        context["source_family"] = "CDC_PATHOGEN_COUNTY_STATUS"
        context["source_dataset_id"] = row["source_dataset_id"]
        rule = next(
            item
            for item in load_registry()["mappings"]
            if item["rule_id"] == "PATHOGEN_CDC_BMAYONII_V1"
        )
        row["normalization"]["mappings"] = {"pathogen": _entry(rule)}
        return row, context
    if family in {"COLLECTION", "EFFORT"}:
        return _canonical(DENSITY), _active_context()
    return _canonical(PREVALENCE), _active_context(True)


def _entry(rule: dict) -> dict:
    registry = load_registry()
    return {
        "source_value": rule["source_value"],
        "canonical_id": rule["canonical_id"],
        "canonical_label": rule["canonical_label"],
        "status": rule["status"],
        "mapping_rule_id": rule["rule_id"],
        "registry_id": registry["registry_id"],
        "registry_version": registry["registry_version"],
        "source_context": rule["source_context"],
    }


def _path(construct: str, row: dict, context: dict, *, dimension: str | None) -> tuple[dict, dict]:
    coverage = serialize_surveillance_coverage(
        evaluate_surveillance_coverage(
            construct,
            [row],
            source_context=context,
            county_fips="01001" if construct == COUNTY else None,
            dimension=dimension,
        ),
        evidence_basis="SYNTHETIC_FIXTURE",
    )
    priority = serialize_surveillance_priority(evaluate_surveillance_priority(coverage))
    return coverage, priority


def test_registry_generated_exact_source_matrix() -> None:
    registry = load_registry()
    canonical_values = sum(
        len(values) for field, values in registry["canonical_values"].items() if field in _KEYS
    )
    mapping_rules = [item for item in registry["mappings"] if item["field"] in _KEYS]
    combinations = 0
    unexpected_positive = unexpected_cohort = 0
    unexpected_rejected_positive = unexpected_rejected_cohort = 0
    for family, construct, field, dataset in _FAMILIES:
        source, context = _base(family)
        for value in registry["canonical_values"][field]:
            represented_results: list[tuple[dict, dict]] = []
            rules = [
                rule
                for rule in mapping_rules
                if rule["field"] == field
                and rule["canonical_id"] == value["id"]
                and rule["status"] == "APPROVED"
                and rule["source_context"]
                == {
                    "publisher": context["publisher"],
                    "dataset_id": dataset,
                    "source_version": context["source_version_id"],
                }
            ]
            expected = len(rules) >= 1 and not value.get("aggregate", False)
            observed_key, mapping_key = _KEYS[field]
            for representation in (value["id"], value["label"]):
                combinations += 1
                row = deepcopy(source)
                row[observed_key] = representation
                if field == "test_result":
                    row["ticks_positive"] = 1 if value["id"] == "DETECTED" else 0
                row["normalization"]["mappings"].pop(mapping_key, None)
                if rules:
                    row["normalization"]["mappings"][mapping_key] = _entry(rules[0])
                coverage, priority = _path(
                    construct,
                    row,
                    context,
                    dimension=representation if construct == COUNTY else None,
                )
                represented_results.append((coverage, priority))
                positive = coverage["state"] in _POSITIVE[construct]
                cohort = priority["comparison_cohort_id"] is not None
                unexpected_positive += bool(positive and not expected)
                unexpected_cohort += bool(cohort and not expected)
                unexpected_rejected_positive += bool(expected and not positive)
                unexpected_rejected_cohort += bool(expected and not cohort)
                if expected:
                    assert (
                        coverage["scientific_eligibility"][_attestation_index(construct, field)][
                            "canonical_id"
                        ]
                        == value["id"]
                    )
                else:
                    assert priority["tie_group_id"] is None
                # A foreign or absent mapping cannot be redeemed by a canonical label.
                for mode in ("absent", "foreign", "unsupported", "conflicting", "version_mismatch"):
                    bad = deepcopy(row)
                    bad_context = deepcopy(context)
                    mappings = bad["normalization"]["mappings"]
                    mappings.pop(mapping_key, None)
                    if mode == "foreign":
                        foreign = next(
                            (
                                item
                                for item in mapping_rules
                                if item["field"] == field
                                and item["source_context"]["dataset_id"] != dataset
                                and item["canonical_id"] == value["id"]
                            ),
                            None,
                        )
                        if foreign is None:
                            continue
                        mappings[mapping_key] = _entry(foreign)
                    elif mode == "conflicting" and rules:
                        mappings[mapping_key] = _entry(rules[0])
                        mappings[f"{mapping_key}_duplicate"] = _entry(rules[0])
                    elif mode == "conflicting":
                        continue
                    elif mode == "unsupported" and rules:
                        mappings[mapping_key] = _entry(rules[0])
                        mappings[mapping_key]["status"] = "UNSUPPORTED"
                    elif mode == "unsupported":
                        continue
                    elif mode == "version_mismatch":
                        bad_context["source_version_id"] = "UNAPPROVED-VERSION"
                    invalid, triage = _path(
                        construct,
                        bad,
                        bad_context,
                        dimension=representation if construct == COUNTY else None,
                    )
                    assert invalid["state"] not in _POSITIVE[construct]
                    assert triage["comparison_cohort_id"] is None
                    assert triage["tie_group_id"] is None
            if expected:
                (id_coverage, id_priority), (label_coverage, label_priority) = represented_results
                assert id_coverage["coverage_identity"] == label_coverage["coverage_identity"]
                assert id_coverage["result_revision"] == label_coverage["result_revision"]
                assert id_priority["comparison_cohort_id"] == label_priority["comparison_cohort_id"]
    print(
        "GOVERNED_MATRIX canonical_values=",
        canonical_values,
        " mapping_rules=",
        len(mapping_rules),
        " source_value_combinations=",
        combinations,
        " unexpected_positive=",
        unexpected_positive,
        " unexpected_cohort=",
        unexpected_cohort,
        " unexpected_rejected_positive=",
        unexpected_rejected_positive,
        " unexpected_rejected_cohort=",
        unexpected_rejected_cohort,
        sep="",
    )
    assert canonical_values == 30
    assert len(mapping_rules) == 31
    assert combinations == 124
    assert (
        unexpected_positive,
        unexpected_cohort,
        unexpected_rejected_positive,
        unexpected_rejected_cohort,
    ) == (0, 0, 0, 0)


def _attestation_index(construct: str, field: str) -> int:
    if construct == COUNTY:
        return 0
    order = (
        ("pathogen_target", "test_result")
        if construct == TESTING
        else ("tick_taxon", "life_stage", "collection_method", "effort_unit")
    )
    return order.index(field)


def test_every_relevant_mapping_rule_through_both_serializers() -> None:
    registry = load_registry()
    rules = [rule for rule in registry["mappings"] if rule["field"] in _KEYS]
    exercised = set()
    for rule in rules:
        dataset = rule["source_context"]["dataset_id"]
        field = rule["field"]
        if dataset == "cdc-ixodes-county-status-2025":
            family, construct = "VECTOR", COUNTY
        elif dataset == "cdc-ixodes-pathogen-status-2025":
            family, construct = (
                ("PATHOGEN", COUNTY) if field == "pathogen_target" else ("VECTOR", COUNTY)
            )
        elif dataset == "DP1.10093.001":
            family, construct = "COLLECTION", SAMPLING
        else:
            family, construct = "TESTING", TESTING
        row, context = _base(family)
        observed_key, mapping_key = _KEYS[field]
        represented = rule["canonical_id"] or rule["source_value"]
        row[observed_key] = represented
        row["normalization"]["mappings"][mapping_key] = _entry(rule)
        if field == "test_result":
            row["ticks_positive"] = 1 if represented == "DETECTED" else 0
        coverage, priority = _path(
            construct,
            row,
            context,
            dimension=represented if construct == COUNTY else None,
        )
        expected = False
        if dataset == context["source_dataset_id"] and rule["status"] == "APPROVED":
            canonical = next(
                (
                    item
                    for item in registry["canonical_values"][field]
                    if item["id"] == rule["canonical_id"]
                ),
                None,
            )
            expected = canonical is not None and not canonical.get("aggregate", False)
        assert (coverage["state"] in _POSITIVE[construct]) == expected, rule["rule_id"]
        assert (priority["comparison_cohort_id"] is not None) == expected, rule["rule_id"]
        exercised.add(rule["rule_id"])
    print(f"GOVERNED_RULE_PROBES executed={len(exercised)}")
    assert len(exercised) == 31


def test_evidence_basis_distinguishes_immutable_realizations() -> None:
    row, context = _base("COLLECTION")
    result = evaluate_surveillance_coverage(SAMPLING, [row], source_context=context)
    synthetic = serialize_surveillance_coverage(result, evidence_basis="SYNTHETIC_FIXTURE")
    replay = serialize_surveillance_coverage(
        result, evidence_basis="CURRENT_CODE_SOURCE_BACKED_REPLAY"
    )
    assert synthetic["coverage_identity"] == replay["coverage_identity"]
    assert synthetic["result_id"] != replay["result_id"]
    assert synthetic["result_revision"] != replay["result_revision"]
    synthetic_priority = serialize_surveillance_priority(evaluate_surveillance_priority(synthetic))
    replay_priority = serialize_surveillance_priority(evaluate_surveillance_priority(replay))
    assert synthetic_priority["result_id"] != replay_priority["result_id"]
    cursor = _MemoryCursor()
    assert (
        stage_surveillance_coverage(cursor, result, evidence_basis="SYNTHETIC_FIXTURE")[1]
        == "STAGED"
    )
    assert (
        stage_surveillance_coverage(cursor, result, evidence_basis="SYNTHETIC_FIXTURE")[1]
        == "IDENTICAL_REPLAY"
    )
    assert (
        stage_surveillance_coverage(
            cursor, result, evidence_basis="CURRENT_CODE_SOURCE_BACKED_REPLAY"
        )[1]
        == "STAGED"
    )


def test_period_missingness_testing_scope_and_safe_paths_fail_closed() -> None:
    row, context = _base("COLLECTION")
    point = evaluate_surveillance_coverage(SAMPLING, [row], source_context=context)
    period_row = deepcopy(row)
    period_row["temporal_semantics"] = "PERIOD"
    period = evaluate_surveillance_coverage(SAMPLING, [period_row], source_context=context)
    assert period["state"] == "UNKNOWN"
    assert period["coverage_identity"] != point["coverage_identity"]
    period_safe = serialize_surveillance_coverage(period, evidence_basis="SYNTHETIC_FIXTURE")
    assert period_safe["temporal_semantics"] == "PERIOD"
    assert evaluate_surveillance_priority(period_safe)["comparison_cohort_id"] is None

    conflict = deepcopy(row)
    conflict["missingness"] = {"collection_effort_value": "UNKNOWN"}
    conflicted, priority = _path(SAMPLING, conflict, context, dimension=None)
    assert conflicted["state"] == "UNKNOWN"
    assert conflicted["missingness"]["collection_effort_value"] == "UNKNOWN"
    assert "CONFLICTING_EFFORT_MISSINGNESS" in conflicted["reason_codes"]
    assert priority["comparison_cohort_id"] is None

    testing, test_context = _base("TESTING")
    for field, value in (("testing_scope", "MIXED"), ("testing_scope", None)):
        invalid = deepcopy(testing)
        invalid[field] = value
        safe, priority = _path(TESTING, invalid, test_context, dimension=None)
        assert safe["state"] == "UNKNOWN"
        assert safe["testing_scope_attestation"] is None
        assert priority["comparison_cohort_id"] is None
    missing_id = deepcopy(testing)
    missing_id["sampling_event"]["source_testing_id"] = None
    safe, priority = _path(TESTING, missing_id, test_context, dimension=None)
    assert safe["testing_scope_attestation"] is None
    assert priority["comparison_cohort_id"] is None

    secret = deepcopy(row)
    secret["source_record_id"] = r"C:\secrets\private-key.p8"
    with pytest.raises(ValueError, match="unsafe coverage output value"):
        _path(SAMPLING, secret, context, dimension=None)
    opaque = deepcopy(row)
    opaque["source_record_id"] = "region/row-1"
    assert _path(SAMPLING, opaque, context, dimension=None)[0]["state"] == "SAMPLED_EVENT"


def test_source_only_county_evidence_is_safe_and_incomparable() -> None:
    context = _county_context()
    invalid_canonical = _county()
    invalid_canonical.pop("county_fips")
    with pytest.raises(ValueError, match="source-only evidence"):
        evaluate_surveillance_coverage(
            COUNTY,
            [invalid_canonical],
            source_context=context,
            county_fips=None,
            dimension="IXODES_SCAPULARIS",
        )
    evidence = {
        "source_record_id": "source-row-unmapped",
        "reported_geography": "Publisher area 7",
        "source_geography_type": "COUNTY_NAME",
        "mapping_status": "UNMAPPED",
        "mapping_reason": "NO_APPROVED_CANONICAL_MATCH",
        "scientific_dimension": "Ixodes scapularis",
        "retrieved_at": "2026-09-23T00:00:00Z",
    }
    result = evaluate_surveillance_coverage(
        COUNTY,
        [],
        source_context=context,
        county_fips=None,
        dimension="IXODES_SCAPULARIS",
        source_only_evidence=evidence,
    )
    safe = serialize_surveillance_coverage(result, evidence_basis="SYNTHETIC_FIXTURE")
    assert safe["state"] == "UNKNOWN"
    assert safe["county_fips"] is None
    assert safe["source_only_evidence"]["contract_version"] == (
        "surveillance-source-only-county-evidence-v1"
    )
    assert safe["source_only_evidence"]["linked_coverage_identity"] == safe["coverage_identity"]
    priority = serialize_surveillance_priority(evaluate_surveillance_priority(safe))
    assert priority["source_only_evidence"] == safe["source_only_evidence"]
    assert priority["comparison_cohort_id"] is None
    assert priority["tie_group_id"] is None


def test_safe_v2_contract_schemas_accept_resolved_and_source_only_results() -> None:
    contracts = Path(__file__).resolve().parents[1] / "docs/contracts/tick-surveillance"
    coverage_schema = json.loads(
        (contracts / "surveillance-coverage-result-v2.schema.json").read_text()
    )
    priority_schema = json.loads(
        (contracts / "surveillance-priority-result-v2.schema.json").read_text()
    )
    source_only_schema = json.loads(
        (contracts / "surveillance-source-only-county-evidence-v1.schema.json").read_text()
    )
    row, context = _base("COLLECTION")
    coverage, priority = _path(SAMPLING, row, context, dimension=None)
    assert list(Draft202012Validator(coverage_schema).iter_errors(coverage)) == []
    assert list(Draft202012Validator(priority_schema).iter_errors(priority)) == []
    county = serialize_surveillance_coverage(
        evaluate_surveillance_coverage(
            COUNTY,
            [],
            source_context=_county_context(),
            county_fips=None,
            dimension="IXODES_SCAPULARIS",
            source_only_evidence={
                "source_record_id": "source-unmapped",
                "reported_geography": "Publisher area 7",
                "source_geography_type": "COUNTY_NAME",
                "mapping_status": "UNMAPPED",
                "mapping_reason": "NO_APPROVED_CANONICAL_MATCH",
                "scientific_dimension": "Ixodes scapularis",
            },
        ),
        evidence_basis="SYNTHETIC_FIXTURE",
    )
    assert list(Draft202012Validator(coverage_schema).iter_errors(county)) == []
    assert (
        list(Draft202012Validator(source_only_schema).iter_errors(county["source_only_evidence"]))
        == []
    )
    county_priority = serialize_surveillance_priority(evaluate_surveillance_priority(county))
    assert list(Draft202012Validator(priority_schema).iter_errors(county_priority)) == []


def test_governed_source_vintage_tuples_are_unique_and_registry_bound() -> None:
    contracts = Path(__file__).resolve().parents[1] / "docs/contracts/tick-surveillance"
    policy = json.loads((contracts / "surveillance-scientific-eligibility-v1.json").read_text())
    registry = load_registry()
    assert policy["model_version"] == "surveillance-scientific-eligibility-v1"
    tuples = policy["approved_tuples"]
    identities = [
        tuple(
            row[key]
            for key in (
                "construct_id",
                "source_family",
                "publisher",
                "source_dataset_id",
                "source_version_id",
                "source_vintage",
            )
        )
        for row in tuples
    ]
    assert len(identities) == len(set(identities)) == 5
    for row in tuples:
        assert {
            "publisher": row["publisher"],
            "dataset_id": row["source_dataset_id"],
            "source_version": row["source_version_id"],
        } in registry["scope"]["approved_sources"]
        assert row["source_vintage"] not in {"UNKNOWN", "MIXED", "AGGREGATE", ""}


@pytest.mark.parametrize(
    ("field", "changed_key", "changed_value"),
    [
        ("stage", "canonical_id", "ADULT"),
        ("stage", "status", "UNKNOWN"),
        ("taxon", "status", "UNKNOWN"),
        (
            "stage",
            "source_context",
            {
                "publisher": "CDC ArboNET Tick Module",
                "dataset_id": "cdc-ixodes-county-status-2025",
                "source_version": "2025",
            },
        ),
    ],
)
def test_same_rule_id_with_conflicting_mapping_proof_changes_result(
    field: str, changed_key: str, changed_value: object
) -> None:
    row, context = _base("COLLECTION")
    baseline, baseline_priority = _path(SAMPLING, row, context, dimension=None)
    altered = deepcopy(row)
    altered["normalization"]["mappings"][field][changed_key] = changed_value
    coverage, priority = _path(SAMPLING, altered, context, dimension=None)
    assert coverage["state"] != "SAMPLED_EVENT"
    assert coverage["result_id"] != baseline["result_id"]
    assert priority["result_id"] != baseline_priority["result_id"]
    assert priority["comparison_cohort_id"] is None
    assert priority["tie_group_id"] is None


@pytest.mark.parametrize("vintage", ["UNKNOWN", "MIXED", "AGGREGATE", "made-up-2026"])
def test_unlisted_vintage_never_retains_positive_state_or_cohort(vintage: str) -> None:
    row, context = _base("COLLECTION")
    context["source_vintage"] = vintage
    coverage, priority = _path(SAMPLING, row, context, dimension=None)
    assert coverage["state"] == "UNAVAILABLE"
    assert "SOURCE_VINTAGE_TUPLE_UNPROVEN" in coverage["reason_codes"]
    assert priority["comparison_cohort_id"] is None
    assert priority["tie_group_id"] is None
