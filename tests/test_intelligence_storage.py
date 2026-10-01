"""Storage outcomes against an independent transactional ledger double.

SQL/role/concurrency verification against actual Snowflake remains a release gate.
"""

from __future__ import annotations

import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from test_intelligence_feed import FIXTURES, approved, definition, fetch_adapter

from lyme_gap_atlas_data.ingestion import IngestionOrchestrator, InMemoryCheckpointStore, Tier
from lyme_gap_atlas_data.ingestion.intelligence_effects import IntelligenceStageEffects
from lyme_gap_atlas_data.ingestion.intelligence_feed import FeedResponse, acquisition_context
from lyme_gap_atlas_data.intelligence_items import identity_hash, normalize_item
from lyme_gap_atlas_data.intelligence_storage import (
    IntelligenceStorageError,
    IntelligenceStore,
    WriteReceipt,
    capture_id,
)


class Ledger:
    def __init__(self) -> None:
        self.sources: list[dict[str, Any]] = [approved()]
        self.runs = {"fixture-run": "synthetic-publication"}
        self.artifacts = {("fixture-artifact", "fixture-run"): "a" * 64}
        self.endpoints = {("fixture-artifact", "fixture-run"): "https://example.org/feed.xml"}
        self.contexts: dict[tuple[str, str], tuple[str, str]] = {}
        self.pin("fixture-run", "fixture-artifact", self.sources[0], "2026-10-01T00:00:00Z")
        self.revisions: dict[tuple[str, str], tuple[str, str]] = {}
        self.captures: dict[str, tuple[str, str]] = {}
        self.role = "OH_LYME_DEV_RUNTIME"
        self.database = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
        self.guard_rows = 1
        self.source_hash_valid = True
        self.fail_on_capture = False
        self.fail_commit = False
        self.lock = threading.Lock()
        self.events: list[str] = []
        self.fail_at: str | None = None

    def pin(self, run_id: str, artifact_id: str, source: dict[str, Any], fetched_at: str) -> None:
        context = acquisition_context(
            definition(source),
            source,
            effective_url=source["fetch_location"],
            fetched_at=fetched_at,
            artifact_sha256=self.artifacts[(artifact_id, run_id)],
            capture_mode="https",
        )
        self.contexts[(run_id, artifact_id)] = (identity_hash(context), json.dumps(context))

    def fail(self, stage: str) -> None:
        if self.fail_at == stage:
            raise RuntimeError("private warehouse statement and credential")

    def connect(self) -> Connection:
        self.fail("factory")
        return Connection(self)


class Connection:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self.active = False
        self.locked = False
        self.pending: tuple[Any, Any] | None = None

    def __enter__(self) -> Connection:
        self.ledger.fail("connection_enter")
        return self

    def __exit__(self, *args: Any) -> None:
        if self.locked:
            self.rollback()
        self.ledger.fail("connection_exit")

    def cursor(self) -> Cursor:
        self.ledger.fail("cursor")
        return Cursor(self)

    def commit(self) -> None:
        if self.ledger.fail_commit:
            raise RuntimeError("private warehouse statement and credential")
        self.ledger.revisions, self.ledger.captures, self.ledger.contexts = self.pending
        self.ledger.events.append("commit")
        self.active = False
        if self.locked:
            self.ledger.lock.release()
            self.locked = False

    def rollback(self) -> None:
        self.pending = None
        self.active = False
        self.ledger.events.append("rollback")
        if self.locked:
            self.ledger.lock.release()
            self.locked = False
        self.ledger.fail("rollback")


