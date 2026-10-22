"""Independent transaction ledger for complete-feed bounded SQL writes."""

import json

import pytest
import sqlglot
from test_intelligence_storage import Connection, Cursor, Ledger, item

from lyme_gap_atlas_data.intelligence_batch_storage import document_batches
from lyme_gap_atlas_data.intelligence_items import canonical_json
from lyme_gap_atlas_data.intelligence_storage import (
    IntelligenceStorageError,
    IntelligenceStore,
    WriteReceipt,
)
from lyme_gap_atlas_data.settings import PipelineSettings


class BatchCursor(Cursor):
    def execute(self, statement, params=()):
        sql = " ".join(statement.split()).upper()
        database = self.connection.ledger
        database.statements.append((statement, params))
        if sql.startswith("SELECT ITEM_ID,REVISION_ID,CONTENT_SHA256"):
            assert self.connection.locked
            keys = list(zip(params[::2], params[1::2], strict=True))
            self.rows = [
                (*key, *self.connection.pending[0][key])
                for key in keys
                if key in self.connection.pending[0]
            ]
        elif sql.startswith("SELECT CAPTURE_ID,ITEM_SHA256"):
            assert self.connection.locked
            self.rows = [
                (key, *self.connection.pending[1][key])
                for key in params
                if key in self.connection.pending[1]
            ]
        elif "FLATTEN(INPUT=>PARSE_JSON(%S))" in sql:
            assert self.connection.locked and self.connection.active
            assert len(params) == 1 and len(params[0].encode()) <= 900_000
            rows = json.loads(params[0])
            self.rowcount = len(rows) - 1 if database.bad_rowcount else len(rows)
            assert len(rows) <= 250
            if sql.startswith("INSERT INTO CONFORMED.INTELLIGENCE_ITEM_REVISIONS"):
                for row in rows:
                    key = (row["item_id"], row["revision_id"])
                    assert key not in self.connection.pending[0]
                    self.connection.pending[0][key] = (
                        row["content_sha256"],
                        canonical_json(row["content_document"]),
                    )
            else:
                database.capture_batches += 1
                if database.capture_batches == database.fail_capture_batch:
                    raise RuntimeError("private driver diagnostic")
                assert sql.startswith("INSERT INTO GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES")
                for row in rows:
                    assert row["ingestion_run_id"] in database.runs
                    assert row["capture_id"] not in self.connection.pending[1]
                    self.connection.pending[1][row["capture_id"]] = (
                        row["item_sha256"],
                        canonical_json(row["item_document"]),
                    )
        else:
            super().execute(statement, params)


class BatchConnection(Connection):
    def cursor(self):
        return BatchCursor(self)


def setup():
    database = Ledger()
    database.statements = []
    database.capture_batches = 0
    database.fail_capture_batch = -1
    database.bad_rowcount = False
    database.sources[0]["limits"]["maximum_items"] = 3000
    database.pin("fixture-run", "fixture-artifact", database.sources[0], "2026-10-01T00:00:00Z")
    records = [
        item(
            database.sources[0],
            publisher_identity=f"id-{n}",
            url=f"https://example.org/article/{n}",
        )
        for n in range(300)
    ]
    store = IntelligenceStore(
        connection_factory=lambda: BatchConnection(database),
        retention_allowed=lambda _: True,
        maximum_write_bytes=32_000_000,
    )
    return database, records, store


def write(store, records):
    return store.write(
        source_id="synthetic-publication",
        registry_version=1,
        resource_key="synthetic-publication",
        run_id="fixture-run",
        items=records,
    )


def test_complete_capture_batches_are_atomic_replayable_and_bounded():
    database, records, store = setup()
    assert write(store, records) == WriteReceipt(300, 300, 0)
    assert len(database.captures) == len(database.revisions) == 300
    assert database.events == ["begin", "guard", "commit"]
    assert len(database.statements) < 30
    for statement, _ in database.statements:
        # The driver binds pyformat tokens before Snowflake parses SQL.
        sqlglot.parse_one(statement.replace("%s", "?"), read="snowflake")
    database.statements.clear()
    assert write(store, records) == WriteReceipt(0, 0, 300)
    assert len(database.captures) == 300
    corrected = item(
        database.sources[0],
        publisher_identity="id-299",
        url="https://example.org/article/299",
        title="Corrected publisher title",
    )
    assert corrected["item_id"] == records[-1]["item_id"]
    assert write(store, [corrected]) == WriteReceipt(1, 1, 0)
    assert len(database.revisions) == len(database.captures) == 301


@pytest.mark.parametrize("failure", ["later_batch", "commit"])
def test_failure_rolls_back_earlier_batches_without_partial_publication(failure):
    database, records, store = setup()
    database.fail_capture_batch = 2 if failure == "later_batch" else -1
    database.fail_commit = failure == "commit"
    with pytest.raises(IntelligenceStorageError, match="TRANSACTION_FAILED") as caught:
        write(store, records)
    assert "private" not in str(caught.value)
    assert not database.revisions and not database.captures
    assert database.events[-1] == "rollback"


@pytest.mark.parametrize("which", ["artifact", "context", "capture_conflict", "revision_conflict"])
def test_reference_and_replay_conflicts_fail_closed(which):
    database, records, store = setup()
    if which in {"capture_conflict", "revision_conflict"}:
        write(store, records)
        if which == "capture_conflict":
            key = next(iter(database.captures))
            database.captures[key] = ("b" * 64, database.captures[key][1])
        else:
            key = next(iter(database.revisions))
            database.revisions[key] = ("b" * 64, database.revisions[key][1])
    elif which == "artifact":
        database.artifacts.clear()
    else:
        database.contexts.clear()
    before = (dict(database.revisions), dict(database.captures))
    with pytest.raises(IntelligenceStorageError):
        write(store, records)
    assert (database.revisions, database.captures) == before


def test_batch_split_preserves_every_row_and_both_resource_bounds():
    documents = [{"ordinal": n, "metadata": "x" * 40_000} for n in range(400)]
    batches = list(document_batches(documents))
    assert [row for batch in batches for row in batch] == documents
    assert all(
        len(batch) <= 250 and len(canonical_json(batch).encode()) <= 900_000 for batch in batches
    )
    with pytest.raises(IntelligenceStorageError, match="WRITE_LIMIT"):
        list(document_batches([{"metadata": "x" * 900_000}]))


def test_total_byte_bound_stops_before_opening_any_transaction():
    database, records, _ = setup()
    store = IntelligenceStore(
        connection_factory=lambda: pytest.fail("no I/O"),
        retention_allowed=lambda _: True,
        maximum_write_bytes=1,
    )
    with pytest.raises(IntelligenceStorageError, match="WRITE_LIMIT"):
        write(store, records)
    assert database.events == []


def test_direct_production_store_cannot_enable_the_extended_dev_path():
    with pytest.raises(PermissionError, match="PROD_EXPANDED_BOUNDS_NOT_ADMITTED"):
        IntelligenceStore(
            connection_factory=lambda: pytest.fail("no I/O"),
            retention_allowed=lambda _: True,
            maximum_write_bytes=32_000_000,
            settings=PipelineSettings(
                topx_env="prod",
                enable_production_execution=True,
                snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
            ),
        )


def test_incomplete_batch_insert_receipt_rolls_back_the_whole_capture():
    database, records, store = setup()
    database.bad_rowcount = True
    with pytest.raises(IntelligenceStorageError, match="WRITE_COUNT_MISMATCH"):
        write(store, records)
    assert not database.revisions and not database.captures
    assert database.events[-1] == "rollback"
