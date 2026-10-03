"""Independent expiry controls; no real object, warehouse or filesystem delete."""

from dataclasses import replace

import pytest

from lyme_gap_atlas_data.intelligence_retention import (
    KINDS,
    RawCopy,
    RawLease,
    capture_lease,
    execute_cleanup,
    plan_cleanup,
    require_read,
)


def lease(capture: str = "capture-1", at: str = "2026-09-01T00:00:00Z") -> RawLease:
    return capture_lease(
        source_id="cdc-mmwr",
        registry_version=1,
        source_sha256="a" * 64,
        capture_id=capture,
        artifact_sha256="b" * 64,
        captured_at=at,
        policy_ref="approved-raw30",
        permitted=lambda *args: True,
    )


class Ledger:
    def __init__(self, leases, copies):
        self.leases = {item.sha256: item for item in leases}
        self.inventory = tuple(copies)

    def lease(self, digest):
        return self.leases[digest]

    def copies(self):
        return self.inventory

    def claims(self, copy):
        return tuple(item for item in self.inventory if item.physical_key == copy.physical_key)


def fixture(kind="checkpoint_payload"):
    original = lease()
    copy = RawCopy("DEV", original.source_id, kind, "fixture-only/feed/run1", original.sha256)
    return copy, Ledger([original], [copy])


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_all_copy_types_expire_at_exact_original_deadline(kind):
    copy, ledger = fixture(kind)
    assert require_read(copy, ledger, now="2026-09-30T23:59:59.999999Z", permitted=lambda _: True)
    with pytest.raises(PermissionError, match="RAW_EXPIRED"):
        require_read(copy, ledger, now="2026-10-01T00:00:00Z", permitted=lambda _: True)
    # Restart/new run references the SAME capture, never a new retrieval clock.
    resumed = replace(copy, locator="fixture-only/feed/resumed")
    ledger.inventory += (resumed,)
    with pytest.raises(PermissionError, match="RAW_EXPIRED"):
        require_read(resumed, ledger, now="2026-10-01T00:00:00Z", permitted=lambda _: True)


def test_rights_denial_and_unregistered_copy_fail_before_byte_read():
    copy, ledger = fixture()
    for candidate, permit in [(copy, False), (replace(copy, locator="unregistered"), True)]:
        with pytest.raises(PermissionError):
            require_read(
                candidate,
                ledger,
                now="2026-09-02T00:00:00Z",
                permitted=lambda _, allowed=permit: allowed,
            )
    with pytest.raises(PermissionError, match="RIGHTS_REQUIRED"):
        capture_lease(
            source_id="cdc-mmwr",
            registry_version=1,
            source_sha256="a" * 64,
            capture_id="denied",
            artifact_sha256="b" * 64,
            captured_at="2026-09-01T00:00:00Z",
            policy_ref="unreviewed",
            permitted=lambda *args: False,
        )


def test_a_304_or_retry_cannot_extend_capture_deadline():
    original = lease()
    forged = replace(original, expires_at="2026-10-02T00:00:00Z")
    with pytest.raises(ValueError, match="LEASE_INVALID"):
        forged.validate()
    # A genuine fresh 200 can own a distinct capture even with identical bytes.
    fresh = lease("fresh-200", "2026-09-30T00:00:00Z")
    assert fresh.artifact_sha256 == original.artifact_sha256 and fresh.sha256 != original.sha256


def test_live_claim_protects_shared_object_without_renewing_old_lease():
    copy, ledger = fixture("raw_object")
    fresh = lease("fresh-200", "2026-09-30T00:00:00Z")
    ledger.leases[fresh.sha256] = fresh
    ledger.inventory += (replace(copy, lease_sha256=fresh.sha256),)
    assert (
        plan_cleanup(
            ledger,
            environment="DEV",
            source_ids=("cdc-mmwr",),
            now="2026-10-01T00:00:00Z",
            scope=lambda _: True,
        ).copies
        == ()
    )
    with pytest.raises(PermissionError, match="RAW_EXPIRED"):
        require_read(copy, ledger, now="2026-10-01T00:00:00Z", permitted=lambda _: True)