class Cursor:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.rows: list[Any] = []
        self.rowcount = 0

    def __enter__(self) -> Cursor:
        self.connection.ledger.fail("cursor_enter")
        return self

    def __exit__(self, *args: Any) -> None:
        self.connection.ledger.fail("cursor_exit")

    def fetchall(self) -> list[Any]:
        return self.rows

    def execute(self, statement: str, params: tuple[Any, ...] = ()) -> None:
        sql = " ".join(statement.split()).upper()
        database = self.connection.ledger
        self.rows = []
        if sql.startswith("SELECT CURRENT_ROLE"):
            database.fail("context")
            self.rows = [(database.role, database.database, 1 if self.connection.active else None)]
        elif sql.startswith("ALTER SESSION"):
            database.fail("setup")
            assert not self.connection.active
            assert "LOCK_TIMEOUT=5" in sql
        elif sql == "BEGIN TRANSACTION":
            database.fail("begin")
            self.connection.active = True
            database.events.append("begin")
        elif sql.startswith("UPDATE GOVERNANCE.INTELLIGENCE_WRITE_GUARD"):
            assert self.connection.active
            database.lock.acquire(timeout=2)
            self.connection.locked = True
            self.rowcount = database.guard_rows
            self.connection.pending = (
                copy.deepcopy(database.revisions),
                copy.deepcopy(database.captures),
                copy.deepcopy(database.contexts),
            )
            database.events.append("guard")
        elif "FROM GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS S" in sql:
            database.fail("lookup")
            matching = [
                s for s in database.sources if (s["source_id"], s["registry_version"]) == params
            ]
            latest = max(
                (s["registry_version"] for s in database.sources if s["source_id"] == params[0]),
                default=0,
            )
            self.rows = [
                (identity_hash(s) if database.source_hash_valid else "b" * 64, json.dumps(s))
                for s in matching
                if s["registry_version"] == latest
            ]
        elif "FROM GOVERNANCE.INGESTION_RUNS" in sql:
            self.rows = [(database.runs[params[0]],)] if params[0] in database.runs else []
        elif "FROM GOVERNANCE.RAW_ARTIFACTS" in sql:
            self.rows = (
                [
                    (database.artifacts[params], database.endpoints.get(params))
                    if "R.ENDPOINT" in sql
                    else (database.artifacts[params],)
                ]
                if params in database.artifacts
                else []
            )
        elif "FROM GOVERNANCE.INTELLIGENCE_ACQUISITION_CONTEXTS" in sql:
            value = self.connection.pending[2].get(params)
            self.rows = [value] if value else []
        elif sql.startswith("INSERT INTO GOVERNANCE.INTELLIGENCE_ACQUISITION_CONTEXTS"):
            assert self.connection.locked
            self.connection.pending[2][params[:2]] = params[2:]
        elif "FROM CONFORMED.INTELLIGENCE_ITEM_REVISIONS" in sql:
            assert self.connection.locked
            value = self.connection.pending[0].get(params)
            self.rows = [value] if value else []
        elif sql.startswith("INSERT INTO CONFORMED.INTELLIGENCE_ITEM_REVISIONS"):
            assert self.connection.locked
            self.connection.pending[0][params[:2]] = params[2:]
        elif "FROM GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES" in sql:
            assert self.connection.locked
            value = self.connection.pending[1].get(params[0])
            self.rows = [value] if value else []
        elif sql.startswith("INSERT INTO GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES"):
            assert self.connection.locked
            if database.fail_on_capture:
                raise RuntimeError("private provider identifier")
            assert params[6] in database.runs
            assert database.artifacts[(params[7], params[6])] == params[8]
            self.connection.pending[1][params[0]] = (params[9], params[10])
        else:
            pytest.fail(f"Unexpected operation: {sql.split()[0:3]}")


