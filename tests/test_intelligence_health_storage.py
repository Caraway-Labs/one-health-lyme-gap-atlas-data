"""Actual file checkpoint reads and durable journal restart, no live services."""

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from test_intelligence_feed import approved
from test_intelligence_health import NOW, run_evidence

from lyme_gap_atlas_data.ingestion.checkpoints import FileCheckpointStore
from lyme_gap_atlas_data.intelligence_health_storage import (
    IntelligenceHealthPersistence,
    SnowflakeAcquisitionContext,
    SnowflakeHealthJournal,
    SQLiteHealthJournal,
)


def fixture(tmp_path, *, failed=False):
    source = approved()
    state, rows, context = run_evidence(source, "fixture-run", NOW, failed=failed)
    checkpoints = FileCheckpointStore(tmp_path / "checkpoints")
    checkpoints.save(state)
    checkpoints.save_normalized(state.ingestion_run_id, list(rows))
    journal = SQLiteHealthJournal(tmp_path / "health.sqlite")
    from test_intelligence_raw_runtime import setup

    _, retention, _ = setup(tmp_path)
    retention.bind_source(
        state.ingestion_run_id,
        source,
        parser_version="rss-atom-v1",
        fetch_version="pinned-https-v1",
    )
    service = IntelligenceHealthPersistence(
        journal,
        source_lookup=lambda sid, version: source,
        context_lookup=lambda selected: context,
        run_binding_lookup=retention.source_binding,
    )
    return source, state, checkpoints, service


def events(journal):
    with closing(sqlite3.connect(journal.path)) as connection:
        return connection.execute("SELECT history FROM health_events ORDER BY sequence").fetchall()


def test_actual_checkpoint_restart_replay_and_telemetry_outage_preserve_health(
    tmp_path, monkeypatch
):
    source, state, checkpoints, service = fixture(tmp_path)
    monkeypatch.setattr(checkpoints, "load_payload", lambda *args: pytest.fail("raw XML read"))
    first = service.record_checkpoint(source, checkpoints, state.ingestion_run_id, observed_at=NOW)
    assert first.history.document["state"] == "healthy"
    journal = SQLiteHealthJournal(service.journal.path)
    restarted = IntelligenceHealthPersistence(
        journal,
        source_lookup=service.source_lookup,
        context_lookup=service.context_lookup,
        run_binding_lookup=service.run_binding_lookup,
    )
    emitted = []

    def outage(event):
        emitted.append(event)
        raise RuntimeError("private provider credential")

    repeated = restarted.record_checkpoint(
        source, checkpoints, state.ingestion_run_id, observed_at=NOW, emit=outage
    )
    assert repeated.history == first.history and len(events(journal)) == 1
    assert repeated.incident_key is None and repeated.escalation_owner is None
    assert repeated.history.document["policy_ref"] is None
    assert emitted and "credential" not in json.dumps(emitted)
    stored = json.dumps(events(journal))
    assert "xml_base64" not in stored and "canonical_url" not in stored and "title" not in stored


def test_failed_attempt_is_not_double_counted_after_restart(tmp_path):
    source, state, checkpoints, service = fixture(tmp_path, failed=True)
    first = service.record_checkpoint(source, checkpoints, state.ingestion_run_id, observed_at=NOW)
    second = service.record_checkpoint(source, checkpoints, state.ingestion_run_id, observed_at=NOW)
    assert first.history == second.history
    assert second.history.document["consecutive_failures"] == 1
    assert len(events(service.journal)) == 1
    assert not second.incident_key


def test_reconfigured_preload_failure_cannot_enter_new_registry_history(tmp_path):
    source, state, checkpoints, service = fixture(tmp_path, failed=True)
    changed = dict(source, registry_version=source["registry_version"] + 1)
    service.source_lookup = lambda *args: changed
    with pytest.raises(PermissionError, match="RUN_BINDING_MISMATCH"):
        service.record_checkpoint(changed, checkpoints, state.ingestion_run_id, observed_at=NOW)
    assert events(service.journal) == []


def test_unbound_legacy_preload_failure_is_rejected(tmp_path):
    source, state, checkpoints, service = fixture(tmp_path, failed=True)
    service.run_binding_lookup = None
    with pytest.raises(PermissionError, match="RUN_BINDING_REQUIRED"):
        service.record_checkpoint(source, checkpoints, state.ingestion_run_id, observed_at=NOW)
    assert events(service.journal) == []


