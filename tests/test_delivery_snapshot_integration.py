"""Capstone consumes final snapshot and failure contracts without promoting metadata."""

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from lyme_gap_atlas_data.failure_evidence import review_context, validate_packet
from lyme_gap_atlas_data.metadata_snapshots import report, validate_snapshot
from lyme_gap_atlas_data.operation_capabilities import assess_operation, load_contract

ROOT = Path(__file__).resolve().parents[1]
CORPUS = json.loads(
    (ROOT / "tests/fixtures/delivery-regressions/expected-v1.json").read_text(encoding="utf-8-sig")
)
CASES = {case["id"]: case for case in CORPUS["cases"]}
SNAPSHOT = ROOT / "docs/generated/snowflake/dev-2026-10-02-current.snapshot.json"


def observed():
    value = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    validate_snapshot(value)
    return value


def capture_time(value):
    return datetime.fromisoformat(value["generated_at"].replace("Z", "+00:00"))


@pytest.mark.parametrize("case_id", ["336", "353", "365", "366"])
def test_final_owner_artifacts_do_not_supply_missing_historical_behavior(case_id):
    value = observed()
    before = copy.deepcopy(value)
    packet = json.loads(
        (ROOT / f"docs/delivery/failures/pr-{case_id}.json").read_text(encoding="utf-8")
    )
    validate_packet(packet)
    reviewer = review_context(packet)
    metadata = report(value, now=capture_time(value))
    assert value == before
    assert value["source"] == "live"
    assert value["visibility"] == "partial"
    assert value["content"]["procedures"] == []
    assert metadata["comparison_kind"] == "live_observation"
    assert metadata["consequential_use"] == "blocked"
    assert metadata["mutation_started"] is False
    assert any(finding["category"] == "unknown" for finding in metadata["findings"])
    assert reviewer["independent_behavioral_evidence_required"] is True
    assert packet["repair"]["state"] == "UNKNOWN"
    # Metadata is deliberately not passed as observed row lineage, identity or privileges.
    operation = assess_operation(load_contract(), operation="semantic_release", environment="prod")
    assert operation["status"] == "UNKNOWN"
    assert operation["mutation_started"] is False
    if case_id != "366":
        assert operation["status"] == CASES[case_id]["expected"]
    else:
        denial = assess_operation(
            load_contract(),
            operation="semantic_release",
            environment="prod",
            observed={"capabilities": {CASES[case_id]["runtime_object"]: False}},
        )
        assert denial["status"] == CASES[case_id]["expected"]


def test_frozen_stale_context_requires_refresh_of_final_owner_observation():
    value = observed()
    expired = capture_time(value) + timedelta(hours=value["scope"]["maximum_age_hours"] + 1)
    result = report(value, now=expired)
    assert CASES["stale-context"]["expected"] == "UNKNOWN"
    assert any(
        item["category"] == "stale" and item["subject"] == "snapshot" for item in result["findings"]
    )
    assert result["consequential_use"] == "blocked"


def test_tampered_owner_observation_cannot_become_readiness():
    value = observed()
    value["semantic_hash"] = "0" * 64
    result = report(value, now=capture_time(value))
    assert any(
        item["category"] == "mismatched" and item["subject"] == "semantic_hash"
        for item in result["findings"]
    )
    assert result["consequential_use"] == "blocked"


def test_synthetic_baseline_does_not_upgrade_final_live_observation():
    value = observed()
    baseline = json.loads(
        (ROOT / "docs/contracts/snowflake-snapshots/examples/synthetic.snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    result = report(value, now=capture_time(value), baseline=baseline)
    assert result["source"] == "live"
    assert result["baseline_source"] == "synthetic"
    assert result["comparison_kind"] == "mixed_source_non_live"
    assert result["consequential_use"] == "blocked"


def test_reviewed_offline_driver_receipt_does_not_upgrade_engine_repair():
    original = json.loads((ROOT / "docs/delivery/failures/pr-336.json").read_text(encoding="utf-8"))
    companion = json.loads(
        (
            ROOT / "docs/delivery/failure-reproduction-receipts/pr-336-client-binding-v1.json"
        ).read_text(encoding="utf-8")
    )
    for packet in (original, companion):
        validate_packet(packet)
        assert packet["repair"]["state"] == CASES["336"]["expected"]
        assert packet["identity"]["workload_sha"]["state"] == "UNKNOWN"
        assert packet["effective_role"]["state"] == "UNKNOWN"
        assert review_context(packet)["missing_check"] == "DRIVER_BATCH_EXECUTION"
    assert original["regression"]["kind"] == "STATIC"
    assert companion["regression"]["kind"] == "BEHAVIORAL"
    assert companion["regression"]["state"] == "PASS"
    value = observed()
    assert report(value, now=capture_time(value))["consequential_use"] == "blocked"