def item(source: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    record = source or approved()
    values = {
        "source": record,
        "transport": record["transport"],
        "publisher_identity": "publisher-id-1",
        "url": "https://example.org/article/1",
        "title": "Publisher update",
        "excerpt": "Permitted summary.",
        "published_at": "2026-09-30T14:00:00Z",
        "updated_at": None,
        "fetched_at": "2026-10-01T00:00:00Z",
        "provenance": {
            "run_id": "fixture-run",
            "artifact_id": "fixture-artifact",
            "artifact_sha256": "a" * 64,
            "parser_version": "fixture-v1",
            "fetch_version": "fixture-v1",
        },
    }
    values.update(kwargs)
    return normalize_item(**values)


def store(database: Ledger) -> IntelligenceStore:
    return IntelligenceStore(
        connection_factory=database.connect,
        retention_allowed=lambda ref: ref == "synthetic-test-policy",
    )


def write(database: Ledger, items: list[dict[str, Any]], **kwargs: Any) -> WriteReceipt:
    values = {
        "source_id": "synthetic-publication",
        "registry_version": 1,
        "resource_key": "synthetic-publication",
        "run_id": "fixture-run",
        "items": items,
    }
    values.update(kwargs)
    return store(database).write(**values)


def test_atomic_first_write_replay_and_new_poll_capture() -> None:
    database = Ledger()
    document = item()
    assert write(database, [document]) == WriteReceipt(1, 1, 0)
    assert write(database, [document, copy.deepcopy(document)]) == WriteReceipt(0, 0, 2)
    assert len(database.revisions) == len(database.captures) == 1
    database.runs["next-run"] = "synthetic-publication"
    database.artifacts[("next-artifact", "next-run")] = "a" * 64
    database.endpoints[("next-artifact", "next-run")] = "https://example.org/feed.xml"
    database.pin("next-run", "next-artifact", database.sources[0], "2026-10-01T01:00:00Z")
    repoll = item(
        fetched_at="2026-10-01T01:00:00Z",
        provenance={**document["provenance"], "run_id": "next-run", "artifact_id": "next-artifact"},
    )
    assert write(database, [repoll], run_id="next-run") == WriteReceipt(0, 1, 0)
    assert len(database.revisions) == 1 and len(database.captures) == 2
    assert database.events[:3] == ["begin", "guard", "commit"]


def test_corrections_conflicting_dates_and_cross_transport_attribution() -> None:
    database = Ledger()
    first = item()
    revised = item(title="Publisher correction")
    conflicting = item(published_at="2026-09-29T14:00:00Z")
    write(database, [first, revised, conflicting])
    assert {x[0] for x in database.revisions} == {first["item_id"]}
    assert len(database.revisions) == 3
    other = approved()
    other.update(source_id="synthetic-atom", transport="atom", family="nih_niaid")
    database.sources.append(other)
    database.runs["atom-run"] = other["source_id"]
    database.artifacts[("atom-artifact", "atom-run")] = "a" * 64
    database.endpoints[("atom-artifact", "atom-run")] = other["fetch_location"]
    database.pin("atom-run", "atom-artifact", other, "2026-10-01T00:00:00Z")
    attributed = item(
        other,
        provenance={**first["provenance"], "run_id": "atom-run", "artifact_id": "atom-artifact"},
    )
    assert (
        attributed["item_id"] == first["item_id"]
        and attributed["revision_id"] == first["revision_id"]
    )
    assert write(
        database,
        [attributed],
        source_id="synthetic-atom",
        resource_key="synthetic-atom",
        run_id="atom-run",
    ) == WriteReceipt(0, 1, 0)
    captures = [json.loads(value[1]) for value in database.captures.values()]
    assert {x["source_id"] for x in captures} == {"synthetic-publication", "synthetic-atom"}
    assert {x["transport"] for x in captures} == {"rss", "atom"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("item_id", "b" * 64),
        ("content_sha256", "b" * 64),
        ("revision_id", "b" * 64),
        ("deduplication_key", "b" * 64),
    ],
)
def test_forged_hashes_rollback(field: str, value: str) -> None:
    database = Ledger()
    malformed = item()
    malformed[field] = value
    with pytest.raises(IntelligenceStorageError, match="HASH_MISMATCH"):
        write(database, [malformed])
    assert not database.revisions and not database.captures and database.events[-1] == "rollback"


@pytest.mark.parametrize("failure", ["capture", "commit"])
def test_partial_persistence_or_commit_failure_rolls_back_every_row_and_redacts(
    failure: str,
) -> None:
    database = Ledger()
    database.fail_on_capture = failure == "capture"
    database.fail_commit = failure == "commit"
    with pytest.raises(IntelligenceStorageError, match="TRANSACTION_FAILED") as caught:
        write(database, [item(), item(title="Second legitimate revision")])
    assert str(caught.value) == "INTELLIGENCE_TRANSACTION_FAILED"
    assert not database.revisions and not database.captures and database.events[-1] == "rollback"


def test_conflicting_replay_never_overwrites_provenance() -> None:
    database = Ledger()
    original = item()
    write(database, [original])
    changed = copy.deepcopy(original)
    changed["fetched_at"] = "2026-10-01T00:01:00Z"
    with pytest.raises(IntelligenceStorageError, match="ACQUISITION_REFERENCE_INVALID"):
        write(database, [changed])
    assert json.loads(database.captures[capture_id(original)][1]) == original


@pytest.mark.parametrize("which", ["run", "artifact", "artifact_hash", "source_hash", "guard"])
def test_missing_or_corrupt_ledger_references_fail_closed(which: str) -> None:
    database = Ledger()
    if which == "run":
        database.runs.clear()
    elif which == "artifact":
        database.artifacts.clear()
    elif which == "artifact_hash":
        database.artifacts[("fixture-artifact", "fixture-run")] = "c" * 64
    elif which == "source_hash":
        database.source_hash_valid = False
    else:
        database.guard_rows = 2
    with pytest.raises(IntelligenceStorageError):
        write(database, [item()])
    assert not database.revisions and not database.captures


