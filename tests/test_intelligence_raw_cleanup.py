"""Only synthetic temporary files and provider doubles are deleted."""

import json
import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest
from test_intelligence_feed import definition
from test_intelligence_raw_runtime import END, adapter, setup

from lyme_gap_atlas_data.ingestion.intelligence_checkpoints import IntelligenceFileCheckpoints
from lyme_gap_atlas_data.intelligence_items import identity_hash
from lyme_gap_atlas_data.intelligence_raw_cleanup import FileRawDelete, ObjectRawDelete, cleanup
from lyme_gap_atlas_data.intelligence_retention import RawCopy, plan_cleanup


def prepared(tmp_path):
    source, gate, clock = setup(tmp_path)
    feed, _ = adapter(source, gate)
    capture = feed.acquire(definition(source))
    store = IntelligenceFileCheckpoints(tmp_path / "checkpoints", gate)
    store.save_payload("fixture-run", capture.payload)
    store.save_normalized("fixture-run", [{"eligible": "retained structured metadata"}])
    clock.value = END
    driver = FileRawDelete(store.root)
    plan = plan_cleanup(
        gate,
        environment="DEV",
        source_ids=(source["source_id"],),
        now=clock(),
        scope=lambda copy: bool(driver.path(copy)),
    )
    return source, gate, store, plan, driver


def audits(gate):
    with closing(sqlite3.connect(gate.ledger.audit_path)) as connection:
        return [json.loads(row[0]) for row in connection.execute("SELECT document FROM events")]


def test_exact_plan_cleanup_removes_only_fixture_xml_payload_and_retains_metadata(tmp_path):
    source, gate, store, plan, driver = prepared(tmp_path)
    payload_path = store._payload_path("fixture-run", "payload")
    with pytest.raises(PermissionError, match="APPROVAL_REQUIRED"):
        cleanup(gate, plan, scope=lambda copy: True, delete={"local_checkpoint": driver})
    assert payload_path.exists() and audits(gate) == []
    receipts = cleanup(
        gate,
        plan,
        approved=lambda digest: digest == plan.sha256,
        scope=lambda copy: bool(driver.path(copy)),
        delete={"local_checkpoint": driver},
    )
    assert any(receipt.outcome == "deleted" for receipt in receipts) and not payload_path.exists()
    assert store.load_normalized("fixture-run") == [{"eligible": "retained structured metadata"}]
    assert gate.lease(plan.copies[0].lease_sha256) and gate.ledger.documents("run")
    assert {event["outcome"] for event in audits(gate)} == {"pending", "deleted", "already_absent"}
    retry = cleanup(
        gate,
        plan,
        approved=lambda digest: digest == plan.sha256,
        scope=lambda copy: bool(driver.path(copy)),
        delete={"local_checkpoint": driver},
    )
    assert retry[0].outcome == "already_absent"


def test_crash_after_fixture_delete_keeps_durable_pending_intent_for_restart(tmp_path):
    source, gate, store, plan, driver = prepared(tmp_path)

    def crash(copy):
        if driver(copy):
            raise KeyboardInterrupt("simulated process crash")
        return False

    with pytest.raises(KeyboardInterrupt):
        cleanup(
            gate,
            plan,
            approved=lambda digest: digest == plan.sha256,
            scope=lambda copy: True,
            delete={"local_checkpoint": crash},
        )
    assert "pending" in {event["outcome"] for event in audits(gate)}
    assert "deleted" not in {event["outcome"] for event in audits(gate)}
    source2, restarted, clock2 = setup(tmp_path)
    clock2.value = END
    receipt = cleanup(
        restarted,
        plan,
        approved=lambda digest: digest == plan.sha256,
        scope=lambda copy: True,
        delete={"local_checkpoint": driver},
    )
    assert receipt[0].outcome == "already_absent"
    assert {event["outcome"] for event in audits(restarted)} == {"pending", "already_absent"}


def test_interrupted_atomic_write_leaves_registered_expirable_staging_file(tmp_path, monkeypatch):
    source, gate, clock = setup(tmp_path)
    feed, _ = adapter(source, gate)
    capture = feed.acquire(definition(source))
    store = IntelligenceFileCheckpoints(tmp_path / "checkpoints", gate)
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.intelligence_checkpoints.os.replace",
        lambda *args: (_ for _ in ()).throw(KeyboardInterrupt("simulated crash")),
    )
    with pytest.raises(KeyboardInterrupt):
        store.save_payload("fixture-run", capture.payload)
    staging = tuple(store.root.glob("*.raw-*.tmp"))
    assert len(staging) == 1 and staging[0].read_bytes()
    assert any(copy.locator == staging[0].resolve().as_uri() for copy in gate.copies())
    clock.value = END
    driver = FileRawDelete(store.root)
    plan = plan_cleanup(
        gate,
        environment="DEV",
        source_ids=(source["source_id"],),
        now=clock(),
        scope=lambda copy: bool(driver.path(copy)),
    )
    result = cleanup(
        gate,
        plan,
        approved=lambda digest: digest == plan.sha256,
        scope=lambda copy: bool(driver.path(copy)),
        delete={"local_checkpoint": driver},
    )
    assert not staging[0].exists() and any(receipt.outcome == "deleted" for receipt in result)


