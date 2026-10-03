"""Frozen artifact identity, tuple digest and atomic failure boundaries."""

import hashlib
import json

import pytest

from lyme_gap_atlas_data import climate_membership as membership
from lyme_gap_atlas_data.ingestion import nclimgrid_pilot_measurement as pilot


class Cursor:
    def __init__(self):
        self.identity = (
            "OH_LYME_DEV_PIPELINE_SVC",
            "OH_LYME_DEV_RUNTIME",
            "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            "OH_LYME_DEV_INGEST_XS_WH",
        )
        self.rows = [
            ("a" * 64, "revision-1", "record-1", "c" * 64, "d" * 64),
            ("b" * 64, "revision-2", "record-2", "e" * 64, "f" * 64),
        ]
        self.source_hash_bad = False
        self.pointer_changed = False
        self.extra_count = 0
        self.calls = []
        self.batch = False
        self.donor = {"sources": [{"source_key": str(i)} for i in range(5)], "unchanged": "annual"}

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        self.batch = False

    def fetchone(self):
        if "CURRENT_USER" in self.calls[-1][0]:
            return self.identity
        return (len(self.rows) + self.extra_count,)

    def fetchall(self):
        sql, params = self.calls[-1]
        if "INGESTION_RUNS" in sql:
            return [(membership.RESOURCE_KEY, "COMPLETED")]
        if "RAW_ARTIFACTS" in sql:
            source = next(s for s in membership.INPUTS if s["artifact_id"] == params[0])
            return [("wrong" if self.source_hash_bad else source["sha256"], source["byte_count"])]
        if "r.source_manifest" in sql:
            return [("current-annual", "PUBLISHED", self.donor)]
        return [("changed" if self.pointer_changed else "current-annual",)]

    def fetchmany(self, size):
        assert size == 1000
        if self.batch:
            return []
        self.batch = True
        return self.rows


def test_selected_tuple_wire_digest_and_annual_manifest_are_frozen_without_writes(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(membership, "ROW_COUNT", 2)
    cursor = Cursor()
    output = tmp_path / membership.ARTIFACT_NAME
    report = membership.freeze_membership(cursor, output, "1" * 40)
    expected = hashlib.sha256(
        b"".join(
            (json.dumps(list(row), separators=(",", ":")) + "\n").encode() for row in cursor.rows
        )
    ).hexdigest()
    artifact = json.loads(output.read_text())
    assert artifact["capture_ids"] == [row[0] for row in cursor.rows]
    assert artifact["capture_membership_sha256"] == report["capture_membership_sha256"] == expected
    assert artifact["annual_manifest"] == cursor.donor
    assert report["artifact_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert not report["writes_performed"] and not report["publication"]
    assert all(sql.startswith("SELECT") for sql, _ in cursor.calls)
    selected = next(params for sql, params in cursor.calls if "ORDER BY capture_record_id" in sql)
    assert selected == (
        membership.RUN_ID,
        membership.RESOURCE_KEY,
        membership.NOAA_ARTIFACT_ID,
        membership.NOAA_SHA,
    )


@pytest.mark.parametrize("mutation", ["identity", "hash", "order", "extra", "count", "pointer"])
def test_failed_gate_never_replaces_existing_artifact_or_leaves_partial_file(
    monkeypatch, tmp_path, mutation
):
    monkeypatch.setattr(membership, "ROW_COUNT", 2)
    cursor = Cursor()
    if mutation == "identity":
        cursor.identity = ("wrong", *cursor.identity[1:])
    elif mutation == "hash":
        cursor.source_hash_bad = True
    elif mutation == "order":
        cursor.rows.reverse()
    elif mutation == "extra":
        cursor.extra_count = 1
    elif mutation == "count":
        cursor.rows = cursor.rows[:1]
    else:
        cursor.pointer_changed = True
    output = tmp_path / membership.ARTIFACT_NAME
    output.write_text("existing-reviewed-artifact")
    with pytest.raises(membership.MembershipBlocked, match="MEMBERSHIP_"):
        membership.freeze_membership(cursor, output, "1" * 40)
    assert output.read_text() == "existing-reviewed-artifact"
    assert list(tmp_path.iterdir()) == [output]
    assert all(sql.startswith("SELECT") for sql, _ in cursor.calls)


def test_wrapper_rejects_other_run_and_missing_workflow_directory_before_connection(monkeypatch):
    monkeypatch.setattr(pilot, "connect", lambda _: pytest.fail("must not connect"))
    with pytest.raises(pilot.MeasurementError, match="approved January"):
        pilot.frozen_membership_report("other-run")
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    with pytest.raises(pilot.MeasurementError, match="workflow artifact directory"):
        pilot.frozen_membership_report(membership.RUN_ID)


def test_sdk_failure_does_not_emit_message_or_misclassify_absence(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))

    def unavailable(_settings):
        raise RuntimeError("private-connection-message")

    monkeypatch.setattr(pilot, "connect", unavailable)
    with pytest.raises(
        pilot.MeasurementError, match="FROZEN_MEMBERSHIP_READ_UNAVAILABLE"
    ) as failure:
        pilot.frozen_membership_report(membership.RUN_ID)
    assert "private-connection-message" not in str(failure.value)