def test_replay_alias_of_raw_object_also_protects_live_claim():
    copy, ledger = fixture("raw_object")
    fresh = lease("fresh-200", "2026-09-30T00:00:00Z")
    ledger.leases[fresh.sha256] = fresh
    ledger.inventory += (replace(copy, kind="artifact_member", lease_sha256=fresh.sha256),)
    assert (
        plan_cleanup(
            ledger,
            environment="DEV",
            source_ids=("cdc-mmwr",),
            now="2026-10-01T00:00:00Z",
            scope=lambda _: True,
        ).copies
        == ()
    )


def test_exact_approval_and_current_inventory_required_before_any_delete():
    copy, ledger = fixture()
    plan = plan_cleanup(
        ledger,
        environment="DEV",
        source_ids=("cdc-mmwr",),
        now="2026-10-01T00:00:00Z",
        scope=lambda _: True,
    )
    calls = []
    args = dict(
        now="2026-10-01T00:00:00Z",
        scope=lambda _: True,
        delete={copy.kind: lambda value: calls.append(value) or True},
        audit=calls.append,
    )
    for approved in (None, lambda _: False):
        with pytest.raises(PermissionError, match="APPROVAL_REQUIRED"):
            execute_cleanup(plan, ledger, approved=approved, **args)
    assert calls == []
    ledger.inventory += (replace(copy, locator="new-copy"),)
    with pytest.raises(PermissionError, match="PLAN_CHANGED"):
        execute_cleanup(plan, ledger, approved=lambda digest: digest == plan.sha256, **args)
    assert calls == []


def test_scope_denial_and_driver_preflight_prevent_partial_unapproved_delete():
    copy, ledger = fixture()
    with pytest.raises(PermissionError, match="SCOPE_INVALID"):
        plan_cleanup(
            ledger,
            environment="DEV",
            source_ids=("cdc-mmwr",),
            now="2026-10-01T00:00:00Z",
            scope=lambda _: False,
        )
    plan = plan_cleanup(
        ledger,
        environment="DEV",
        source_ids=("cdc-mmwr",),
        now="2026-10-01T00:00:00Z",
        scope=lambda _: True,
    )
    with pytest.raises(PermissionError, match="DRIVER_REQUIRED"):
        execute_cleanup(
            plan,
            ledger,
            now=plan.planned_at,
            approved=lambda _: True,
            scope=lambda _: True,
            delete={},
            audit=lambda _: pytest.fail("early audit"),
        )


def test_partial_failure_audited_redacted_and_idempotent_retry():
    copy, ledger = fixture()
    plan = plan_cleanup(
        ledger,
        environment="DEV",
        source_ids=("cdc-mmwr",),
        now="2026-10-01T00:00:00Z",
        scope=lambda _: True,
    )
    events = []

    def failure(value):
        raise RuntimeError("private locator and XML must never enter receipt")

    args = dict(
        now=plan.planned_at,
        approved=lambda digest: digest == plan.sha256,
        scope=lambda _: True,
        audit=events.append,
    )
    assert execute_cleanup(plan, ledger, delete={copy.kind: failure}, **args)[0].outcome == "failed"
    assert [e.outcome for e in events] == ["pending", "failed"]
    assert "private" not in repr(events) and copy.locator not in repr(events)
    assert (
        execute_cleanup(plan, ledger, delete={copy.kind: lambda _: True}, **args)[0].outcome
        == "deleted"
    )
    assert (
        execute_cleanup(plan, ledger, delete={copy.kind: lambda _: False}, **args)[0].outcome
        == "already_absent"
    )


def test_audit_failure_prevents_mutation():
    copy, ledger = fixture()
    plan = plan_cleanup(
        ledger,
        environment="DEV",
        source_ids=("cdc-mmwr",),
        now="2026-10-01T00:00:00Z",
        scope=lambda _: True,
    )

    def unavailable(receipt):
        raise RuntimeError("audit unavailable")

    with pytest.raises(RuntimeError, match="audit unavailable"):
        execute_cleanup(
            plan,
            ledger,
            now=plan.planned_at,
            approved=lambda _: True,
            scope=lambda _: True,
            delete={copy.kind: lambda _: pytest.fail("unsafe delete")},
            audit=unavailable,
        )