def test_native_parser_survives_accepted_load_then_quality_failure_and_restart(tmp_path):
    from test_intelligence_native_metadata import records

    from lyme_gap_atlas_data.ingestion.types import (
        FailureCategory,
        RunStatus,
        Stage,
        StageCheckpoint,
        StageStatus,
    )

    source, state, checkpoints, service = fixture(tmp_path)
    rows = records()
    state.checkpoint(Stage.ACQUIRE).artifact_id = rows[0]["provenance"]["artifact_id"]
    state.checkpoint(Stage.LOAD).detail.update(record_count=len(rows), captures_inserted=len(rows))
    state.status = RunStatus.FAILED
    state.stages.append(
        StageCheckpoint(
            stage=Stage.QUALITY,
            status=StageStatus.FAILED,
            attempt_count=1,
            started_at=NOW,
            failure_category=FailureCategory.QUALITY,
            redacted_diagnostic_code="INJECTED_FAILURE",
        )
    )
    checkpoints.save(state)
    checkpoints.save_normalized(state.ingestion_run_id, rows)
    # Legacy accepted LOAD still has independently verified immutable capture evidence.
    service.run_binding_lookup = None
    result = service.record_checkpoint(source, checkpoints, state.ingestion_run_id, observed_at=NOW)
    assert result.history.document["parser_version"] == "rss-atom-native-v2"
    assert result.history.document["last_fetch_success_at"] == NOW
    reopened = SQLiteHealthJournal(service.journal.path)
    assert json.loads(events(reopened)[0][0])["document"]["parser_version"] == "rss-atom-native-v2"


def test_concurrent_duplicate_attempts_serialize_without_lost_history(tmp_path):
    source, state, checkpoints, service = fixture(tmp_path, failed=True)
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(
            workers.map(
                lambda unused: service.record_checkpoint(
                    source, checkpoints, state.ingestion_run_id, observed_at=NOW
                ),
                range(4),
            )
        )
    assert all(result.history.document["consecutive_failures"] == 1 for result in results)
    assert len(events(service.journal)) == 1


def test_out_of_order_or_conflicting_evidence_rolls_back_journal(tmp_path):
    source, state, checkpoints, service = fixture(tmp_path, failed=True)
    service.record_checkpoint(source, checkpoints, state.ingestion_run_id, observed_at=NOW)
    before = events(service.journal)
    changed = copy.deepcopy(state)
    changed.stages[-1].redacted_diagnostic_code = "FEED_ACCESS_FAILED"
    checkpoints.save(changed)
    with pytest.raises(ValueError, match="ATTEMPT_CONFLICT"):
        service.record_checkpoint(source, checkpoints, state.ingestion_run_id, observed_at=NOW)
    assert events(service.journal) == before
    with pytest.raises(ValueError, match="HISTORY_MISMATCH"):
        service.observe(source, observed_at="2026-09-30T00:00:00Z")
    assert events(service.journal) == before


def test_missing_policy_does_not_invent_stale_threshold_or_notifications(tmp_path):
    source, state, checkpoints, service = fixture(tmp_path)
    first = service.record_checkpoint(source, checkpoints, state.ingestion_run_id, observed_at=NOW)
    observed = service.observe(source, observed_at="2027-10-01T00:00:00Z")
    assert observed.history.document["state"] in {"healthy", "quiet"}
    assert observed.history.document["last_fetch_success_at"] == NOW
    assert observed.expected_cadence == source["cadence"]
    assert observed.incident_key is None and observed.escalation_owner is None
    assert observed.history.seen_revisions == first.history.seen_revisions


def test_source_authority_or_corrupt_journal_fail_closed(tmp_path):
    source, state, checkpoints, service = fixture(tmp_path)
    service.record_checkpoint(source, checkpoints, state.ingestion_run_id, observed_at=NOW)
    changed = dict(source, registry_version=2)
    with pytest.raises(PermissionError, match="SOURCE_AUTHORITY_REQUIRED"):
        service.observe(changed, observed_at=NOW)
    with closing(sqlite3.connect(service.journal.path)) as connection:
        connection.execute("UPDATE health_events SET checksum='bad'")
        connection.commit()
    with pytest.raises(ValueError, match="JOURNAL_INVALID"):
        service.observe(source, observed_at=NOW)


def test_production_requires_shared_journal(tmp_path):
    source, state, checkpoints, service = fixture(tmp_path)
    with pytest.raises(ValueError, match="SHARED_JOURNAL_REQUIRED"):
        IntelligenceHealthPersistence(
            service.journal,
            source_lookup=service.source_lookup,
            context_lookup=service.context_lookup,
            environment="PROD",
        )