@pytest.mark.parametrize(
    "role,database_name",
    [
        ("OH_LYME_DEV_READ", "ONE_HEALTH_LYME_GAP_ATLAS_DEV"),
        ("ACCOUNTADMIN", "ONE_HEALTH_LYME_GAP_ATLAS_DEV"),
        ("OH_LYME_DEV_RUNTIME", "ONE_HEALTH_LYME_GAP_ATLAS"),
        ("OH_LYME_PROD_RUNTIME", "ONE_HEALTH_LYME_GAP_ATLAS_PROD"),
    ],
)
def test_wrong_role_or_database_cannot_start_write(role: str, database_name: str) -> None:
    database = Ledger()
    database.role, database.database = role, database_name
    with pytest.raises(PermissionError, match="WRITER_CONTEXT_REQUIRED"):
        write(database, [item()])
    assert database.events == []


def test_paused_new_source_version_hides_old_approval_and_candidate_cannot_write() -> None:
    database = Ledger()
    newer = copy.deepcopy(database.sources[0])
    newer.update(registry_version=2, state="paused")
    database.sources.append(newer)
    with pytest.raises(PermissionError, match="CURRENT_SOURCE_REQUIRED"):
        write(database, [item()])
    database.sources = [json.loads((FIXTURES / "v1/candidate-source.json").read_text())]
    with pytest.raises(PermissionError, match="SOURCE_RIGHTS_REQUIRED"):
        write(database, [item()])
    assert not database.captures


def test_rights_revocation_and_unreviewed_inference_reject_items() -> None:
    database = Ledger()
    database.sources[0]["access_use"]["public_excerpt_permitted"] = False
    with pytest.raises(PermissionError, match="EXCERPT_NOT_PERMITTED"):
        write(database, [item()])
    database = Ledger()
    tagged = item()
    tagged["topics"] = [
        {
            "value": "tick-borne",
            "origin": "inferred",
            "method": "unapproved",
            "method_version": "1",
            "confidence": 0.8,
        }
    ]
    with pytest.raises(PermissionError, match="INFERENCE_REVIEW_REQUIRED"):
        write(database, [tagged])


def test_concurrent_replays_serialize_before_identity_checks_in_ledger_double() -> None:
    database = Ledger()
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: write(database, [item()]), range(2)))
    assert sorted((x.captures_inserted, x.captures_replayed) for x in receipts) == [(0, 1), (1, 0)]
    assert len(database.revisions) == len(database.captures) == 1


def test_bound_invalid_unknown_fields_and_duplicate_registry_rows() -> None:
    database = Ledger()
    with pytest.raises(IntelligenceStorageError, match="WRITE_LIMIT"):
        write(database, [item()] * 1001)
    unsafe = item()
    unsafe["recipient"] = "private@example.org"
    with pytest.raises(ValueError, match="INVALID_INTELLIGENCE_RECORD"):
        write(database, [unsafe])
    assert database.events == []
    database.sources.append(copy.deepcopy(database.sources[0]))
    with pytest.raises(IntelligenceStorageError, match="DUPLICATE_LEDGER_KEY"):
        write(database, [item()])


def test_offline_transport_to_storage_to_public_contract_fields() -> None:
    database = Ledger()

    class FixtureEffects(IntelligenceStageEffects):
        def _register_artifact(
            self,
            definition: Any,
            state: Any,
            acquired: Any,
            *,
            capture_identity: str | None = None,
        ) -> dict[str, Any]:
            database.runs[state.ingestion_run_id] = definition.resource_key
            artifact_id = "fixture-" + state.ingestion_run_id
            database.artifacts[(artifact_id, state.ingestion_run_id)] = acquired.artifact_sha256
            database.endpoints[(artifact_id, state.ingestion_run_id)] = acquired.payload[
                "source_context"
            ]["effective_url"]
            return {"artifact_id": artifact_id, "artifact_sha256": acquired.artifact_sha256}

    effects = FixtureEffects(
        connection_factory=database.connect,
        retention_allowed=lambda ref: True,
        artifact_policy_allowed=lambda ref, policy: True,
    )
    checkpoints = InMemoryCheckpointStore()
    # Test-only transport: identical local bytes through the injected HTTP seam.
    # No live provider or warehouse, and no fixture-mode bypass in the writer.
    adapter, _ = fetch_adapter(
        database.sources[0], [FeedResponse(200, {}, (FIXTURES / "rss/sample.xml").read_bytes())]
    )
    original_acquire = adapter.acquire
    adapter.acquire = lambda selected, **kwargs: original_acquire(selected)
    orchestrator = IngestionOrchestrator(
        store=checkpoints, fixture_dir=FIXTURES / "rss", effects=effects, adapter=adapter
    )
    state = orchestrator.run(definition(database.sources[0]), tier=Tier.A)
    assert state.status.value == "SUCCEEDED"
    normalized = checkpoints.load_normalized(state.ingestion_run_id)
    assert len(database.captures) == len(normalized) == 2
    documents = [json.loads(value[1]) for value in database.captures.values()]
    assert {x["revision_id"] for x in documents} == {x["revision_id"] for x in normalized}
    assert all(x["provenance"]["run_id"] == state.ingestion_run_id for x in documents)
    assert all("artifact_uri" not in x and "xml_base64" not in x for x in documents)


