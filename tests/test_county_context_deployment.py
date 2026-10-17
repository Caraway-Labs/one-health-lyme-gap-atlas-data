"""Scope and resource gates for the protected forward migration."""

import runpy
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest

from lyme_gap_atlas_data import migrations

ROOT = Path(__file__).parents[1]


def entry(version):
    migration = next(m for m in migrations.load_migrations() if m.version == version)
    return {"version": version, "filename": migration.filename, "sha256": migration.sha256}


@pytest.mark.parametrize(
    "database,versions",
    [
        (migrations.DEV_DATABASE, ["V150", "V155"]),
        (migrations.PROD_DATABASE, ["V155"]),
        (migrations.PROD_DATABASE, ["V150", "V154", "V155"]),
    ],
)
def test_wrong_execution_scope_cannot_connect(monkeypatch, database, versions):
    connection = Mock()
    monkeypatch.setattr(migrations, "connect", connection)
    with pytest.raises(PermissionError, match="County context"):
        migrations.apply_migrations(
            Mock(),
            database,
            county_context_only=True,
            expected_pending=[entry(v) for v in versions],
        )
    connection.assert_not_called()


def test_only_v155_executes_and_v150_remains_pending(monkeypatch):
    plan = [
        m
        for m in migrations.load_migrations()
        if m.version not in migrations.DEV_ONLY_MIGRATION_VERSIONS
    ]
    cursor = Mock()
    cursor.fetchall.return_value = [
        (m.version, m.sha256) for m in plan if m.version not in {"V150", "V155"}
    ]
    connection = Mock()
    connection.cursor.return_value = nullcontext(cursor)
    monkeypatch.setattr(migrations, "connect", lambda *a, **k: nullcontext(connection))
    monkeypatch.setattr(migrations, "_reconciled_legacy_migrations", lambda *a: {})
    applied = migrations.apply_migrations(
        Mock(),
        migrations.PROD_DATABASE,
        "reviewed-commit",
        county_context_only=True,
        expected_pending=[entry("V150"), entry("V155")],
    )
    assert applied == ["V155"]
    assert connection.execute_string.call_count == 1
    sql = connection.execute_string.call_args.args[0]
    assert "CURRENT_COUNTY_OBSERVATIONS_V COPY GRANTS" in sql
    assert "CLEANUP" not in sql
    recorded = [
        call for call in cursor.execute.call_args_list if call.args[0].lstrip().startswith("INSERT")
    ]
    assert len(recorded) == 1 and recorded[0].args[1][0] == "V155"


def test_view_replacement_uses_existing_owner_without_new_grants():
    migration = next(m for m in migrations.load_migrations() if m.version == "V155")
    assert (
        migrations.migration_execution_role(migration, migrations.PROD_DATABASE)
        == "OH_LYME_PROD_OWNER"
    )
    assert "GRANT " not in migration.source


@pytest.mark.parametrize("rows", [[], [("wrong", "bundle")]])
def test_deployment_stops_on_release_change(rows):
    script = runpy.run_path(str(ROOT / "scripts/apply_county_context_migration.py"))
    cursor = Mock()
    cursor.fetchall.return_value = rows
    with pytest.raises(ValueError, match="CONTEXT_RELEASE_BINDING"):
        script["snapshot"](cursor, deployed=False)
    assert cursor.execute.call_count == 1


def test_deployment_entry_requires_protected_production_environment(monkeypatch):
    script = runpy.run_path(str(ROOT / "scripts/apply_county_context_migration.py"))
    monkeypatch.delenv("COUNTY_CONTEXT_ONLY", raising=False)
    with pytest.raises(SystemExit, match="CONTEXT_PROTECTED_PROD_REQUIRED"):
        script["main"]()
