"""Offline API88 serialization boundary for the accepted DATA429 writer."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from test_surveillance_evidence_mapping import REGISTRY, case, negative, reported

from lyme_gap_atlas_data.semantic_metadata import metadata_revision_id
from lyme_gap_atlas_data.surveillance_evidence_mapping import project_surveillance_evidence

CONTRACTS = Path(__file__).resolve().parents[1] / "docs/contracts/semantic-domain"
SEMANTIC = json.loads((CONTRACTS / "atlas-semantic-consumer-v1.schema.json").read_text())
SCHEMA = json.loads((CONTRACTS / "surveillance-evidence-consumer-v2.schema.json").read_text())
VALIDATOR = Draft202012Validator(
    SCHEMA,
    registry=Registry().with_resource(SEMANTIC["$id"], Resource.from_contents(SEMANTIC)),
)


def payload(data):
    record, metadata, authority = data
    metadata["visibility"] = "CONSUMER_SAFE"
    metadata["revision_id"] = metadata_revision_id(metadata)
    return project_surveillance_evidence(record, metadata, authority, REGISTRY, fixture_mode=True)


@pytest.mark.parametrize(
    ("data", "state"),
    [
        (case("county_tick_status", "Established"), "established"),
        (reported(), "detected_below_establishment"),
        (negative(), "sampled_not_detected"),
        (case("county_tick_status", "No records"), "no_qualifying_record"),
        (case("county_pathogen_status", "Present"), "unknown"),
    ],
)
def test_existing_writer_validates_without_network_and_preserves_observation(data, state):
    result = json.loads(json.dumps(payload(copy.deepcopy(data))))
    VALIDATOR.validate(result)
    evidence = result["surveillance_evidence"]
    observation = result["semantic"]["observation"]
    assert evidence["state"] == state
    assert evidence["observation_key"] == observation["id"]
    assert evidence["revision_id"] == observation["revision_id"]
    assert evidence["value_state"] == observation["value_state"]
    assert evidence["evidence_tier"] == result["semantic"]["evidence_tier"] == "SYNTHETIC_FIXTURE"


@pytest.mark.parametrize("field", ["canonical_evidence_sha256", "lineage_id", "source_output"])
def test_private_evidence_fields_are_not_consumer_contract(field):
    result = payload(negative())
    result["surveillance_evidence"][field] = "private"
    assert list(VALIDATOR.iter_errors(result))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state", "absent"),
        ("contract_version", "atlas-surveillance-evidence-v2"),
        ("reason_codes", []),
        ("evidence_revision_id", "evidence:v2:" + "0" * 64),
    ],
)
def test_unsupported_or_contextless_evidence_is_rejected(field, value):
    result = payload(negative())
    result["surveillance_evidence"][field] = value
    assert list(VALIDATOR.iter_errors(result))


def test_required_context_and_legacy_semantic_boundary_are_retained():
    Draft202012Validator.check_schema(SCHEMA)
    result = payload(negative())
    del result["surveillance_evidence"]["limitations"]
    assert list(VALIDATOR.iter_errors(result))
    result = payload(negative())
    result["semantic"]["observation"]["value_state"] = "ABSENT"
    assert list(VALIDATOR.iter_errors(result))
