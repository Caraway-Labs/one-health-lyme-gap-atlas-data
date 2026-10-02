"""Privacy, original-outcome preservation and honest delivery evidence (#376)."""

import copy
import json
import re
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from lyme_gap_atlas_data.failure_evidence import (
    PACKET_SCHEMA,
    VALIDATOR,
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


def test_observed_role_allowlist_matches_rendered_current_contracts():
    model = (ROOT / "docs/operations/snowflake-stable-role-model.md").read_text()
    current_table = model.split("Removed entirely", 1)[0]
    templates = set(re.findall(r"`(OH_LYME_\{ENV\}_[A-Z_]+)`", current_table))
    expected = {role.replace("{ENV}", env) for role in templates for env in ("DEV", "PROD")}
    observed_roles = PACKET_SCHEMA["properties"]["effective_role"]["oneOf"][0]["properties"][
        "value"
    ]["enum"]
    assert len(expected) == 10
    assert set(observed_roles) == expected
    capabilities = yaml.safe_load((ROOT / "config/operation-capabilities-v1.yml").read_text())
    for role in capabilities["role_aliases"].values():
        for env in ("DEV", "PROD"):
            assert role.replace("{ENV}", env) in observed_roles
    inventory = (ROOT / "docs/operations/connection-inventory.md").read_text()
    connections = dict(
        re.findall(
            r"^\| `(ATLAS_[A-Z_]+)` \| `(OH_LYME_[A-Z_]+)`",
            inventory,
            re.MULTILINE,
        )
    )
    assert connections["ATLAS_PROD_MIGRATOR"] == "OH_LYME_PROD_MIGRATION_DEPLOYER"
    assert set(connections.values()) <= set(observed_roles)


@pytest.mark.parametrize(
    "role",
    [
        "OH_LYME_DEV_READ",
        "OH_LYME_DEV_OWNER",
        "OH_LYME_DEV_RUNTIME",
        "OH_LYME_DEV_MIGRATION_DEPLOYER",
        "OH_LYME_DEV_STREAMLIT_OWNER",
        "OH_LYME_PROD_READ",
        "OH_LYME_PROD_OWNER",
        "OH_LYME_PROD_RUNTIME",
        "OH_LYME_PROD_MIGRATION_DEPLOYER",
        "OH_LYME_PROD_STREAMLIT_OWNER",
    ],
)
def test_documented_observed_roles_retained_without_alias_substitution(role):
    context = example()
    context["effective_role"] = {"state": "KNOWN", "value": role}
    assert build_packet(context)["effective_role"] == context["effective_role"]


@pytest.mark.parametrize(
    "alias",
    [
        "ATLAS_PROD_MIGRATOR",
        "ATLAS_DEV_READ",
        "ATLAS_PROD_RUNTIME_AUDIT",
        "OH_LYME_PROD_MIGRATOR",
        "OH_LYME_DEV_MIGRATOR",
        "migration_deployer",
    ],
)
def test_connection_names_and_capability_aliases_are_not_observed_roles(alias):
    context = example()
    context["effective_role"] = {"state": "KNOWN", "value": alias}
    assert collect_failure(context, lambda _: None) == "REDACTION_REJECTED"


def privacy_context(known):
    context = example()
    context.pop("correlation_key")  # This is derived output, not caller evidence.
    if known:
        for name in context["identity"]:
            context["identity"][name] = {
                "state": "KNOWN",
                "value": "a" * 40 if name.endswith("sha") else 1,
            }
        for name in context["artifacts"]:
            context["artifacts"][name] = {"state": "KNOWN", "value": "sha256:" + "a" * 64}
        context["effective_role"] = {"state": "KNOWN", "value": "OH_LYME_PROD_MIGRATION_DEPLOYER"}
        context["migration"] = {"state": "KNOWN", "value": "V091"}
        context["query_ids"] = {"state": "KNOWN", "value": ["00000000-0000-0000-0000-000000000001"]}
        reference = {"state": "KNOWN", "value": context["verified_facts"][0]}
        context["reproduction"] = copy.deepcopy(reference)
        for name in ("regression", "repair"):
            context[name] = {
                "state": "PASS",
                "kind": "BEHAVIORAL",
                "reference": copy.deepcopy(reference),
            }
    return context


def string_paths(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from string_paths(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from string_paths(child, (*path, index))
    elif isinstance(value, str):
        yield path


@pytest.mark.parametrize(
    "known,path",
    [(known, path) for known in (False, True) for path in string_paths(privacy_context(known))],
)
@pytest.mark.parametrize(
    "hostile",
    [
        "password=fake-sensitive-value",
        "SELECT private WHERE name='private'",
        "C:\\Users\\PrivatePerson\\workbook.xlsx",
        "private@example.test",
        "private prompt\nprivate payload",
    ],
)
def test_every_input_string_leaf_rejects_hostile_content_without_sink(known, path, hostile, capsys):
    context = privacy_context(known)
    target = context
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = hostile
    captured = []
    assert collect_failure(context, captured.append) == "REDACTION_REJECTED"
    assert captured == []
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "bad_timestamp",
    [
        "password=fake-sensitive-value",
        "2026-02-29T00:00:00Z",
        "2026-10-02T24:00:00Z",
        "2026-10-02T00:00:60Z",
        "0000-10-02T00:00:00Z",
        "2026-10-02T00:00:00Z\n",
        "2026-10-02T00:00:00+00:00",
        "2026-10-02T00:00:00Zprivate",
    ],
)
def test_timestamps_fail_closed_without_optional_format_checker(bad_timestamp, monkeypatch):
    monkeypatch.setattr(VALIDATOR, "format_checker", None)
    context = privacy_context(False)
    context["recorded_at"] = bad_timestamp
    captured = []
    assert collect_failure(context, captured.append) == "REDACTION_REJECTED"
    assert captured == []


def test_schema_pattern_blocks_reported_bypass_without_format_checker():
    packet = example()
    packet["recorded_at"] = "password=fake-sensitive-value"
    assert not Draft202012Validator(PACKET_SCHEMA).is_valid(packet)


def test_valid_calendar_timestamp_and_complete_nested_evidence_collect_without_format_checker(
    monkeypatch,
):
    monkeypatch.setattr(VALIDATOR, "format_checker", None)
    for known in (False, True):
        context = privacy_context(known)
        context["recorded_at"] = "2024-02-29T23:59:59Z"
        captured = []
        assert collect_failure(context, captured.append) == "COLLECTED"
        assert captured[0]["recorded_at"] == "2024-02-29T23:59:59Z"


@pytest.mark.parametrize("field", ["reproduction", "regression", "repair", "verified_facts"])
def test_public_reference_control_suffix_is_rejected(field):
    context = privacy_context(True)
    if field == "verified_facts":
        context[field][0] += "\n"
    elif field == "reproduction":
        context[field]["value"] += "\n"
    else:
        context[field]["reference"]["value"] += "\n"
    assert collect_failure(context, lambda _: None) == "REDACTION_REJECTED"


@pytest.mark.parametrize("field", ["migration", "query_ids", "requested_sha", "tested_artifact"])
def test_bounded_identifier_control_suffix_is_rejected(field):
    context = privacy_context(True)
    if field == "migration":
        context[field]["value"] += "\n"
    elif field == "query_ids":
        context[field]["value"][0] += "\n"
    elif field == "requested_sha":
        context["identity"][field]["value"] += "\n"
    else:
        context["artifacts"][field]["value"] += "\n"
    assert collect_failure(context, lambda _: None) == "REDACTION_REJECTED"


def test_derived_correlation_never_publishes_supplied_private_text():
    context = privacy_context(False)
    context["correlation_key"] = "password=fake-sensitive-value"
    captured = []
    assert collect_failure(context, captured.append) == "COLLECTED"
    assert "fake-sensitive-value" not in json.dumps(captured)
    invalid_packet = example()
    invalid_packet["correlation_key"] = context["correlation_key"]
    with pytest.raises(ValueError, match="failure evidence rejected"):
        validate_packet(invalid_packet)
