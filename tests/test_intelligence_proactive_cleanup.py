"""Proactive PROD deadline, exact-plan retry and physical absence alarms."""

import importlib.util
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from lyme_gap_atlas_data.intelligence_retention import (
    RawCopy,
    capture_lease,
    execute_cleanup,
    plan_cleanup,
)

spec = importlib.util.spec_from_file_location(
    "proactive_runner", Path(__file__).parents[1] / "scripts/intelligence_raw_cleanup_prod.py"
)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def fixture(environment="PROD", source="cdc-eid-expedited"):
    lease = capture_lease(
        source_id=source,
        registry_version=1,
        source_sha256="a" * 64,
        capture_id="deadline-test",
        artifact_sha256="b" * 64,
        captured_at="2026-09-01T00:00:00Z",
        policy_ref="reviewed-raw30",
        permitted=lambda *_: True,
    )
    copies = (
        RawCopy(
            environment,
            source,
            "checkpoint_payload",
            f"snowflake://ONE_HEALTH_LYME_GAP_ATLAS_{environment}/GOVERNANCE/INGESTION_RUN_PAYLOADS/deadline-test",
            lease.sha256,
        ),
        RawCopy(
            environment,
            source,
            "raw_object",
            f"s3://one-health-lyme-gap-atlas-data-prod/prod/prod/{source}/deadline-test/{lease.artifact_sha256}.bin",
            lease.sha256,
        ),
    )
    leases = {lease.sha256: lease}
    ledger = SimpleNamespace(
        environment=environment,
        copies=lambda: copies,
        claims=lambda c: tuple(x for x in copies if x.physical_key == c.physical_key),
        lease=lambda sha: leases[sha],
    )
    return ledger, lease, leases


def plan(ledger, now):
    return plan_cleanup(
        ledger,
        environment=ledger.environment,
        source_ids=(ledger.copies()[0].source_id,),
        now=now,
        scope=lambda _: True,
    )


@pytest.mark.parametrize(
    "at,count",
    [
        ("2026-09-28T23:59:59.999999Z", 0),
        ("2026-09-29T00:00:00Z", 2),
        ("2026-09-29T00:00:00.000001Z", 2),
        ("2026-09-30T23:59:59.999999Z", 2),
        ("2026-10-01T00:00:00Z", 2),
    ],
)
def test_fixed_48_hour_boundary_without_renewing_lease(at, count):
    ledger, lease, _ = fixture()
    assert len(plan(ledger, at).copies) == count
    assert lease.expires_at == "2026-10-01T00:00:00Z"


@pytest.mark.parametrize(
    "environment,source", [("DEV", "cdc-eid-expedited"), ("PROD", "other-feed")]
)
def test_proactive_window_does_not_expand_other_policies(environment, source):
    ledger, _, _ = fixture(environment, source)
    assert plan(ledger, "2026-09-30T23:59:59Z").copies == ()


def test_newer_shared_claim_is_not_deleted_early():
    ledger, lease, leases = fixture()
    fresh = replace(
        lease,
        capture_id="fresh",
        captured_at="2026-09-02T00:00:00Z",
        expires_at="2026-10-02T00:00:00Z",
    )
    leases[fresh.sha256] = fresh
    copies = ledger.copies()
    inventory = copies + tuple(replace(c, lease_sha256=fresh.sha256) for c in copies)
    ledger.copies = lambda: inventory
    ledger.claims = lambda c: tuple(x for x in inventory if x.physical_key == c.physical_key)
    assert plan(ledger, "2026-09-29T00:00:00Z").copies == ()


def test_daily_phase_and_one_failed_cycle_leave_time_for_exact_plan_retry():
    ledger, _, _ = fixture()
    # Worst daily phase: eligibility was almost 24h ago; nearly 24h still remain.
    reviewed = plan(ledger, "2026-09-29T23:59:59Z")
    audit = []

    def fail(_):
        raise OSError("private provider error")

    failed = execute_cleanup(
        reviewed,
        ledger,
        now="2026-09-29T23:59:59Z",
        approved=lambda _: True,
        scope=lambda _: True,
        delete={"raw_object": fail, "checkpoint_payload": fail},
        audit=audit.append,
    )
    assert {r.outcome for r in failed} == {"failed"}
    assert [r.outcome for r in audit].count("pending") == 2
    assert "private provider" not in str(audit)
    retried = execute_cleanup(
        reviewed,
        ledger,
        now="2026-09-30T23:59:58Z",
        approved=lambda sha: sha == reviewed.sha256,
        scope=lambda _: True,
        delete={"raw_object": lambda _: True, "checkpoint_payload": lambda _: True},
        audit=audit.append,
    )
    assert {r.outcome for r in retried} == {"deleted"}


def test_early_window_keeps_exact_approval_and_audit_failure_closed():
    ledger, _, _ = fixture()
    reviewed = plan(ledger, "2026-09-29T00:00:00Z")
    calls = []
    with pytest.raises(PermissionError, match="APPROVAL_REQUIRED"):
        execute_cleanup(
            reviewed,
            ledger,
            now=reviewed.planned_at,
            approved=lambda _: False,
            scope=lambda _: True,
            delete={"raw_object": calls.append},
            audit=calls.append,
        )
    assert calls == []

    def audit_fail(_):
        raise OSError("audit unavailable")

    with pytest.raises(OSError, match="audit unavailable"):
        execute_cleanup(
            reviewed,
            ledger,
            now=reviewed.planned_at,
            approved=lambda _: True,
            scope=lambda _: True,
            delete={"raw_object": calls.append, "checkpoint_payload": calls.append},
            audit=audit_fail,
        )
    assert calls == []


