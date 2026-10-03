"""Offline actual checkpoint/restart/cache boundaries, with no real deletion."""

from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path

import pytest
from test_intelligence_feed import FIXTURES, approved, definition

from lyme_gap_atlas_data.ingestion.artifact_replay import ArtifactMember
from lyme_gap_atlas_data.ingestion.intelligence_checkpoints import (
    IntelligenceFileCheckpoints,
    IntelligenceMemoryCheckpoints,
    IntelligenceSnowflakeCheckpoints,
)
from lyme_gap_atlas_data.ingestion.intelligence_feed import FeedResponse, IntelligenceFeedAdapter
from lyme_gap_atlas_data.ingestion.orchestrator import IngestionOrchestrator
from lyme_gap_atlas_data.ingestion.runtime import NoopStageEffects
from lyme_gap_atlas_data.ingestion.types import Stage, Tier
from lyme_gap_atlas_data.intelligence_raw_runtime import FeedRawRetention, SQLiteRawLedger
from lyme_gap_atlas_data.settings import PipelineSettings

RAW = (FIXTURES / "rss/sample.xml").read_bytes()
START = "2026-10-01T00:00:00Z"
END = "2026-10-31T00:00:00Z"


class Clock:
    value = START

    def __call__(self):
        return self.value


def setup(tmp_path, clock=None):
    clock = clock or Clock()
    source = approved()
    gate = FeedRawRetention(
        SQLiteRawLedger(tmp_path / "ledger.sqlite"),
        environment="DEV",
        source_lookup=lambda source_id, version: source,
        policy_lookup=lambda selected: "fixture-raw30-reviewed",
        clock=clock,
    )
    return source, gate, clock


def adapter(source, gate, responses=None):
    replies = iter(responses or [FeedResponse(200, {"etag": '"fixture"'}, RAW)])
    requests = []

    def request(url, address, headers, budget, timeout):
        requests.append(dict(headers))
        return next(replies)

    return IntelligenceFeedAdapter(
        registry_lookup=lambda sid, version: source,
        retention_allowed=lambda ref: True,
        request=request,
        resolve=lambda *args: ("1.1.1.1",),
        sleep=lambda seconds: None,
        feed_retention=gate,
    ), requests


@pytest.mark.parametrize("memory", [False, True])
def test_expired_in_process_resume_refuses_before_raw_read(tmp_path, monkeypatch, memory):
    source, gate, clock = setup(tmp_path)
    store = (
        IntelligenceMemoryCheckpoints(gate)
        if memory
        else IntelligenceFileCheckpoints(tmp_path / "checkpoints", gate)
    )
    feed, requests = adapter(source, gate)
    orchestrator = IngestionOrchestrator(store, adapter=feed, effects=NoopStageEffects())
    state = orchestrator.run(definition(source), tier=Tier.B, fail_after_stage="ACQUIRE")
    assert state.checkpoint(Stage.ACQUIRE).status.value == "COMPLETED"
    clock.value = END
    monkeypatch.setattr(store, "load_payload", lambda run: pytest.fail("expired payload read"))
    monkeypatch.setattr(
        store, "load_binary_artifact", lambda run: pytest.fail("expired binary fallback")
    )
    resumed = orchestrator.resume(state.ingestion_run_id, definition=definition(source))
    assert resumed.status.value == "FAILED" and resumed.next_action == "new-approved-feed-run"
    assert resumed.checkpoint(Stage.VALIDATE).redacted_diagnostic_code == "INTELLIGENCE_RAW_EXPIRED"
    assert state.ingestion_run_id not in orchestrator._payloads
    assert len(requests) == 1


def test_actual_file_restart_before_deadline_succeeds_and_preserves_lease(tmp_path):
    source, gate, clock = setup(tmp_path)
    store = IntelligenceFileCheckpoints(tmp_path / "checkpoints", gate)
    feed, _ = adapter(source, gate)
    state = IngestionOrchestrator(store, adapter=feed, effects=NoopStageEffects()).run(
        definition(source), tier=Tier.B, fail_after_stage="ACQUIRE"
    )
    old = gate.require_run(state.ingestion_run_id)
    # New ledger connection, checkpoint object, adapter and orchestrator.
    source2, gate2, clock2 = setup(tmp_path)
    clock2.value = "2026-10-30T23:59:59.999999Z"
    store2 = IntelligenceFileCheckpoints(tmp_path / "checkpoints", gate2)
    feed2, requests = adapter(source2, gate2)
    resumed = IngestionOrchestrator(store2, adapter=feed2, effects=NoopStageEffects()).resume(
        state.ingestion_run_id, definition=definition(source2)
    )
    assert resumed.status.value == "SUCCEEDED" and requests == []
    assert gate2.require_run(state.ingestion_run_id).sha256 == old.sha256
    assert store2.load_normalized(state.ingestion_run_id)


