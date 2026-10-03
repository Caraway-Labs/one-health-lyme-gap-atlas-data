"""Real ledger transaction/audit ordering over a transactional warehouse double."""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict

import pytest
from test_intelligence_feed import definition
from test_intelligence_raw_runtime import END, adapter, setup

from lyme_gap_atlas_data.intelligence_items import identity_hash
from lyme_gap_atlas_data.intelligence_raw_cleanup import WarehouseRawDelete, cleanup
from lyme_gap_atlas_data.intelligence_raw_runtime import SnowflakeRawLedger
from lyme_gap_atlas_data.intelligence_retention import RawCopy, plan_cleanup


class Warehouse:
    def __init__(self, metadata):
        self.metadata = metadata
        self.payload_exists = True
        self.fail_commit = False
        self.audit = []
        self.calls = []

    def connect(self):
        return Connection(self)


class Connection:
    def __init__(self, warehouse):
        self.warehouse = warehouse
        self.active = False
        self.pending_delete = False
        self.pending_audit = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self.active:
            self.rollback()

    def cursor(self):
        return Cursor(self)

    def autocommit(self, value):
        assert value is False

    def commit(self):
        if self.active and self.warehouse.fail_commit:
            raise RuntimeError("simulated warehouse commit failure")
        if self.pending_delete:
            self.warehouse.payload_exists = False
        self.warehouse.audit.extend(self.pending_audit)
        self.pending_audit.clear()
        self.active = False
        self.warehouse.calls.append("COMMIT")

    def rollback(self):
        self.pending_delete = False
        self.pending_audit.clear()
        self.active = False
        self.warehouse.calls.append("ROLLBACK")


class Cursor:
    rowcount = 1

    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, params=()):
        warehouse = self.connection.warehouse
        warehouse.calls.append(sql)
        if "CURRENT_ROLE" in sql:
            self.rows = [("OH_LYME_DEV_RUNTIME", "ONE_HEALTH_LYME_GAP_ATLAS_DEV", None)]
        elif sql == "BEGIN TRANSACTION":
            self.connection.active = True
        elif "FROM GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS" in sql:
            selected = [
                document
                for (kind, key), document in warehouse.metadata.items()
                if kind == params[0] and (len(params) == 1 or key == params[1])
            ]
            self.rows = [(identity_hash(document), json.dumps(document)) for document in selected]
        elif sql.startswith("CALL GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT"):
            self.connection.pending_delete = warehouse.payload_exists
            self.rows = [("deleted" if warehouse.payload_exists else "already_absent",)]
        elif sql.startswith("INSERT INTO GOVERNANCE.INTELLIGENCE_RAW_RETENTION_AUDIT"):
            document = json.loads(params[1])
            if document["outcome"] == "deleted":
                assert not warehouse.payload_exists, "false durable deleted receipt"
            self.connection.pending_audit.append(document)
        elif not sql.startswith(("ALTER SESSION", "UPDATE GOVERNANCE.INTELLIGENCE_WRITE_GUARD")):
            pytest.fail(f"unexpected warehouse fixture statement: {sql}")

    def fetchall(self):
        return self.rows


def prepared(tmp_path):
    source, gate, clock = setup(tmp_path)
    feed, _ = adapter(source, gate)
    acquired = feed.acquire(definition(source))
    gate.bind("fixture-run", acquired.payload)
    lease_sha = acquired.payload["raw_lease_sha256"]
    copy = RawCopy(
        "DEV",
        source["source_id"],
        "checkpoint_payload",
        "snowflake://ONE_HEALTH_LYME_GAP_ATLAS_DEV/GOVERNANCE/INGESTION_RUN_PAYLOADS/fixture-run",
        lease_sha,
    )
    gate.ledger.put("copy", copy.sha256, asdict(copy))
    with closing(sqlite3.connect(gate.ledger.path)) as connection:
        metadata = {
            (kind, key): json.loads(document)
            for kind, key, document in connection.execute("SELECT kind,key,document FROM documents")
        }
    warehouse = Warehouse(metadata)
    gate.ledger = SnowflakeRawLedger(warehouse.connect, "DEV")
    clock.value = END
    plan = plan_cleanup(
        gate,
        environment="DEV",
        source_ids=(source["source_id"],),
        now=END,
        scope=lambda selected: selected == copy,
    )
    driver = WarehouseRawDelete(gate, warehouse.connect, plan)
    return gate, warehouse, plan, driver


def test_failed_outer_commit_never_appends_false_deleted_receipt(tmp_path):
    gate, warehouse, plan, driver = prepared(tmp_path)
    warehouse.fail_commit = True
    with pytest.raises(RuntimeError, match="commit failure"):
        cleanup(
            gate,
            plan,
            approved=lambda digest: digest == plan.sha256,
            scope=lambda copy: True,
            delete={"checkpoint_payload": driver},
        )
    assert warehouse.payload_exists
    assert [receipt["outcome"] for receipt in warehouse.audit] == ["pending"]
    assert warehouse.calls[-1] == "ROLLBACK"
    warehouse.fail_commit = False
    result = cleanup(
        gate,
        plan,
        approved=lambda digest: digest == plan.sha256,
        scope=lambda copy: True,
        delete={"checkpoint_payload": driver},
    )
    assert result[0].outcome == "deleted" and not warehouse.payload_exists
    assert warehouse.audit[-1]["outcome"] == "deleted"


def test_warehouse_deleted_audit_follows_actual_commit_and_retry_is_absent(tmp_path):
    gate, warehouse, plan, driver = prepared(tmp_path)
    result = cleanup(
        gate,
        plan,
        approved=lambda digest: digest == plan.sha256,
        scope=lambda copy: True,
        delete={"checkpoint_payload": driver},
    )
    assert result[0].outcome == "deleted" and not warehouse.payload_exists
    assert [receipt["outcome"] for receipt in warehouse.audit] == ["pending", "deleted"]
    retry = cleanup(
        gate,
        plan,
        approved=lambda digest: digest == plan.sha256,
        scope=lambda copy: True,
        delete={"checkpoint_payload": driver},
    )
    assert retry[0].outcome == "already_absent"
