"""DATA429 source-rule and canonical/semantic/consumer compatibility fixtures."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from test_semantic_source_mappings import REGISTRY, _case

from lyme_gap_atlas_data.semantic_domain import meaning_signature
from lyme_gap_atlas_data.semantic_metadata import metadata_revision_id
from lyme_gap_atlas_data.semantic_source_mappings import SemanticMappingError, map_record
from lyme_gap_atlas_data.surveillance_evidence import STATES as V1_STATES
from lyme_gap_atlas_data.surveillance_evidence_mapping import (
    STATES,
    map_surveillance_evidence,
    project_surveillance_evidence,
)
from lyme_gap_atlas_data.tick_normalization import normalize_value


def case(identity, value=None):
    record, metadata, authority = _case(identity)
    if identity in {"county_tick_status", "county_pathogen_status"}:
        record["temporal"]["date"] = "2025-12-31"
    if identity == "neon_pathogen_test":
        record["geography"]["site_id"] = "BLAN"
        record["source_output"]["sampling_site"]["source_site_id"] = "BLAN"
        record["temporal"]["date"] = "2016-05-01"
        record["source_output"]["surveillance_period_start"] = "2016-05-01"
        record["source_output"]["surveillance_period_end"] = "2016-05-01"
    if value is not None:
        record["value"] = value
        record["source_output"][REGISTRY[identity]["field"]] = value
        record["value_state"] = (
            "ZERO" if value == 0 else ("NO_RECORDS" if value == "No records" else "OBSERVED")
        )
        if record["value_state"] not in metadata["measure"]["allowed_value_states"]:
            metadata["measure"]["allowed_value_states"].append(record["value_state"])
            metadata["allowed_value_states"] = list(metadata["measure"]["allowed_value_states"])
            metadata["meaning_signature"] = meaning_signature(metadata["measure"])
            metadata["revision_id"] = metadata_revision_id(metadata)
    return record, metadata, authority


def negative():
    record, metadata, authority = case("neon_pathogen_test", 0)
    output = record["source_output"]
    output["sampling_event"].update(
        source_testing_id="fixture-test", source_sample_id="fixture-tick"
    )
    output["quality_flags"] = []
    output.update(
        tick_species="Ixodes scapularis",
        method_version="tick-surveillance-v1.2",
        pathogen_name="Borrelia burgdorferi sensu lato",
        reported_or_derived="HARMONIZED",
        source_geography={
            "source_location_id": "BLAN",
            "geography_kind": "SITE",
            "coordinate_reference_system": None,
            "longitude": None,
            "latitude": None,
            "spatial_uncertainty_meters": None,
        },
    )
    output["county_relationship"].update(
        mapping_status="UNMAPPED",
        mapping_method=None,
        mapping_version=None,
        mapping_artifact_id=None,
        representativeness="NOT_COUNTY_REPRESENTATIVE",
    )
    output["normalization"].update(
        registry_id="tick-surveillance-normalization-v1", registry_version="1.0.4"
    )
    proof = normalize_value(
        field="test_result",
        source_value="negative",
        publisher="NSF NEON",
        dataset_id="DP1.10092.001",
        source_version="RELEASE-2026",
    ).as_contract_value()
    output["normalization"]["mappings"][proof["mapping_rule_id"]] = proof
    return record, metadata, authority


def run(data):
    return map_surveillance_evidence(*data, REGISTRY, fixture_mode=True)


@pytest.mark.parametrize(
    ("identity", "value", "state"),
    [
        ("county_tick_status", "Established", "established"),
        ("county_tick_status", "No records", "no_qualifying_record"),
        ("county_pathogen_status", "No records", "no_qualifying_record"),
        ("county_tick_status", "Reported", "unknown"),
        ("county_pathogen_status", "Present", "unknown"),
    ],
)
def test_publisher_state_rules_preserve_legacy_semantics(identity, value, state):
    data = case(identity, value)
    before = copy.deepcopy(data)
    legacy = map_record(*data, REGISTRY, fixture_mode=True)
    result = run(data)
    assert result["surveillance_evidence"]["state"] == state
    assert {key: result[key] for key in legacy} == legacy
    assert data == before


def test_v2_matches_current_issue_without_renaming_historical_fixture_v1():
    assert "detected_below_establishment" in STATES
    assert "detected_below_establishment_criteria" in V1_STATES
    assert len(STATES) == 5


def test_negative_test_requires_actual_source_result_and_remains_site_native():
    result = run(negative())
    assert result["surveillance_evidence"]["state"] == "sampled_not_detected"
    assert result["observation"]["value_state"] == "ZERO"
    assert result["observation"]["geography"]["representativeness"] == "NOT_COUNTY_REPRESENTATIVE"


def validate_canonical(data):
    schema = json.loads(
        (
            Path(__file__).parents[1]
            / "docs/contracts/tick-surveillance/canonical-tick-surveillance-v1.schema.json"
        ).read_text()
    )
    Draft202012Validator(schema).validate(data[0]["source_output"])


@pytest.mark.parametrize("source_value", ["positive", "Positive"])
def test_conflicting_valid_result_proofs_abstain(source_value):
    data = negative()
    proof = normalize_value(
        field="test_result",
        source_value=source_value,
        publisher="NSF NEON",
        dataset_id="DP1.10092.001",
        source_version="RELEASE-2026",
    ).as_contract_value()
    data[0]["source_output"]["normalization"]["mappings"][proof["mapping_rule_id"]] = proof
    validate_canonical(data)
    before = copy.deepcopy(data)
    legacy = map_record(*data, REGISTRY, fixture_mode=True)
    result = run(data)
    assert result["surveillance_evidence"]["state"] == "unknown"
    assert {key: result[key] for key in legacy} == legacy
    assert data == before


@pytest.mark.parametrize("result", ["DETECTED", "positive", "UNKNOWN", None])
def test_explicit_incompatible_test_result_abstains(result):
    data = negative()
    data[0]["source_output"]["test_result"] = result
    validate_canonical(data)
    assert run(data)["surveillance_evidence"]["state"] == "unknown"


@pytest.mark.parametrize("scope", ["MIXED", "AGGREGATE", "UNKNOWN", None])
def test_explicit_nonindividual_testing_scope_abstains(scope):
    data = negative()
    data[0]["source_output"]["testing_scope"] = scope
    validate_canonical(data)
    assert run(data)["surveillance_evidence"]["state"] == "unknown"


def test_explicit_consistent_individual_negative_and_legacy_negative_remain_valid():
    data = negative()
    validate_canonical(data)
    assert run(data)["surveillance_evidence"]["state"] == "sampled_not_detected"
    data[0]["source_output"].update(
        testing_scope="INDIVIDUAL_PATHOGEN_TEST", test_result="NOT_DETECTED"
    )
    validate_canonical(data)
    assert run(data)["surveillance_evidence"]["state"] == "sampled_not_detected"


@pytest.mark.parametrize(
    "change",
    [
        lambda o: o.pop("quality_flags"),
        lambda o: o.update(quality_flags=[{"canonical_id": "SAMPLING_IMPRACTICAL"}]),
        lambda o: o["sampling_event"].pop("source_testing_id"),
        lambda o: o["sampling_event"].pop("source_sample_id"),
        lambda o: o["normalization"]["mappings"].pop("RESULT_NEON_NEGATIVE_V1"),
        lambda o: o["normalization"]["mappings"]["RESULT_NEON_NEGATIVE_V1"].update(
            source_context={"publisher": "passive-submission"}
        ),
    ],
)
def test_incomplete_or_incompatible_sampling_proof_abstains(change):
    data = negative()
    change(data[0]["source_output"])
    assert run(data)["surveillance_evidence"]["state"] == "unknown"


@pytest.mark.parametrize("identity", ["neon_collection", "neon_pathogen_test"])
def test_generic_zero_without_sampling_or_result_proof_does_not_classify(identity):
    assert run(case(identity, 0))["surveillance_evidence"]["state"] == "unknown"


def test_missing_record_cannot_become_no_records_and_mixed_sources_fail():
    data = case("county_tick_status")
    data[0]["source_output"].pop(REGISTRY["county_tick_status"]["field"])
    with pytest.raises(SemanticMappingError):
        run(data)
    data = negative()
    data[0]["edges"][0]["source_version_id"] = "fixture-other-source"
    with pytest.raises(SemanticMappingError):
        run(data)


def test_stale_scope_is_retained_and_changed_canonical_proof_changes_evidence_revision():
    data = case("county_tick_status", "Established")
    first = run(data)
    assert first["observation"]["temporal"] == data[0]["temporal"]
    data[0]["source_output"]["method_version"] = "fixture-revised-method"
    second = run(data)
    assert first["observation"] == second["observation"]
    assert (
        first["surveillance_evidence"]["evidence_revision_id"]
        != second["surveillance_evidence"]["evidence_revision_id"]
    )


def test_safe_consumer_companion_binds_semantic_revision_without_private_proof():
    data = negative()
    data[1]["visibility"] = "CONSUMER_SAFE"
    data[1]["revision_id"] = metadata_revision_id(data[1])
    payload = project_surveillance_evidence(*data, REGISTRY, fixture_mode=True)
    evidence = payload["surveillance_evidence"]
    assert evidence["state"] == "sampled_not_detected"
    assert evidence["revision_id"] == payload["semantic"]["observation"]["revision_id"]
    assert "source_testing_id" not in str(payload)
    assert "canonical_evidence_sha256" not in evidence


def test_existing_review_gate_is_not_replaced_by_source_classification():
    with pytest.raises(SemanticMappingError, match="unreviewed"):
        map_surveillance_evidence(*negative(), REGISTRY)
    with pytest.raises(ValueError, match="literal boolean"):
        map_surveillance_evidence(*negative(), REGISTRY, fixture_mode="true")