@pytest.mark.parametrize(
    "role,database",
    [
        ("OH_LYME_DEV_OWNER", "ONE_HEALTH_LYME_GAP_ATLAS_DEV"),
        ("OH_LYME_DEV_RUNTIME", "ONE_HEALTH_LYME_GAP_ATLAS"),
    ],
)
def test_warehouse_wrong_role_or_alpha_refuses_before_any_health_sql(role, database):
    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def cursor(self):
            return self

        def execute(self, sql):
            calls.append(sql)

        def fetchall(self):
            return [(role, database, None)]

    store = SnowflakeHealthJournal(Connection, "DEV")
    with pytest.raises(PermissionError, match="WRITER_CONTEXT_REQUIRED"):
        store.transact("fixture-source", 1, lambda previous: pytest.fail("health reduced"))
    assert len(calls) == 1 and "CURRENT_ROLE" in calls[0]


def test_native_parser_version_survives_journal_round_trip(tmp_path):
    from test_intelligence_native_metadata import records

    from lyme_gap_atlas_data.intelligence_health import reduce_health
    from lyme_gap_atlas_data.intelligence_storage import WriteReceipt

    source, rows = approved(), records()
    journal = SQLiteHealthJournal(tmp_path / "health.sqlite")
    fetched_at = rows[0]["fetched_at"]
    first = journal.transact(
        source["source_id"],
        source["registry_version"],
        lambda previous: reduce_health(
            source,
            observed_at=fetched_at,
            fetched_at=fetched_at,
            items=tuple(rows),
            receipt=WriteReceipt(0, len(rows), 0),
            outcome="success",
            previous=previous,
        ),
    )
    restarted = SQLiteHealthJournal(journal.path)
    observed = restarted.transact(
        source["source_id"],
        source["registry_version"],
        lambda previous: reduce_health(source, observed_at=fetched_at, previous=previous),
    )
    assert first.history.document["parser_version"] == "rss-atom-native-v2"
    assert observed.history.document["parser_version"] == "rss-atom-native-v2"


def test_concrete_receipt_lookup_checks_role_hash_and_run_artifact_scope(tmp_path):
    from lyme_gap_atlas_data.intelligence_items import identity_hash

    source = approved()
    state, rows, context = run_evidence(source, "fixture-run", NOW)
    calls = []
    context_rows = [(identity_hash(context), json.dumps(context))]

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def cursor(self):
            return self

        def execute(self, sql, params=()):
            calls.append((sql, params))

        def fetchall(self):
            if "CURRENT_ROLE" in calls[-1][0]:
                return [("OH_LYME_DEV_RUNTIME", "ONE_HEALTH_LYME_GAP_ATLAS_DEV", None)]
            return context_rows

    reader = SnowflakeAcquisitionContext(Connection, "DEV")
    assert reader(state) == context
    assert calls[-1][1] == ("fixture-run", "artifact-fixture-run")
    assert "INTELLIGENCE_ACQUISITION_CONTEXTS" in calls[-1][0]
    assert all("INGESTION_RUN_PAYLOADS" not in sql for sql, params in calls)
    context_rows[0] = ("b" * 64, json.dumps(context))
    with pytest.raises(ValueError, match="CAPTURE_MISMATCH"):
        reader(state)


@pytest.mark.parametrize("guard_rows", [0, 1])
def test_warehouse_journal_serializes_and_commits_only_after_guard(guard_rows, tmp_path):
    from lyme_gap_atlas_data.intelligence_health import reduce_health

    calls = []
    stored = []

    class Connection:
        rowcount = guard_rows

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def cursor(self):
            return self

        def execute(self, sql, params=()):
            calls.append(sql)
            if sql.startswith("INSERT"):
                stored.append((params[4], params[3], params[2]))

        def fetchall(self):
            if "CURRENT_ROLE" in calls[-1]:
                return [("OH_LYME_DEV_RUNTIME", "ONE_HEALTH_LYME_GAP_ATLAS_DEV", None)]
            return stored[-2:][::-1]

        def autocommit(self, value):
            assert value is False

        def commit(self):
            calls.append("COMMIT")

        def rollback(self):
            calls.append("ROLLBACK")

    source = approved()
    store = SnowflakeHealthJournal(Connection, "DEV")

    def transform(previous):
        return reduce_health(source, observed_at=NOW, previous=previous)

    if not guard_rows:
        with pytest.raises(PermissionError, match="WRITE_GUARD_REQUIRED"):
            store.transact(source["source_id"], 1, transform)
        assert calls[-1] == "ROLLBACK" and stored == []
    else:
        first = store.transact(source["source_id"], 1, transform)
        second = store.transact(source["source_id"], 1, transform)
        assert first.history == second.history and len(stored) == 1
        assert "CURRENT_ROLE" in calls[0] and calls[-1] == "COMMIT"
        assert any("INTELLIGENCE_WRITE_GUARD" in sql for sql in calls)
