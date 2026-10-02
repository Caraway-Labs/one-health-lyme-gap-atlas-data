"""DATA377 consumes reviewed DATA376 APIs; all comparisons are offline fixtures."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from lyme_gap_atlas_data.failure_evidence import review_context, validate_packet
from lyme_gap_atlas_data.operation_capabilities import assess_operation, load_contract

ROOT = Path(__file__).resolve().parents[1]
CORPUS = json.loads(
    (ROOT / "tests/fixtures/delivery-regressions/expected-v1.json").read_text(encoding="utf-8-sig")
)
CASES = {case["id"]: case for case in CORPUS["cases"]}
PACKETS = ROOT / "docs/delivery/failures"
BOUNDARIES = [
    ("336", "CONNECTOR_WRITE", "DRIVER_BATCH_EXECUTION"),
    ("353", "PROCEDURE_BINDING", "DRIVER_VARIANT_EXECUTION"),
    ("365", "CANONICAL_COVERAGE", "CANONICAL_FIXTURE_EXECUTION"),
    ("366", "RELEASE_AUTHORITY", "INTENDED_ROLE_EXECUTION"),
]


@pytest.mark.parametrize("case_id,boundary,missing_check", BOUNDARIES)
def test_frozen_cases_consume_validated_historical_reviewer_packets(
    case_id, boundary, missing_check
):
    packet = json.loads((PACKETS / f"pr-{case_id}.json").read_text(encoding="utf-8"))
    before = copy.deepcopy(packet)
    validate_packet(packet)
    review = review_context(packet)
    assert packet == before
    assert packet["schema_version"] == "1"
    assert review["boundary"] == boundary
    assert review["missing_check"] == missing_check
    assert review["independent_behavioral_evidence_required"] is True
    assert (
        f"https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/pull/{case_id}"
        in (packet["verified_facts"])
    )
    assert packet["regression"]["kind"] == "STATIC"
    assert packet["repair"]["state"] == "UNKNOWN"
    assert packet["identity"]["workload_sha"]["state"] == "UNKNOWN"
    assert packet["effective_role"]["state"] == "UNKNOWN"
    # Desired mapping cannot fill missing observed identity or functional proof.
    report = assess_operation(load_contract(), operation="semantic_release", environment="prod")
    assert report["status"] == "UNKNOWN"
    if case_id != "366":
        assert report["status"] == CASES[case_id]["expected"]


def test_permission_packet_and_frozen_denial_keep_authority_unknown():
    packet = json.loads((PACKETS / "pr-366.json").read_text(encoding="utf-8"))
    validate_packet(packet)
    review = review_context(packet)
    assert review["missing_check"] == "INTENDED_ROLE_EXECUTION"
    case = CASES["366"]
    # Denial is the explicit sanitized offline case input, not a live observation
    # inferred from the packet's UNKNOWN role or the configured executor policy.
    report = assess_operation(
        load_contract(),
        operation="semantic_release",
        environment="prod",
        observed={"capabilities": {case["runtime_object"]: False}},
    )
    findings = {finding["check"]: finding["status"] for finding in report["findings"]}
    assert report["status"] == case["expected"]
    assert findings[f"runtime_capability:{case['runtime_object']}"] == "BLOCKED"
    assert findings["grant_authority"] == case["grant_authority"]
    assert findings["effective_identity"] == "UNKNOWN"
    assert report["mutation_started"] is False
    assert packet["repair"]["state"] == "UNKNOWN"


@pytest.mark.parametrize("case_id,_boundary,_missing_check", BOUNDARIES)
def test_capstone_rejects_packet_promoted_to_repaired_from_static_proof(
    case_id, _boundary, _missing_check
):
    packet = json.loads((PACKETS / f"pr-{case_id}.json").read_text(encoding="utf-8"))
    packet["repair"] = copy.deepcopy(packet["regression"])
    with pytest.raises(ValueError, match="^failure evidence rejected$"):
        validate_packet(packet)


def test_capstone_rejects_tampered_packet_correlation_via_python_api():
    packet = json.loads((PACKETS / "pr-366.json").read_text(encoding="utf-8"))
    packet["correlation_key"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="^failure evidence rejected$"):
        validate_packet(packet)


def test_capstone_uses_mandatory_calendar_validation_beyond_schema_annotations():
    from lyme_gap_atlas_data.failure_evidence import PACKET_SCHEMA

    packet = json.loads((PACKETS / "pr-336.json").read_text(encoding="utf-8"))
    packet["recorded_at"] = "2026-02-30T00:00:00Z"
    # Shape/pattern validation alone accepts this impossible UTC calendar date.
    assert Draft202012Validator(PACKET_SCHEMA).is_valid(packet)
    with pytest.raises(ValueError, match="^failure evidence rejected$"):
        validate_packet(packet)
