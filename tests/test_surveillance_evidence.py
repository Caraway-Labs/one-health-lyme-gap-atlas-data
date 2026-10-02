"""Synthetic DATA429 behavior; fixtures do not approve source interpretation."""

import copy

import pytest
from test_semantic_domain import measure, observation, reseal

from lyme_gap_atlas_data.surveillance_evidence import (
    STATES,
    evidence_fixture,
    project_evidence_fixture,
)


def fixture(grain="COUNTY", value=3, state="OBSERVED"):
    m = measure("tick_status", grain=grain, strata=["tick_taxon", "pathogen_target"])
    o = observation(m, value=value, state=state)
    o["provenance"]["source_id"] = "fixture-surveillance"
    o["provenance"]["dataset_id"] = "fixture-ticks"
    o["provenance"]["source_version_id"] = "fixture-source-v1"
    o["strata"] = {"tick_taxon": "ixodes_scapularis", "pathogen_target": "bb_ss"}
    reseal(o, m)
    return o, m


def assertion(o, state):
    return {
        "observation_key": o["observation_key"],
        "revision_id": o["revision_id"],
        "state": state,
        "source_definition_ref": "fixture-definition-v1",
        "eligibility_rule_id": "fixture-rule-v1",
        "criteria_ref": "fixture-criteria-v1",
        "qualifying_sampling_proven": True,
        "not_detected_proven": True,
        "sampling_evidence_ref": "private-fixture-proof",
    }


@pytest.mark.parametrize("state", sorted(STATES))
def test_explicit_fixture_vocabulary_and_unchanged_observation(state):
    o, m = fixture()
    before = copy.deepcopy(o)
    result = evidence_fixture(o, m, assertion=assertion(o, state), fixture_mode=True)
    assert result["state"] == state
    assert result["value_state"] == "OBSERVED"
    assert o == before


@pytest.mark.parametrize(
    ("value", "state"),
    [
        (0, "ZERO"),
        (None, "UNKNOWN"),
        (None, "MISSING"),
        (None, "UNAVAILABLE"),
        (None, "SUPPRESSED"),
        (None, "NOT_REPORTED"),
        ("No records", "NO_RECORDS"),
    ],
)
def test_value_or_absence_alone_never_classifies(value, state):
    o, m = fixture(value=value, state=state)
    result = evidence_fixture(o, m, fixture_mode=True)
    assert result["state"] == "unknown"
    assert result["value_state"] == state


@pytest.mark.parametrize(
    "field", ["qualifying_sampling_proven", "not_detected_proven", "sampling_evidence_ref"]
)
def test_sampled_negative_requires_both_sampling_and_result_proof(field):
    o, m = fixture("SITE_EVENT", value=0, state="ZERO")
    proof = assertion(o, "sampled_not_detected")
    del proof[field]
    assert evidence_fixture(o, m, assertion=proof, fixture_mode=True)["state"] == "unknown"


def test_site_grain_and_stale_period_are_retained_without_county_or_freshness_inference():
    o, m = fixture("SITE_EVENT")
    o["temporal"].update(start="2000-01-01", end="2000-12-31")
    reseal(o, m)
    result = evidence_fixture(
        o, m, assertion=assertion(o, "sampled_not_detected"), fixture_mode=True
    )
    assert result["scope"]["geography"]["representativeness"] == "NOT_COUNTY_REPRESENTATIVE"
    assert result["scope"]["temporal"]["end"] == "2000-12-31"
    assert result["state"] == "sampled_not_detected"


def test_revised_or_mixed_source_assertion_cannot_attach_to_other_revision():
    o, m = fixture()
    proof = assertion(o, "established")
    previous = evidence_fixture(o, m, assertion=proof, fixture_mode=True)
    o["provenance"]["source_version_id"] = "fixture-source-v2"
    reseal(o, m)
    with pytest.raises(ValueError, match="another observation or revision"):
        evidence_fixture(o, m, assertion=proof, fixture_mode=True)
    revised = evidence_fixture(o, m, assertion=assertion(o, "unknown"), fixture_mode=True)
    assert revised["evidence_revision_id"] != previous["evidence_revision_id"]


def test_source_only_geography_abstains_even_with_explicit_fixture_state():
    o, m = fixture("SOURCE_ONLY_COUNTY", value=None, state="UNKNOWN")
    assert (
        evidence_fixture(o, m, assertion=assertion(o, "established"), fixture_mode=True)["state"]
        == "unknown"
    )


def test_unreviewed_scientific_use_is_disabled_and_real_source_cannot_use_fixture_escape():
    o, m = fixture()
    with pytest.raises(ValueError, match="scientific review pending"):
        evidence_fixture(o, m)
    o["provenance"]["source_version_id"] = "real-source-v1"
    reseal(o, m)
    with pytest.raises(ValueError, match="synthetic reported"):
        evidence_fixture(o, m, fixture_mode=True)


def test_companion_projection_excludes_private_proof_and_keeps_no_records_literal():
    o, m = fixture(value="No records", state="NO_RECORDS")
    o["temporal"]["warehouse_path"] = "private-temporal-fixture"
    proof = assertion(o, "no_qualifying_record")
    proof["warehouse_path"] = "private-storage-fixture"
    payload = project_evidence_fixture(o, m, assertion=proof, fixture_mode=True)
    assert payload["state"] == "no_qualifying_record"
    assert payload["value_state"] == "NO_RECORDS"
    assert "private" not in str(payload)
    assert "source_record_id" not in payload
    assert payload["evidence_tier"] == "SYNTHETIC_FIXTURE"


def test_unknown_criteria_and_numeric_zero_cannot_create_establishment_rule():
    o, m = fixture(value=0, state="ZERO")
    proof = assertion(o, "established")
    del proof["criteria_ref"]
    assert evidence_fixture(o, m, assertion=proof, fixture_mode=True)["state"] == "unknown"
