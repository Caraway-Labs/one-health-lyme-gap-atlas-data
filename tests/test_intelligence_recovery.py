"""Actual orchestrator/effects/store recovery against offline provider/SQL seams."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_intelligence_feed import FIXTURES, definition, fetch_adapter
from test_intelligence_storage import Connection, Cursor, Ledger

from lyme_gap_atlas_data.ingestion import IngestionOrchestrator, Tier
from lyme_gap_atlas_data.ingestion.checkpoints import SnowflakeCheckpointStore
from lyme_gap_atlas_data.ingestion.intelligence_checkpoints import (
    IntelligenceFileCheckpoints,
    IntelligenceSnowflakeCheckpoints,
)
from lyme_gap_atlas_data.ingestion.intelligence_effects import IntelligenceStageEffects
from lyme_gap_atlas_data.ingestion.intelligence_feed import FeedResponse
from lyme_gap_atlas_data.ingestion.types import RunState, Stage, StageStatus
from lyme_gap_atlas_data.intelligence_raw_runtime import FeedRawRetention, SQLiteRawLedger


class AcquisitionLedger(Ledger):
    def __init__(self) -> None:
        super().__init__()
        self.contexts.clear()
        self.artifacts.clear()
        self.endpoints.clear()
        self.requests: dict[str, tuple[str, str]] = {}
        self.fail_after_receipt_commit = False

    def connect(self) -> AcquisitionConnection:
        return AcquisitionConnection(self)


class AcquisitionConnection(Connection):
    def __init__(self, ledger: AcquisitionLedger) -> None:
        super().__init__(ledger)
        self.ledger: AcquisitionLedger = ledger
        self.raw_pending: tuple[dict[Any, Any], dict[Any, Any], dict[Any, Any]] | None = None
        self.receipt_inserted = False
        self.receipt_committed = False

    def autocommit(self, value: bool) -> None:
        assert value is False
        self.raw_pending = (
            copy.deepcopy(self.ledger.artifacts),
            copy.deepcopy(self.ledger.endpoints),
            copy.deepcopy(self.ledger.requests),
        )

    def cursor(self) -> AcquisitionCursor:
        return AcquisitionCursor(self)

    def commit(self) -> None:
        if self.raw_pending is not None:
            self.ledger.artifacts, self.ledger.endpoints, self.ledger.requests = self.raw_pending
            self.raw_pending = None
        else:
            super().commit()
            self.receipt_committed = self.receipt_inserted


class AcquisitionCursor(Cursor):
    def __init__(self, connection: AcquisitionConnection) -> None:
        super().__init__(connection)
        self.connection: AcquisitionConnection = connection

    def __exit__(self, *args: Any) -> None:
        connection = self.connection
        if connection.receipt_committed and connection.ledger.fail_after_receipt_commit:
            connection.ledger.fail_after_receipt_commit = False
            raise RuntimeError("private credential in provider cleanup")
        super().__exit__(*args)

    def execute(self, statement: str, params: tuple[Any, ...] = ()) -> None:
        sql = " ".join(statement.split()).upper()
        raw = self.connection.raw_pending
        if sql.startswith("MERGE INTO GOVERNANCE.INGESTION_REQUESTS"):
            assert raw is not None
            raw[2].setdefault(params[0], (params[1], params[4]))
        elif sql.startswith("MERGE INTO GOVERNANCE.RAW_ARTIFACTS"):
            assert raw is not None
            key = (params[0], params[1])
            assert raw[2][params[2]][0] == params[1]
            raw[0].setdefault(key, params[7])
            raw[1].setdefault(key, raw[2][params[2]][1])
        else:
            if sql.startswith("INSERT INTO GOVERNANCE.INTELLIGENCE_ACQUISITION_CONTEXTS"):
                self.connection.receipt_inserted = True
            super().execute(statement, params)


class Objects:
    def __init__(self) -> None:
        self.content: dict[str, bytes] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:
        prior = self.content.setdefault(Key, Body)
        assert prior == Body  # Identical raw bytes can share content-addressed storage.


class FailingCheckpoints(IntelligenceFileCheckpoints):
    def __init__(self, root: Path, database: AcquisitionLedger, failure: str) -> None:
        source = database.sources[0]
        retention = FeedRawRetention(
            SQLiteRawLedger(root / "retention.sqlite"),
            environment="DEV",
            source_lookup=lambda sid, version: source,
            policy_lookup=lambda selected: "fixture-raw30-reviewed",
            clock=lambda: datetime(2026, 10, 1, tzinfo=UTC).isoformat(),
        )
        super().__init__(root, retention)
        self.database, self.failure = database, failure

    def save_payload(self, run_id: str, payload: object) -> None:
        if self.failure == "payload":
            self.failure = ""
            raise RuntimeError("checkpoint unavailable")
        super().save_payload(run_id, payload)

    def save(self, state: RunState) -> None:
        self.database.runs[state.ingestion_run_id] = state.resource_key
        acquire = state.checkpoint(Stage.ACQUIRE)
        if self.failure == "checkpoint" and acquire and acquire.status is StageStatus.COMPLETED:
            self.failure = ""
            raise RuntimeError("checkpoint unavailable")
        super().save(state)


@pytest.mark.parametrize(
    "failure,second_minute", [("cleanup", 1), ("payload", 1), ("checkpoint", 1), ("cleanup", 0)]
)
def test_fresh_process_resume_reacquires_without_conflicting_with_committed_receipt(
    failure: str,
    second_minute: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = AcquisitionLedger()
    source = database.sources[0]
    raw = (FIXTURES / "rss/sample.xml").read_bytes()
    adapter, calls = fetch_adapter(source, [FeedResponse(200, {}, raw), FeedResponse(200, {}, raw)])
    original_acquire = adapter.acquire
    adapter.acquire = lambda selected, **kwargs: original_acquire(selected)

    class Clock(datetime):
        value = datetime(2026, 10, 1, tzinfo=UTC)

        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return cls.value

    monkeypatch.setattr("lyme_gap_atlas_data.ingestion.intelligence_feed.datetime", Clock)
    database.fail_after_receipt_commit = failure == "cleanup"
    checkpoints = FailingCheckpoints(tmp_path, database, failure)
    checkpoints.feed_retention.clock = lambda: Clock.now().isoformat()
    adapter.feed_retention = checkpoints.feed_retention
    effects = IntelligenceStageEffects(
        connection_factory=database.connect,
        spaces_client=Objects(),
        retention_allowed=lambda ref: True,
        artifact_policy_allowed=lambda ref, policy: True,
        feed_retention=checkpoints.feed_retention,
    )
    # Real orchestrator + real effects (including generic RAW registration) + real
    # store. Only HTTP, object store and warehouse are offline test seams.
    first = IngestionOrchestrator(
        store=checkpoints,
        adapter=adapter,
        fixture_dir=FIXTURES / "rss",
        effects=effects,
    ).run(definition(source), tier=Tier.A)
    assert first.status.value == "FAILED" and len(database.contexts) == 1
    first_receipts = copy.deepcopy(database.contexts)
    first_artifact = next(iter(first_receipts))[1]
    assert not database.captures
    if failure in {"cleanup", "payload"}:
        assert checkpoints.load_payload(first.ingestion_run_id) is None
    Clock.value = datetime(2026, 10, 1, 0, second_minute, tzinfo=UTC)
    resumed = IngestionOrchestrator(
        store=IntelligenceFileCheckpoints(tmp_path, checkpoints.feed_retention),
        adapter=adapter,
        fixture_dir=FIXTURES / "rss",
        effects=effects,
    ).resume(first.ingestion_run_id, definition=definition(source))
    assert resumed.status.value == "SUCCEEDED" and len(calls) == 2
    assert len(database.contexts) == len(database.artifacts) == len(database.requests) == 2
    assert all(database.contexts[key] == value for key, value in first_receipts.items())
    assert len(database.captures) == len(database.revisions) == 2
    items = [json.loads(value[1]) for value in database.captures.values()]
    assert all(item["provenance"]["artifact_id"] != first_artifact for item in items)
    assert all(item["fetched_at"] == f"2026-10-01T00:{second_minute:02}:00Z" for item in items)
    assert len({context[0] for context in database.contexts.values()}) == 2
    assert (
        len({json.loads(context[1])["attempt_id"] for context in database.contexts.values()}) == 2
    )
    # A second resume sees durable stage completion and performs no extra fetch/write.
    IngestionOrchestrator(
        store=IntelligenceFileCheckpoints(tmp_path, checkpoints.feed_retention),
        adapter=adapter,
        effects=effects,
    ).resume(
        first.ingestion_run_id,
        definition=definition(source),
    )
    assert len(calls) == 2 and len(database.contexts) == 2 and len(database.captures) == 2


class ImmutablePayloadSQL:
    """Independent append-only SQL seam for the real Snowflake save/load methods."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, str]] = {}
        self.reads = 0

    def connect(self) -> Any:
        database = self

        class Connection:
            def __enter__(self) -> Any:
                self.pending = copy.deepcopy(database.rows)
                return self

            def __exit__(self, *args: Any) -> None:
                pass

            def autocommit(self, value: bool) -> None:
                assert value is False

            def commit(self) -> None:
                database.rows = self.pending

            def cursor(self) -> Any:
                connection = self

                class Cursor:
                    def __enter__(self) -> Any:
                        return self

                    def __exit__(self, *args: Any) -> None:
                        pass

                    def execute(self, statement: str, params: tuple[Any, ...]) -> None:
                        sql = " ".join(statement.split()).upper()
                        if sql.startswith("MERGE INTO GOVERNANCE.INGESTION_RUN_PAYLOADS"):
                            connection.pending.setdefault(params[0], (params[1], params[2]))
                        elif sql.startswith("SELECT VALUE_SHA256"):
                            row = connection.pending.get(params[0])
                            self.row = (row[1],) if row else None
                        elif sql.startswith("SELECT PAYLOAD, VALUE_SHA256"):
                            database.reads += 1
                            self.row = database.rows.get(params[0])
                        else:
                            pytest.fail("Unexpected immutable checkpoint SQL")

                    def fetchone(self) -> Any:
                        return self.row

                return Cursor()

        return Connection()


