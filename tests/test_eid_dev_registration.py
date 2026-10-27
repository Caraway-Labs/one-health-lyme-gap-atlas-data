"""Credential-free checks for the one-source governed DEV registration path."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from semantic_contracts import load_workflow, trigger_map

from lyme_gap_atlas_data.ingestion.intelligence_runtime import (
    PROD_DAILY_SOURCE_SHA256,
    PROD_SOURCE_DEFINITIONS,
    PROD_SOURCE_SHA256,
)
from lyme_gap_atlas_data.intelligence_items import identity_hash

spec = importlib.util.spec_from_file_location(
    "eid_registration", Path(__file__).parents[1] / "scripts/register_eid_expedited_dev.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Cursor:
    def __init__(
        self, *, identity: tuple[str, ...] = module.IDENTITY, existing: list[Any] | None = None
    ):
        self.identity = identity
        self.existing = existing or []
        self.statements: list[str] = []
        self.rowcount = 0
        self.rows: list[Any] = []

    def __enter__(self):
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.statements.append(sql)
        if sql.startswith("SELECT CURRENT_USER()"):
            self.rows = [self.identity]
        elif sql.startswith("SELECT registry_version"):
            assert params == (module.SOURCE_ID,)
            self.rows = self.existing
        elif sql.startswith("UPDATE GOVERNANCE.INTELLIGENCE_WRITE_GUARD"):
            self.rowcount = 1
        elif sql.startswith("INSERT INTO GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS"):
            assert params[:2] == (module.SOURCE_ID, 1)
            assert json.loads(params[3])["source_id"] == module.SOURCE_ID
            self.rowcount = 1

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, cursor: Cursor):
        self.selected = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.selected

    def autocommit(self, enabled: bool) -> None:
        assert enabled is False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_exact_checked_in_document_and_receipt_are_bound() -> None:
    source, checksum = module.reviewed_package()
    assert source["registry_version"] == 1
    assert source["approval"]["decision_ref"] == module.DECISION_REF
    assert checksum == "51705ebb4c82d7fc8e992f2e5793c45f79f202578ba487747aa2109e695f33a4"


def test_wrong_identity_stops_before_any_mutation() -> None:
    source, checksum = module.reviewed_package()
    cursor = Cursor(identity=("OTHER", *module.IDENTITY[1:]))
    connection = Connection(cursor)
    with pytest.raises(PermissionError, match="IDENTITY_REQUIRED"):
        module.register(connection, source, checksum)
    assert cursor.statements == [
        "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()"
    ]
    assert connection.commits == 0


def test_exact_single_insert_and_idempotent_retry() -> None:
    source, checksum = module.reviewed_package()
    first = Connection(Cursor())
    assert module.register(first, source, checksum) == "RECORDED"
    assert first.commits == 1
    assert (
        sum(
            "INSERT INTO GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS" in sql
            for sql in first.selected.statements
        )
        == 1
    )
    merges = [sql for sql in first.selected.statements if sql.startswith("MERGE INTO")]
    assert len(merges) == 1
    assert merges[0].count("MERGE INTO") == 1
    assert "'BLOCKED'" not in merges[0]
    retry = Connection(Cursor(existing=[(1, checksum, json.dumps(source))]))
    assert module.register(retry, source, checksum) == "ALREADY_RECORDED"
    assert retry.commits == 0 and retry.rollbacks == 1
    assert all("INSERT INTO" not in sql for sql in retry.selected.statements)
    assert all(not sql.startswith("MERGE INTO") for sql in retry.selected.statements)


def test_different_existing_registry_row_fails_closed() -> None:
    source, checksum = module.reviewed_package()
    connection = Connection(Cursor(existing=[(2, "0" * 64, json.dumps(source))]))
    with pytest.raises(PermissionError, match="REGISTRY_STATE_CHANGED"):
        module.register(connection, source, checksum)
    assert connection.rollbacks == 1 and connection.commits == 0
    assert all("INSERT INTO" not in sql for sql in connection.selected.statements)


def test_mutated_receipt_rejected_before_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = json.loads(module.RECEIPTS.read_text())
    receipt["receipts"][0]["source_sha256"] = "0" * 64
    changed = tmp_path / "receipt.json"
    changed.write_text(json.dumps(receipt))
    monkeypatch.setattr(module, "RECEIPTS", changed)
    with pytest.raises(PermissionError, match="PACKAGE_MISMATCH"):
        module.reviewed_package()


def test_workflow_fixed_registration_exits_before_migration_path() -> None:
    workflow = (Path(__file__).parents[1] / ".github/workflows/deploy-dev.yml").read_text()
    start = workflow.index('if [ "$REGISTER_EID_EXPEDITED_DEV" = "true" ]')
    end = workflow.index("exit 0", start)
    branch = workflow[start:end]
    assert "test \"$EXPECTED_PENDING_JSON\" = '[]'" in branch
    assert 'test "$GITHUB_SHA" = "$REVIEWED_COMMIT"' in branch
    assert 'test "$FEED_PREFLIGHT_ACCOUNTING_CONFIRMED" = "true"' in branch
    assert "scripts/register_eid_expedited_dev.py" in branch
    assert workflow.index("apply-reviewed-dev-migrations") > end
    assert "-q " not in branch and "--query" not in branch


_FIVE_V1_PINS = {
    "cdc-eid-expedited": "51705ebb4c82d7fc8e992f2e5793c45f79f202578ba487747aa2109e695f33a4",
    "cdc-eid-ahead-of-print": "b92e97c9e958c270645c9710118b3a3076228c6bcb2390b5c58cff9bacb2a7be",
    "cdc-outbreaks": "54793f2c4856602bf8901d09972a44d2a7479056e71eac75ddc88db060646172",
    "nih-news-releases": "38d7364d5ce7b730d16e07197d0bb1cf88403eae59defc66de05e3a3df825bea",
    "cdc-mmwr": "875b0bc1b33f2c89ff4596532ccd8504dc6ce60086f8bba9146183da2b2d59a6",
}
_FIVE_V2_PINS = {
    "cdc-eid-expedited": "570a796df7086b520136e5deab5917957561314e2f5fe96659bb3c9534124423",
    "cdc-eid-ahead-of-print": "12e3003da3e8782b379e321eb61fccecb36a9269c3017c10132bb96c848c39c3",
    "cdc-outbreaks": "d8bdcc90b16c98fe2b3661a9316ac78071bd355cbb46ee5d0299c15ca4f53b8f",
    "nih-news-releases": "1542aa4d8f85a650ac216e574907ec19f65e1d17a26dd8c8b607bfdcd17faaa1",
    "cdc-mmwr": "9ee7ceca898a4419241d9706c7cbf0a795287c794cdeb74b0892a4f90ccda0e9",
}
_PUBMED_IDS = ("pubmed-tick-borne", "pubmed-lyme-borrelia")


class RecordingCursor(Cursor):
    def __init__(self) -> None:
        super().__init__()
        self.params: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.params.append(params)
        self.statements.append(sql)
        if sql.startswith("SELECT CURRENT_USER()"):
            self.rows = [self.identity]
        elif sql.startswith("SELECT registry_version"):
            self.rows = list(self.existing)
        elif sql.startswith(
            ("UPDATE GOVERNANCE.INTELLIGENCE_WRITE_GUARD", "INSERT INTO", "MERGE INTO")
        ):
            self.rowcount = 1


def test_five_source_pins_are_unchanged() -> None:
    for source_id, digest in _FIVE_V1_PINS.items():
        assert PROD_SOURCE_SHA256[source_id] == digest
    for source_id, digest in _FIVE_V2_PINS.items():
        assert PROD_DAILY_SOURCE_SHA256[source_id] == digest
    assert set(PROD_SOURCE_DEFINITIONS) == set(_FIVE_V1_PINS)


def test_pubmed_ids_match_pins_and_unknown_ids_are_refused() -> None:
    for source_id in _PUBMED_IDS:
        source, checksum = module.reviewed_package(source_id, 1)
        assert checksum == identity_hash(source)
        assert checksum == PROD_SOURCE_SHA256[source_id] == PROD_DAILY_SOURCE_SHA256[source_id]
        assert source["state"] == "active"
        assert source["registry_version"] == 1
        assert source_id not in PROD_SOURCE_DEFINITIONS
        with pytest.raises(PermissionError, match="EID_REVIEWED_PACKAGE_MISMATCH"):
            module.reviewed_package(source_id, 2)
        with pytest.raises(PermissionError, match="EID_REVIEWED_PACKAGE_MISMATCH"):
            module.reviewed_package(source_id, 3)
    with pytest.raises(PermissionError, match="EID_REVIEWED_PACKAGE_MISMATCH"):
        module.reviewed_package("pubmed-unknown")
    with pytest.raises(PermissionError, match="EID_REVIEWED_PACKAGE_MISMATCH"):
        module.reviewed_package("cdc-eid-expedited", 4)


def test_pubmed_registration_writes_one_active_activation_row() -> None:
    source, checksum = module.reviewed_package("pubmed-tick-borne", 1)
    cursor = RecordingCursor()
    connection = Connection(cursor)
    assert module.register(connection, source, checksum) == "RECORDED"
    merges = [
        (sql, params)
        for sql, params in zip(cursor.statements, cursor.params, strict=True)
        if sql.startswith("MERGE INTO")
    ]
    assert len(merges) == 1
    merge_sql, merge_params = merges[0]
    assert merge_sql.count("MERGE INTO") == 1
    assert merge_params == (
        "pubmed-tick-borne",
        1,
        checksum,
        "ACTIVE",
        "matthew-feed-selection-2026-10-03",
    )
    for other in _FIVE_V1_PINS:
        assert other not in merge_params
    retry_cursor = RecordingCursor()
    retry_cursor.existing = [(1, checksum, json.dumps(source))]
    retry = Connection(retry_cursor)
    assert module.register(retry, source, checksum) == "ALREADY_RECORDED"
    assert all(not sql.startswith("MERGE INTO") for sql in retry.selected.statements)


def test_registration_workflows_list_pubmed_ids_and_still_require_an_empty_pending_set() -> None:
    root = Path(__file__).parents[1]
    prod = load_workflow(root / ".github/workflows/register-prod-eid.yml")
    dev = load_workflow(root / ".github/workflows/deploy-dev.yml")
    prod_inputs = trigger_map(prod)["workflow_dispatch"]["inputs"]
    dev_inputs = trigger_map(dev)["workflow_dispatch"]["inputs"]
    assert prod_inputs["source_id"]["default"] == "cdc-eid-expedited"
    assert prod_inputs["registry_version"]["options"] == ["1", "2"]
    assert dev_inputs["intelligence_register_registry_version"]["options"] == ["1", "2"]
    for source_id in _PUBMED_IDS:
        assert source_id in prod_inputs["source_id"]["options"]
        assert source_id in dev_inputs["intelligence_register_source_id"]["options"]
    dev_text = (root / ".github/workflows/deploy-dev.yml").read_text(encoding="utf-8")
    assert "pubmed-tick-borne|pubmed-lyme-borrelia) ;;" in dev_text
    assert "Unsupported intelligence registration source" in dev_text
    assert "1|2) ;;" in dev_text
    assert "test \"$EXPECTED_PENDING_JSON\" = '[]'" in dev_text
    prod_text = (root / ".github/workflows/register-prod-eid.yml").read_text(encoding="utf-8")
    assert "guard_eq expected_pending_json '[]'" in prod_text