def test_expired_restart_refuses_file_bytes_but_normalized_metadata_survives(tmp_path, monkeypatch):
    source, gate, clock = setup(tmp_path)
    store = IntelligenceFileCheckpoints(tmp_path / "checkpoints", gate)
    feed, _ = adapter(source, gate)
    state = IngestionOrchestrator(store, adapter=feed, effects=NoopStageEffects()).run(
        definition(source), tier=Tier.B, fail_after_stage="NORMALIZE"
    )
    normalized = store.load_normalized(state.ingestion_run_id)
    source2, gate2, clock2 = setup(tmp_path)
    clock2.value = END
    store2 = IntelligenceFileCheckpoints(tmp_path / "checkpoints", gate2)
    feed2, requests = adapter(source2, gate2)
    original_read = Path.read_text

    def read(path, *args, **kwargs):
        if path.name.endswith(".payload.json"):
            pytest.fail("expired XML checkpoint loaded")
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    resumed = IngestionOrchestrator(store2, adapter=feed2, effects=NoopStageEffects()).resume(
        state.ingestion_run_id, definition=definition(source2)
    )
    assert resumed.status.value == "FAILED" and requests == []
    assert store2.load_normalized(state.ingestion_run_id) == normalized


@pytest.mark.parametrize("memory", [False, True])
def test_direct_payload_binary_and_member_reads_are_guarded(tmp_path, monkeypatch, memory):
    source, gate, clock = setup(tmp_path)
    feed, _ = adapter(source, gate)
    capture = feed.acquire(definition(source))
    store = (
        IntelligenceMemoryCheckpoints(gate)
        if memory
        else IntelligenceFileCheckpoints(tmp_path / "checkpoints", gate)
    )
    store.save_payload("fixture-run", capture.payload)
    digest = hashlib.sha256(RAW).hexdigest()
    store.save_binary_artifact("fixture-run", RAW, digest)
    member = ArtifactMember(
        "fixture-run",
        "feed.xml",
        "source_payload",
        "fixture-artifact",
        source["fetch_location"],
        "application/xml",
        digest,
        len(RAW),
    )
    store.save_artifact_member(member, RAW)
    assert store.load_payload("fixture-run") and store.load_binary_artifact("fixture-run") == RAW
    clock.value = END
    for operation in (
        lambda: store.load_payload("fixture-run"),
        lambda: store.load_binary_artifact("fixture-run"),
        lambda: store.load_artifact_member("fixture-run", name="feed.xml"),
        lambda: store.save_payload("fixture-run", capture.payload),
    ):
        with pytest.raises(PermissionError, match="RAW_EXPIRED"):
            operation()


def test_304_keeps_initial_deadline_then_expired_cache_is_dropped_for_fresh_200(tmp_path):
    source, gate, clock = setup(tmp_path)
    feed, _ = adapter(source, gate)
    initial = feed.acquire(definition(source))
    cache = feed.retained_cache(initial.payload, "fixture-artifact")
    clock.value = "2026-10-30T00:00:00Z"
    repoll, requests = adapter(source, gate, [FeedResponse(304, {}, b"")])
    repoll.cache, repoll.cache_allowed = cache, lambda saved: True
    result = repoll.acquire(definition(source))
    assert result.payload["raw_lease_sha256"] == initial.payload["raw_lease_sha256"]
    assert gate.lease(result.payload["raw_lease_sha256"]).expires_at == END
    assert requests[0]["If-None-Match"] == '"fixture"'
    clock.value = END
    reacquire, requests2 = adapter(source, gate)
    reacquire.cache, reacquire.cache_allowed = cache, lambda saved: True
    fresh = reacquire.acquire(definition(source))
    assert reacquire.cache is None and "If-None-Match" not in requests2[0]
    assert fresh.payload["raw_lease_sha256"] != initial.payload["raw_lease_sha256"]
    assert gate.lease(fresh.payload["raw_lease_sha256"]).expires_at == "2026-11-30T00:00:00Z"