@pytest.mark.parametrize("expired", [False, True])
def test_committed_immutable_payload_recovers_before_refetch_and_keeps_original_lease(
    tmp_path: Path,
    expired: bool,
) -> None:
    database = AcquisitionLedger()
    sql = ImmutablePayloadSQL()
    source = database.sources[0]
    raw = (FIXTURES / "rss/sample.xml").read_bytes()
    adapter, calls = fetch_adapter(source, [FeedResponse(200, {}, raw)])
    original_acquire = adapter.acquire
    adapter.acquire = lambda selected, **kwargs: original_acquire(selected)

    class Checkpoints(FailingCheckpoints, IntelligenceSnowflakeCheckpoints):
        # Exercise production immutable serialization, SQL and guarded reads,
        # not FileCheckpointStore's overwrite behavior. Stage metadata alone
        # uses the existing file seam to inject the post-payload save failure.
        save_payload = IntelligenceSnowflakeCheckpoints.save_payload
        load_payload = IntelligenceSnowflakeCheckpoints.load_payload
        recover_acquisition_payload = IntelligenceSnowflakeCheckpoints.recover_acquisition_payload
        _payload_locator = IntelligenceSnowflakeCheckpoints._payload_locator
        _save_json_document = SnowflakeCheckpointStore._save_json_document
        _load_json_document = SnowflakeCheckpointStore._load_json_document

    checkpoints = Checkpoints(tmp_path, database, "checkpoint")
    checkpoints._connection_factory = sql.connect
    adapter.feed_retention = checkpoints.feed_retention
    effects = IntelligenceStageEffects(
        connection_factory=database.connect,
        spaces_client=Objects(),
        retention_allowed=lambda ref: True,
        artifact_policy_allowed=lambda ref, policy: True,
        feed_retention=checkpoints.feed_retention,
    )
    first = IngestionOrchestrator(
        store=checkpoints,
        adapter=adapter,
        fixture_dir=FIXTURES / "rss",
        effects=effects,
    ).run(definition(source), tier=Tier.A)
    assert first.status.value == "FAILED" and len(calls) == 1
    committed = copy.deepcopy(sql.rows)
    leases = checkpoints.feed_retention.ledger.documents("lease")
    contexts = copy.deepcopy(database.contexts)
    original = json.loads(sql.rows[first.ingestion_run_id][0])
    original_lease = checkpoints.feed_retention.require_run(first.ingestion_run_id)

    fresh = Checkpoints(tmp_path, database, "")
    fresh._connection_factory = sql.connect
    fresh.feed_retention.clock = lambda: (
        "2026-11-02T00:00:00Z" if expired else "2026-10-02T00:00:00Z"
    )
    adapter.feed_retention = effects.feed_retention = fresh.feed_retention
    resumed = IngestionOrchestrator(store=fresh, adapter=adapter, effects=effects).resume(
        first.ingestion_run_id,
        definition=definition(source),
    )
    if expired:
        assert resumed.status.value == "FAILED" and len(calls) == 1
        assert sql.reads == 0 and sql.rows == committed and not database.captures
        assert fresh.feed_retention.ledger.documents("lease") == leases
        return
    assert resumed.status.value == "SUCCEEDED" and len(calls) == 1
    assert sql.reads == 1 and sql.rows == committed and database.contexts == contexts
    assert fresh.feed_retention.ledger.documents("lease") == leases
    assert fresh.feed_retention.require_run(first.ingestion_run_id) == original_lease
    acquired = resumed.checkpoint(Stage.ACQUIRE)
    assert acquired.artifact_id == original["_acquisition_lineage"]["artifact_id"]
    assert acquired.artifact_sha256 == original["artifact_sha256"]
    assert acquired.detail["recovered_committed_acquisition"] is True
    items = [json.loads(value[1]) for value in database.captures.values()]
    assert all(item["fetched_at"] == original["fetched_at"] for item in items)
    assert all(item["provenance"]["artifact_id"] == acquired.artifact_id for item in items)
    changed = {**original, "unexpected_new_value": "cannot overwrite"}
    with pytest.raises(ValueError, match="checkpoint checksum mismatch"):
        fresh.save_payload(first.ingestion_run_id, changed)
    assert sql.rows == committed