def test_migration_is_additive_narrow_and_public_view_is_current_reviewed_version() -> None:
    migration = (
        Path(__file__).parents[1] / "migrations/V135__intelligence_item_revisions_and_captures.sql"
    )
    sql = migration.read_text()
    assert "CREATE OR REPLACE" not in sql and "DROP " not in sql
    assert "GRANT SELECT ON VIEW PRESENTATION.INTELLIGENCE_FEED_V" in sql
    assert "GRANT SELECT, INSERT ON TABLE GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES" in sql
    assert "GRANT SELECT, UPDATE ON TABLE GOVERNANCE.INTELLIGENCE_WRITE_GUARD" in sql
    assert "GRANT INSERT ON TABLE GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS" not in sql
    view = sql.split("CREATE VIEW IF NOT EXISTS")[1].split("GRANT SELECT ON VIEW")[0]
    assert "newer.registry_version > s.registry_version" in view
    assert "state::VARCHAR IN ('active', 'manual')" in view
    assert "artifact_uri" not in view and "SELECT *" not in view
    assert "AS excerpt" in view and "AS content_is_untrusted" in view
    assert "AS deduplication_key" in view and "AS transport_identity_sha256" in view


@pytest.mark.parametrize(
    "stage",
    [
        "factory",
        "connection_enter",
        "cursor",
        "cursor_enter",
        "context",
        "lookup",
        "cursor_exit",
        "connection_exit",
    ],
)
def test_lookup_redacts_entire_provider_lifecycle(stage: str) -> None:
    database = Ledger()
    database.fail_at = stage
    with pytest.raises(IntelligenceStorageError) as caught:
        store(database).lookup_source("synthetic-publication", 1)
    assert str(caught.value) == "INTELLIGENCE_SOURCE_LOOKUP_FAILED"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert not database.captures and not database.revisions


@pytest.mark.parametrize(
    "stage",
    [
        "factory",
        "connection_enter",
        "cursor",
        "cursor_enter",
        "context",
        "setup",
        "begin",
        "lookup",
        "cursor_exit",
        "connection_exit",
    ],
)
def test_write_redacts_entire_provider_lifecycle(stage: str) -> None:
    database = Ledger()
    database.fail_at = stage
    with pytest.raises(IntelligenceStorageError) as caught:
        write(database, [item()])
    assert str(caught.value) == "INTELLIGENCE_TRANSACTION_FAILED"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    if stage not in {"cursor_exit", "connection_exit"}:
        assert not database.captures and not database.revisions
    else:
        # Commit succeeded before cleanup failed: exact replay remains safe.
        database.fail_at = None
        assert write(database, [item()]) == WriteReceipt(0, 0, 1)


def test_rollback_failure_cannot_replace_original_safe_error() -> None:
    database = Ledger()
    database.fail_at = "rollback"
    forged = item()
    forged["revision_id"] = "b" * 64
    with pytest.raises(IntelligenceStorageError) as caught:
        write(database, [forged])
    assert str(caught.value) == "INTELLIGENCE_ITEM_HASH_MISMATCH"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert not database.captures and not database.revisions