def test_expired_cache_unconditional_304_fails_not_quiet(tmp_path):
    source, gate, clock = setup(tmp_path)
    feed, _ = adapter(source, gate)
    capture = feed.acquire(definition(source))
    cache = feed.retained_cache(capture.payload, "fixture-artifact")
    clock.value = END
    stale, _ = adapter(source, gate, [FeedResponse(304, {}, b"")])
    stale.cache, stale.cache_allowed = cache, lambda saved: True
    with pytest.raises(Exception, match="304"):
        stale.acquire(definition(source))


def test_expired_warehouse_payload_and_object_paths_do_no_sql_or_object_read(tmp_path):
    source, gate, clock = setup(tmp_path)
    feed, _ = adapter(source, gate)
    capture = feed.acquire(definition(source))
    gate.bind("fixture-run", capture.payload)
    clock.value = END
    store = IntelligenceSnowflakeCheckpoints(
        gate, connection_factory=lambda: pytest.fail("expired raw SQL"), spaces_client=object()
    )
    for operation in (
        lambda: store.load_payload("fixture-run"),
        lambda: store.load_source_artifact("fixture-run"),
        lambda: store.load_artifact_member("fixture-run", name="feed.xml"),
    ):
        with pytest.raises(PermissionError, match="RAW_EXPIRED"):
            operation()


def test_legacy_or_forged_lease_and_revoked_rights_fail_before_decode(tmp_path, monkeypatch):
    source, gate, clock = setup(tmp_path)
    feed, _ = adapter(source, gate)
    capture = feed.acquire(definition(source))
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.intelligence_feed.base64.b64decode",
        lambda *args, **kwargs: pytest.fail("unproven bytes decoded"),
    )
    for digest in (None, "c" * 64):
        forged = dict(capture.payload, raw_lease_sha256=digest)
        with pytest.raises(PermissionError):
            feed.normalize(definition(source), forged)
    gate.policy_lookup = lambda selected: "revoked-policy"
    with pytest.raises(PermissionError, match="RIGHTS_REQUIRED"):
        feed.normalize(definition(source), capture.payload)


def test_unissued_context_or_new_lease_cannot_renew_old_payload(tmp_path, monkeypatch):
    source, gate, clock = setup(tmp_path)
    feed, _ = adapter(source, gate)
    initial = feed.acquire(definition(source))
    clock.value = "2026-10-02T00:00:00Z"
    fresh_feed, _ = adapter(source, gate)
    fresh = fresh_feed.acquire(definition(source))
    forged_context = copy.deepcopy(initial.payload)
    forged_context["fetched_at"] = clock.value
    forged_context["source_context"]["fetched_at"] = clock.value
    forged_lease = dict(initial.payload, raw_lease_sha256=fresh.payload["raw_lease_sha256"])
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.intelligence_feed.base64.b64decode",
        lambda *args, **kwargs: pytest.fail("unissued payload decoded"),
    )
    for payload in (forged_context, forged_lease):
        with pytest.raises(PermissionError, match="CAPTURE_MISMATCH"):
            feed.normalize(definition(source), payload)


def test_buffer_release_is_idempotent_and_released_locator_cannot_be_reused(tmp_path):
    source, gate, clock = setup(tmp_path)
    feed, _ = adapter(source, gate)
    store = IntelligenceMemoryCheckpoints(gate)
    store.save_payload("fixture-run", feed.acquire(definition(source)).payload)
    locator = store._locator("fixture-run", "payload")
    gate.release_buffer(locator)
    receipts = gate.ledger.documents("buffer_release")
    clock.value = "2026-10-02T00:00:00Z"
    gate.release_buffer(locator)
    gate.close()
    assert gate.ledger.documents("buffer_release") == receipts
    assert not store._payloads
    with (
        pytest.raises(PermissionError, match="BUFFER_RELEASED"),
        gate.copy_access("fixture-run", "checkpoint_payload", locator, write=True),
    ):
        pytest.fail("released buffer reused")


def test_production_cannot_use_unshared_local_ledger(tmp_path):
    source, gate, clock = setup(tmp_path)
    with pytest.raises(ValueError, match="SHARED_LEDGER_REQUIRED"):
        FeedRawRetention(
            gate.ledger,
            environment="PROD",
            source_lookup=gate.source_lookup,
            policy_lookup=gate.policy_lookup,
        )


