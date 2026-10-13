"""Credential-free checks for the exact EID PROD route and registration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import typer

from lyme_gap_atlas_data import cli
from lyme_gap_atlas_data.ingestion.source_definition import load_source_definition
from lyme_gap_atlas_data.migrations import load_migrations

ROOT = Path(__file__).parents[1]
EID_PATH = "config/sources/intelligence_cdc_eid_expedited.yml"
spec = importlib.util.spec_from_file_location(
    "eid_prod_registration", ROOT / "scripts/register_eid_expedited_prod.py"
)
assert spec and spec.loader
registration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registration)


class Cursor:
    def __init__(self, identity: tuple[str, ...], v146: list[tuple[str, str]]):
        self.identity, self.v146 = identity, v146
        self.statements: list[str] = []
        self.rows: list[Any] = []

    def __enter__(self) -> Cursor:
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def execute(self, statement: str) -> None:
        self.statements.append(statement)
        if statement.startswith("SELECT CURRENT_USER()"):
            self.rows = [self.identity]
        elif "SCHEMA_MIGRATIONS" in statement:
            self.rows = self.v146
        else:
            pytest.fail("Unexpected SQL in read-only preflight")

    def fetchall(self) -> list[Any]:
        return self.rows


class Connection:
    def __init__(self, cursor: Cursor):
        self.selected = cursor

    def cursor(self) -> Cursor:
        return self.selected


def test_registration_identity_and_exact_v146_fail_closed() -> None:
    migration = next(item for item in load_migrations() if item.version == "V146")
    assert (migration.filename, migration.sha256) == registration.V146
    for identity, v146 in (
        (("OTHER", *registration.IDENTITY[1:]), [registration.V146]),
        (registration.IDENTITY, []),
        (registration.IDENTITY, [(registration.V146[0], "0" * 64)]),
        (registration.IDENTITY, [registration.V146, registration.V146]),
    ):
        cursor = Cursor(identity, v146)
        with pytest.raises(PermissionError):
            registration.verify_schema(Connection(cursor))
        if identity != registration.IDENTITY:
            assert len(cursor.statements) == 1
        assert all(statement.startswith("SELECT ") for statement in cursor.statements)
    registration.verify_schema(Connection(Cursor(registration.IDENTITY, [registration.V146])))


def test_cli_rejects_generic_tier_c_rss_and_alternate_eid_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    eid = load_source_definition(ROOT / EID_PATH)
    monkeypatch.setattr(cli, "load_source_definition", lambda _: eid)
    monkeypatch.setattr(cli, "_orchestrator", lambda *args, **kwargs: pytest.fail("Generic route"))
    with pytest.raises(typer.BadParameter, match="exact EID protected route"):
        cli.source_run(
            definition="other-eid.yml",
            tier="C",
            dry_run=False,
            fixture_dir=None,
            fail_after_stage=None,
        )
    with pytest.raises(typer.BadParameter, match="exact EID protected route"):
        cli.source_run(
            definition=EID_PATH,
            tier="C",
            dry_run=True,
            fixture_dir=None,
            fail_after_stage=None,
        )


def test_prod_workflows_pin_eid_and_keep_registry_write_separate() -> None:
    ingestion = (ROOT / ".github/workflows/run-prod-ingestion.yml").read_text()
    registration_workflow = (ROOT / ".github/workflows/register-prod-eid.yml").read_text()
    assert (
        "environment: production" in ingestion
        and "environment: production" in registration_workflow
    )
    assert 'test "$GITHUB_SHA" = "$REVIEWED_COMMIT"' in registration_workflow
    assert "test \"$EXPECTED_PENDING_JSON\" = '[]'" in registration_workflow
    assert "scripts/register_eid_expedited_prod.py" in registration_workflow
    assert "apply-migrations" not in registration_workflow
    assert "--query" not in registration_workflow
    assert (
        "inputs.source_definition != 'config/sources/intelligence_cdc_eid_expedited.yml'"
        in ingestion
    )
    assert 'test "$REQUEST_OPERATION" = run' in ingestion
    assert 'test -z "$REQUEST_SOURCE_VERSION_ID"' in ingestion
    assert "GOVERNANCE.DATA_SOURCE_VERSIONS" in ingestion  # unchanged generic route
    assert "--tier C" in ingestion