def test_claim_is_durable_before_ambiguous_write_failure(tmp_path):
    source, gate, clock = setup(tmp_path)
    feed, _ = adapter(source, gate)
    capture = feed.acquire(definition(source))
    gate.bind("fixture-run", capture.payload)
    locator = "s3://fixture-bucket/fixture-prefix/dev/fixture/fixture-run/raw.bin"
    with (
        pytest.raises(RuntimeError, match="ambiguous"),
        gate.copy_access("fixture-run", "raw_object", locator, write=True),
    ):
        # An independent restarted reader must already see the claim.
        with closing(sqlite3.connect(gate.ledger.path)) as observer:
            documents = observer.execute(
                "SELECT document FROM documents WHERE kind='copy'"
            ).fetchall()
            assert any(json.loads(row[0])["locator"] == locator for row in documents)
        raise RuntimeError("ambiguous provider response after write")
    assert any(copy.locator == locator for copy in gate.copies())


def test_nested_uncommitted_copy_claim_cannot_write_bytes(tmp_path):
    source, gate, clock = setup(tmp_path)
    feed, _ = adapter(source, gate)
    capture = feed.acquire(definition(source))
    gate.bind("fixture-run", capture.payload)
    with (
        gate.ledger.guard(),
        pytest.raises(PermissionError, match="IO_NESTING_INVALID"),
        gate.copy_access("fixture-run", "raw_object", "s3://fixture/raw", write=True),
    ):
        pytest.fail("uncommitted raw write")


def test_file_driver_refuses_escape_and_structured_metadata(tmp_path):
    source, gate, store, plan, driver = prepared(tmp_path)
    original = plan.copies[0]
    for path in (
        tmp_path / "outside.payload.json",
        store._payload_path("fixture-run", "normalized"),
        store.root,
    ):
        with pytest.raises(PermissionError, match="SCOPE_INVALID"):
            driver.path(replace(original, locator=path.resolve().as_uri()))


def test_object_driver_requires_exact_approved_source_and_artifact_key(tmp_path):
    source, gate, store, plan, file_driver = prepared(tmp_path)
    lease = gate.lease(plan.copies[0].lease_sha256)
    events = []

    class Client:
        def head_object(self, **kwargs):
            events.append(("head", kwargs))

        def delete_object(self, **kwargs):
            events.append(("delete", kwargs))

    driver = ObjectRawDelete(gate, Client(), bucket="fixture-bucket", prefix="fixture-prefix")
    url = f"s3://fixture-bucket/fixture-prefix/dev/{source['source_id']}/fixture-run/{lease.artifact_sha256}.bin"
    copy = RawCopy("DEV", source["source_id"], "raw_object", url, lease.sha256)
    for unsafe in (
        url.replace("fixture-bucket", "other-bucket"),
        url.replace("/dev/", "/prod/"),
        url.replace(source["source_id"], "scientific-source"),
        url.replace("fixture-run", "../escape"),
        url.replace("fixture-bucket/", "fixture-bucket//"),
    ):
        with pytest.raises(PermissionError, match="SCOPE_INVALID"):
            driver(replace(copy, locator=unsafe))
    assert events == []
    assert driver(copy)
    assert [event[0] for event in events] == ["head", "delete"]


def test_independent_expired_alias_cannot_delete_canonical_live_object(tmp_path):
    source, gate, clock = setup(tmp_path)
    feed, _ = adapter(source, gate)
    first = feed.acquire(definition(source))
    gate.bind("old-run", first.payload)
    old = gate.require_run("old-run")
    clock.value = "2026-10-02T00:00:00Z"
    fresh, _ = adapter(source, gate)
    second = fresh.acquire(definition(source))
    gate.bind("fresh-run", second.payload)
    live = gate.require_run("fresh-run")
    uri = f"s3://fixture-bucket/fixture-prefix/dev/{source['source_id']}/fresh-run/{live.artifact_sha256}.bin"
    canonical = RawCopy("DEV", source["source_id"], "raw_object", uri, live.sha256)
    aliased = replace(
        canonical,
        locator=uri.replace("fixture-bucket/", "fixture-bucket//"),
        lease_sha256=old.sha256,
    )
    # A separately recorded claim, bypassing the built-in writer, still fails closed.
    with gate.ledger.guard():
        gate.ledger.put("copy", canonical.sha256, canonical.__dict__)
        gate.ledger.put("copy", identity_hash(aliased.__dict__), aliased.__dict__)
    clock.value = END
    with pytest.raises(ValueError, match="COPY_INVALID"):
        plan_cleanup(
            gate,
            environment="DEV",
            source_ids=(source["source_id"],),
            now=clock(),
            scope=lambda copy: True,
        )