def test_new_failed_write_claim_cannot_authorize_old_expired_checkpoint(tmp_path, monkeypatch):
    source, gate, clock = setup(tmp_path)
    feed, _ = adapter(source, gate)
    initial = feed.acquire(definition(source))
    store = IntelligenceFileCheckpoints(tmp_path / "checkpoints", gate)
    store.save_payload("fixture-run", initial.payload)
    clock.value = END
    fresh_feed, _ = adapter(source, gate)
    fresh = fresh_feed.acquire(definition(source))
    gate.bind("fixture-run", fresh.payload)

    def failed_replace(*args):
        raise RuntimeError("ambiguous write before replacement")

    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.intelligence_checkpoints.os.replace", failed_replace
    )
    with pytest.raises(RuntimeError, match="ambiguous"):
        store.save_payload("fixture-run", fresh.payload)
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: pytest.fail("old XML read"))
    with pytest.raises(PermissionError, match="WRITE_COMPLETION_REQUIRED"):
        store.load_payload("fixture-run")


@pytest.mark.parametrize("role", ["OH_LYME_DEV_RUNTIME", "OH_LYME_DEV_OWNER"])
def test_warehouse_object_replay_checks_role_and_committed_claim_before_get(tmp_path, role):
    source, gate, clock = setup(tmp_path)
    feed, _ = adapter(source, gate)
    capture = feed.acquire(definition(source))
    gate.bind("fixture-run", capture.payload)
    digest = hashlib.sha256(RAW).hexdigest()
    uri = f"s3://fixture-bucket/fixture-prefix/dev/{source['source_id']}/fixture-run/{digest}.bin"
    with gate.copy_access("fixture-run", "raw_object", uri, write=True):
        pass
    events = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params=()):
            events.append(sql)

        def fetchall(self):
            return [(role, "ONE_HEALTH_LYME_GAP_ATLAS_DEV", None)]

        def fetchone(self):
            return (uri, digest)

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def cursor(self):
            return Cursor()

    class Objects:
        def get_object(self, **kwargs):
            assert gate.ledger.in_guard()
            assert any(claim.locator == uri for claim in gate.copies())
            events.append("GET")
            return {"Body": io.BytesIO(RAW)}

    store = IntelligenceSnowflakeCheckpoints(
        gate,
        connection_factory=Connection,
        spaces_client=Objects(),
        settings=PipelineSettings(spaces_bucket="fixture-bucket", spaces_prefix="fixture-prefix"),
    )
    if role.endswith("OWNER"):
        with pytest.raises(PermissionError, match="WRITER_CONTEXT_REQUIRED"):
            store.load_source_artifact("fixture-run")
        assert len(events) == 1 and "CURRENT_ROLE" in events[0]
    else:
        assert store.load_source_artifact("fixture-run") == RAW
        assert "CURRENT_ROLE" in events[0] and "RAW_ARTIFACTS" in events[1]
        assert events[-1] == "GET"


def test_existing_artifact_put_has_durable_claim_before_provider_io(tmp_path):
    import sqlite3
    from contextlib import closing

    from lyme_gap_atlas_data.ingestion.runtime import SnowflakeStageEffects
    from lyme_gap_atlas_data.ingestion.types import RunState, RunStatus

    source, gate, clock = setup(tmp_path)
    feed, _ = adapter(source, gate)
    acquired = feed.acquire(definition(source))
    gate.bind("fixture-run", acquired.payload)
    events = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params=()):
            events.append("SQL")

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def cursor(self):
            return Cursor()

        def autocommit(self, value):
            pass

        def commit(self):
            events.append("COMMIT")

    class Objects:
        def put_object(self, **kwargs):
            uri = f"s3://{kwargs['Bucket']}/{kwargs['Key']}"
            assert gate.ledger.in_guard()
            with closing(sqlite3.connect(gate.ledger.path)) as observer:
                claims = observer.execute("SELECT document FROM documents WHERE kind='copy'")
                assert any(json.loads(row[0])["locator"] == uri for row in claims)
            assert kwargs["Body"] == RAW
            events.append("PUT")

    effects = SnowflakeStageEffects(
        PipelineSettings(spaces_bucket="fixture-bucket", spaces_prefix="fixture-prefix"),
        connection_factory=Connection,
        spaces_client=Objects(),
    )
    state = RunState("fixture-run", source["source_id"], 1, Tier.B, RunStatus.RUNNING)
    effects._register_artifact(
        definition(source),
        state,
        acquired,
        raw_artifact_guard=lambda uri: gate.copy_access(
            "fixture-run", "raw_object", uri, write=True
        ),
    )
    assert events[0] == "PUT" and events[-1] == "COMMIT"
