"""Credential-free checks for the one-source governed DEV registration path."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

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
    retry = Connection(Cursor(existing=[(1, checksum, json.dumps(source))]))
    assert module.register(retry, source, checksum) == "ALREADY_RECORDED"
    assert retry.commits == 0 and retry.rollbacks == 1
    assert all("INSERT INTO" not in sql for sql in retry.selected.statements)


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
