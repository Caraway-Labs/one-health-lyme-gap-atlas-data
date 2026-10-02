"""Privacy, original-outcome preservation and honest delivery evidence (#376)."""

import copy
import json
from pathlib import Path

import pytest

from lyme_gap_atlas_data.failure_evidence import (
    PACKET_SCHEMA,
    build_packet,
    collect_failure,
    review_context,
    unknown,
    validate_packet,
)

ROOT = Path(__file__).resolve().parents[1]


def example():
    return json.loads((ROOT / "docs/delivery/failures/pr-336.json").read_text())


def test_schema_and_historical_packets():
    assert (
        json.loads((ROOT / "docs/delivery/failure-packet-v1.schema.json").read_text())
        == PACKET_SCHEMA
    )
    for path in (ROOT / "docs/delivery/failures").glob("pr-*.json"):
        packet = json.loads(path.read_text())
        validate_packet(packet)
        assert packet["identity"]["workload_sha"]["state"] == "UNKNOWN"
        assert packet["repair"]["state"] == "UNKNOWN"
        assert review_context(packet)["independent_behavioral_evidence_required"]


@pytest.mark.parametrize(
    "secret",
    [
        "password=fake-sensitive-value",
        "Bearer fake-private-token",
        "SELECT * WHERE name='private'",
        "C:\\Users\\PrivatePerson\\workbook.xlsx",
        "private@example.test",
        "hidden prompt",
        "https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/pull/336?token=private",
        "https://github.com/other/private/pull/336",
        "\nprivate payload",
        {"nested": "private"},
    ],
)
@pytest.mark.parametrize(
    "field", ["effective_role", "query_ids", "diagnostic_code", "verified_facts"]
)
def test_arbitrary_content_rejected_without_echo(secret, field, capsys):
    context = example()
    context[field] = secret
    captured = []
    assert collect_failure(context, captured.append) == "REDACTION_REJECTED"
    assert captured == []
    assert capsys.readouterr() == ("", "")


def test_unknown_keys_and_nested_payloads_fail_closed():
    for section in (None, "identity", "artifacts", "regression"):
        packet = example()
        target = packet if section is None else packet[section]
        target["raw_exception"] = "private SQL parameters"
        with pytest.raises(ValueError, match="failure evidence rejected"):
            build_packet(packet)


def test_correlation_stable_across_attempts_and_separates_boundaries():
    first = example()
    second = copy.deepcopy(first)
    second["recorded_at"] = "2026-10-02T00:00:00Z"
    second["identity"]["attempt"] = {"state": "KNOWN", "value": 2}
    second["identity"]["job_id"] = {"state": "KNOWN", "value": 123}
    assert build_packet(first)["correlation_key"] == build_packet(second)["correlation_key"]
    second["boundary"] = "LOAD"
    assert build_packet(first)["correlation_key"] != build_packet(second)["correlation_key"]
    second["identity"]["workload_sha"] = {"state": "KNOWN", "value": "a" * 40}
    assert build_packet(first)["correlation_key"] != build_packet(second)["correlation_key"]


def test_missing_evidence_is_explicit_and_empty_query_list_is_not_known():
    context = example()
    context["effective_role"] = unknown("ROLE_NOT_VISIBLE")
    context["query_ids"] = unknown("QUERY_ID_UNAVAILABLE")
    context["unknowns"] = ["INCOMPLETE_LOGS", "ROLE_NOT_VISIBLE", "QUERY_ID_UNAVAILABLE"]
    packet = build_packet(context)
    assert packet["query_ids"] == unknown("QUERY_ID_UNAVAILABLE")
    context["query_ids"] = {"state": "KNOWN", "value": []}
    with pytest.raises(ValueError):
        build_packet(context)
    del context["identity"]["workload_sha"]
    assert collect_failure(context, lambda _: None) == "REDACTION_REJECTED"


def test_collection_failures_preserve_original_exception_and_input():
    class PrivateError(Exception):
        def __str__(self):
            raise AssertionError("must never render private exception")

    original = PrivateError()
    context = example()
    before = copy.deepcopy(context)

    def broken_sink(_):
        raise RuntimeError("private sink details")

    with pytest.raises(PrivateError) as caught:
        try:
            raise original
        except PrivateError:
            assert collect_failure(context, broken_sink) == "COLLECTION_UNAVAILABLE"
            raise
    assert caught.value is original
    assert context == before


def test_workflow_head_is_not_actual_workload_or_artifact():
    context = example()
    context["identity"]["workflow_head_sha"] = {"state": "KNOWN", "value": "b" * 40}
    packet = build_packet(context)
    assert packet["identity"]["workload_sha"] == unknown()
    assert packet["artifacts"]["tested_artifact"] == unknown()


def test_static_pass_cannot_close_repair_and_behavioral_proof_can():
    context = example()
    proof = {
        "state": "PASS",
        "kind": "STATIC",
        "reference": {
            "state": "KNOWN",
            "value": context["verified_facts"][0],
        },
    }
    context["regression"] = copy.deepcopy(proof)
    context["repair"] = copy.deepcopy(proof)
    with pytest.raises(ValueError, match="failure evidence rejected"):
        build_packet(context)
    context["regression"]["kind"] = "BEHAVIORAL"
    context["repair"]["kind"] = "BEHAVIORAL"
    validate_packet(build_packet(context))
    context["repair"]["reference"] = unknown()
    with pytest.raises(ValueError):
        build_packet(context)


def test_failure_class_is_not_inferred_from_operational_category():
    context = example()
    for classification in (
        "SOFTWARE_DEFECT",
        "PERMISSION_CONFIGURATION",
        "GOVERNANCE_BLOCK",
        "UPSTREAM_OUTAGE",
        "INTENTIONAL_NEGATIVE_TEST",
        "UNKNOWN",
    ):
        context["failure_class"] = classification
        assert build_packet(context)["failure_class"] == classification
    context["risk"] = "PROSE_ONLY"
    assert not review_context(build_packet(context))["independent_behavioral_evidence_required"]


def test_bounded_diagnostics_and_attempts_survive_without_payloads():
    context = example()
    context["effective_role"] = {"state": "KNOWN", "value": "OH_LYME_DEV_RUNTIME"}
    context["query_ids"] = {
        "state": "KNOWN",
        "value": ["00000000-0000-0000-0000-000000000001"],
    }
    context["identity"]["attempt"] = {"state": "KNOWN", "value": 1}
    context["artifacts"]["tested_artifact"] = {"state": "KNOWN", "value": "sha256:" + "a" * 64}
    captured = []
    assert collect_failure(context, captured.append) == "COLLECTED"
    packet = captured[0]
    assert packet["query_ids"] == context["query_ids"]
    assert packet["diagnostic_code"] == "BATCH_WRITE_FAILED"
    assert packet["identity"]["attempt"]["value"] == 1
    assert packet["artifacts"]["deployed_artifact"] == unknown()
    context["query_ids"]["value"] *= 17
    assert collect_failure(context, captured.append) == "REDACTION_REJECTED"
    assert len(captured) == 1


def test_claimed_key_and_nested_references_cannot_bypass_validation():
    packet = example()
    packet["correlation_key"] = "sha256:" + "a" * 64
    with pytest.raises(ValueError, match="failure evidence rejected"):
        validate_packet(packet)
    for value in ("SELECT private", packet["verified_facts"][0] + "?private=payload"):
        context = example()
        context["reproduction"] = {"state": "KNOWN", "value": value}
        assert collect_failure(context, lambda _: None) == "REDACTION_REJECTED"