def test_completed_normalize_replay_rejects_wrong_projection_before_store_write(
    tmp_path: Path,
) -> None:
    database = AcquisitionLedger()
    source = database.sources[0]
    raw = (FIXTURES / "rss/sample.xml").read_bytes()
    adapter, calls = fetch_adapter(source, [FeedResponse(200, {}, raw)])
    original_acquire = adapter.acquire
    adapter.acquire = lambda selected, **kwargs: original_acquire(selected)
    checkpoints = FailingCheckpoints(tmp_path, database, "")
    adapter.feed_retention = checkpoints.feed_retention
    effects = IntelligenceStageEffects(
        connection_factory=database.connect,
        spaces_client=Objects(),
        retention_allowed=lambda ref: True,
        artifact_policy_allowed=lambda ref, policy: True,
        feed_retention=checkpoints.feed_retention,
    )
    first = IngestionOrchestrator(
        store=checkpoints,
        adapter=adapter,
        fixture_dir=FIXTURES / "rss",
        effects=effects,
    ).run(definition(source), tier=Tier.A, fail_after_stage="NORMALIZE")
    assert first.status.value == "FAILED" and len(calls) == 1
    assert first.checkpoint(Stage.NORMALIZE).status is StageStatus.COMPLETED
    saved = checkpoints.load_normalized(first.ingestion_run_id)
    assert saved and all(item["contract_version"] == "1.0.0" for item in saved)
    assert not database.revisions and not database.captures
    target = replace(definition(source), destination="PRESENTATION.INTELLIGENCE_FEED_V2")
    resumed = IngestionOrchestrator(store=checkpoints, adapter=adapter, effects=effects).resume(
        first.ingestion_run_id,
        definition=target,
    )
    assert resumed.status.value == "FAILED" and len(calls) == 1
    assert resumed.checkpoint(Stage.NORMALIZE).status is StageStatus.COMPLETED
    assert resumed.checkpoint(Stage.LOAD).status is StageStatus.FAILED
    assert not database.revisions and not database.captures
    assert checkpoints.load_normalized(first.ingestion_run_id) == saved