def monitor(monkeypatch, now, *, present=True, query_error=False, versions=False):
    ledger, _, _ = fixture()

    class Clock(datetime):
        @staticmethod
        def now(_):
            return datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(UTC)

    monkeypatch.setattr(runner, "datetime", Clock)
    monkeypatch.setattr(runner, "inspection_identity", lambda: None)
    monkeypatch.setattr(runner, "inspection_snapshot", lambda: ledger)
    monkeypatch.setenv("INTELLIGENCE_CLEANUP_SPACES_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("INTELLIGENCE_CLEANUP_SPACES_SECRET_ACCESS_KEY", "test")

    def query(_):
        if query_error:
            raise PermissionError("INSPECTION_UNAVAILABLE")
        return [{"N": int(present)}]

    monkeypatch.setattr(runner, "inspection_query", query)

    class Client:
        def head_object(self, **_):
            if not present:
                error = RuntimeError("absent")
                error.response = {"Error": {"Code": "404"}}
                raise error

        def list_object_versions(self, **_):
            return {"DeleteMarkers": [{}]} if versions else {}

        def delete_object(self, **_):
            pytest.fail("monitor attempted deletion")

    monkeypatch.setattr(runner.boto3, "client", lambda *_, **__: Client())
    return ledger


@pytest.mark.parametrize(
    "now,urgent,overdue",
    [
        ("2026-09-29T00:00:00Z", 0, 0),
        ("2026-09-30T00:00:00Z", 2, 0),
        ("2026-10-01T00:00:00Z", 2, 2),
    ],
)
def test_presence_alarm_starts_at_eligibility_not_after_deadline(
    monkeypatch, capsys, now, urgent, overdue
):
    monitor(monkeypatch, now)
    with pytest.raises(SystemExit) as error:
        runner.deadline_check()
    assert error.value.code == 2
    receipt = json.loads(capsys.readouterr().out)
    assert receipt == {
        "remaining_due_copies": 2,
        "urgent_copies": urgent,
        "overdue_copies": overdue,
        "writes": False,
        "deletes": False,
    }


@pytest.mark.parametrize(
    "present,now", [(False, "2026-10-01T00:00:00Z"), (True, "2026-09-28T23:59:59Z")]
)
def test_monitor_green_requires_absence_or_not_yet_due(monkeypatch, capsys, present, now):
    monitor(monkeypatch, now, present=present)
    runner.deadline_check()
    assert json.loads(capsys.readouterr().out)["remaining_due_copies"] == 0


@pytest.mark.parametrize("failure", ["warehouse", "versions", "credentials", "drift"])
def test_monitor_cannot_report_green_on_verification_failure(monkeypatch, capsys, failure):
    ledger = monitor(
        monkeypatch,
        "2026-09-30T00:00:00Z",
        query_error=failure == "warehouse",
        versions=failure == "versions",
    )
    if failure == "credentials":
        monkeypatch.delenv("INTELLIGENCE_CLEANUP_SPACES_ACCESS_KEY_ID")
    if failure == "drift":
        count = 0

        def snapshot():
            nonlocal count
            count += 1
            return ledger if count == 1 else SimpleNamespace(copies=lambda: ())

        monkeypatch.setattr(runner, "inspection_snapshot", snapshot)
    with pytest.raises(PermissionError):
        runner.deadline_check()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "at,allowed",
    [
        ("2026-09-28T23:59:59.999999Z", True),
        ("2026-09-29T00:00:00Z", False),
        ("2026-09-30T23:59:59Z", False),
    ],
)
def test_runtime_cannot_recreate_cleaned_bytes_from_old_lease(tmp_path, at, allowed):
    from dataclasses import asdict

    from lyme_gap_atlas_data.intelligence_items import identity_hash
    from lyme_gap_atlas_data.intelligence_raw_runtime import (
        FeedRawRetention,
        SnowflakeRawLedger,
        SQLiteRawLedger,
    )
    from lyme_gap_atlas_data.intelligence_retention import require_read

    _, lease, _ = fixture()
    source = {"source_id": "cdc-eid-expedited", "registry_version": 1}
    lease = replace(lease, source_sha256=identity_hash(source))

    # Offline backend implements the shared-ledger interface; no Snowflake connection.
    class OfflineLedger(SQLiteRawLedger, SnowflakeRawLedger):
        environment = "PROD"

    ledger = OfflineLedger(tmp_path / "lease.sqlite")
    with ledger.guard():
        ledger.put("lease", lease.sha256, asdict(lease))
    gate = FeedRawRetention(
        ledger,
        environment="PROD",
        source_lookup=lambda *_: source,
        policy_lookup=lambda _: lease.policy_ref,
        clock=lambda: at,
    )
    locator = (
        "snowflake://ONE_HEALTH_LYME_GAP_ATLAS_PROD/GOVERNANCE/INGESTION_RUN_PAYLOADS/deadline-test"
    )
    copy = RawCopy("PROD", lease.source_id, "checkpoint_payload", locator, lease.sha256)
    with ledger.guard():
        ledger.put("copy", copy.sha256, asdict(copy))
    touched = []

    def resave():
        with gate.lease_access(lease.sha256, "checkpoint_payload", locator, write=True):
            touched.append("raw backend")

    if allowed:
        resave()
        require_read(copy, gate, now=at, permitted=lambda _: True)
        assert touched == ["raw backend"]
    else:
        with pytest.raises(PermissionError, match="RAW_EXPIRED"):
            resave()
        with pytest.raises(PermissionError, match="RAW_EXPIRED"):
            require_read(copy, gate, now=at, permitted=lambda _: True)
        assert touched == []