@pytest.mark.parametrize(
    "stage",
    [
        "factory",
        "connection_enter",
        "cursor",
        "cursor_enter",
        "context",
        "setup",
        "begin",
        "lookup",
        "cursor_exit",
        "connection_exit",
    ],
)
def test_registration_redacts_entire_provider_lifecycle(stage: str) -> None:
    database = Ledger()
    context = json.loads(database.contexts[("fixture-run", "fixture-artifact")][1])
    database.contexts.clear()
    database.fail_at = stage
    with pytest.raises(IntelligenceStorageError) as caught:
        record_context(database, context)
    assert str(caught.value) == "INTELLIGENCE_ACQUISITION_REGISTRATION_FAILED"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert not database.captures and not database.revisions
    if stage not in {"cursor_exit", "connection_exit"}:
        assert not database.contexts


def test_private_permission_callback_error_is_not_preserved() -> None:
    database = Ledger()

    def policy(ref: str) -> bool:
        raise PermissionError("private warehouse credential")

    writer = IntelligenceStore(connection_factory=database.connect, retention_allowed=policy)
    with pytest.raises(IntelligenceStorageError) as caught:
        writer.lookup_source("synthetic-publication", 1)
    assert str(caught.value) == "INTELLIGENCE_SOURCE_LOOKUP_FAILED"
    assert caught.value.__cause__ is None and caught.value.__context__ is None


@pytest.mark.parametrize(
    "drift", ["source", "version", "rights", "resource", "receipt", "missing", "endpoint"]
)
def test_unchanged_artifact_cannot_be_relabelled(drift: str) -> None:
    database = Ledger()
    source = copy.deepcopy(database.sources[0])
    kwargs: dict[str, Any] = {}
    if drift == "source":
        source["source_id"] = "other-source"
        database.sources.append(source)
        # Even changing the caller's run/resource labels cannot change the receipt.
        database.runs["fixture-run"] = "other-source"
        kwargs.update(source_id="other-source", resource_key="other-source")
    elif drift == "version":
        source["registry_version"] = 2
        database.sources.append(source)
        kwargs["registry_version"] = 2
    elif drift == "rights":
        source["access_use"]["excerpt_max_chars"] = 500
        database.sources = [source]
    elif drift == "resource":
        database.runs["fixture-run"] = "other-resource"
        kwargs["resource_key"] = "other-resource"
    elif drift == "receipt":
        key = ("fixture-run", "fixture-artifact")
        context = json.loads(database.contexts[key][1])
        context["effective_url"] = "https://example.org/changed.xml"
        database.contexts[key] = (database.contexts[key][0], json.dumps(context))
    elif drift == "missing":
        database.contexts.clear()
    else:
        database.endpoints[("fixture-artifact", "fixture-run")] = "https://example.org/changed.xml"
    with pytest.raises(IntelligenceStorageError):
        write(database, [item(source)], **kwargs)
    assert not database.captures and not database.revisions


def record_context(database: Ledger, context: dict[str, Any]) -> None:
    store(database).record_acquisition(
        source_id="synthetic-publication",
        registry_version=1,
        resource_key="synthetic-publication",
        run_id="fixture-run",
        artifact_id="fixture-artifact",
        context=context,
    )


def test_acquisition_receipt_is_immutable_and_required_before_capture() -> None:
    database = Ledger()
    context = json.loads(database.contexts[("fixture-run", "fixture-artifact")][1])
    database.contexts.clear()
    record_context(database, context)
    assert write(database, [item()]) == WriteReceipt(1, 1, 0)
    original = copy.deepcopy(database.contexts)
    record_context(database, context)
    context["fetched_at"] = "2026-10-01T00:01:00Z"
    with pytest.raises(IntelligenceStorageError, match="ACQUISITION_REPLAY_CONFLICT") as caught:
        record_context(database, context)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert database.contexts == original


@pytest.mark.parametrize("change", ["endpoint", "fixture", "sha", "rights"])
def test_acquisition_registration_checks_raw_and_review_before_inserting(change: str) -> None:
    database = Ledger()
    context = json.loads(database.contexts[("fixture-run", "fixture-artifact")][1])
    database.contexts.clear()
    if change == "endpoint":
        database.endpoints[("fixture-artifact", "fixture-run")] = "https://example.org/other.xml"
    elif change == "fixture":
        context["capture_mode"] = "fixture"
    elif change == "sha":
        context["artifact_sha256"] = "b" * 64
    else:
        database.sources[0]["access_use"]["excerpt_max_chars"] = 500
    with pytest.raises(IntelligenceStorageError):
        record_context(database, context)
    assert not database.contexts and not database.captures
