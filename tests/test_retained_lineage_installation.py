"""Only the exact approved, expiring diagnostic DDL may reach protected PROD."""

import runpy
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from lyme_gap_atlas_data import migrations

ROOT = Path(__file__).parents[1]
COMMIT = "a" * 40


def test_exact_authorized_sql_and_protected_workflow(monkeypatch):
    helper = runpy.run_path(str(ROOT / "scripts/apply_retained_lineage_migration.py"))
    clock = Mock()
    clock.now.return_value = datetime(2026, 10, 18, tzinfo=UTC)
    clock.side_effect = datetime
    monkeypatch.setitem(helper["verify_artifacts"].__globals__, "datetime", clock)
    migration = helper["verify_artifacts"]()
    sql = migrations.render_migration(migration, migrations.PROD_DATABASE)
    assert sql.count("CREATE SECURE VIEW ") == 4
    assert sql.count("GRANT SELECT ON VIEW ") == 4
    assert "CREATE OR REPLACE" not in sql
    assert sql.count("CURRENT_TIMESTAMP()<TO_TIMESTAMP_TZ('2026-10-25T00:00:00Z')") == 4
    workflow = yaml.safe_load((ROOT / ".github/workflows/promote-prod.yml").read_text())
    job = workflow["jobs"]["retained-lineage"]
    assert job["environment"] == "production"
    assert job["permissions"] == {"contents": "read", "checks": "read"}
    assert job["env"]["SNOWFLAKE_ROLE"] == "${{ secrets.SNOWFLAKE_ROLE }}"
    for other in ("promote", "january-climate"):
        assert "inputs.retained_lineage_only != true" in workflow["jobs"][other]["if"]
    with pytest.raises(ValueError, match="PROD-only"):
        migrations.render_migration(migration, migrations.DEV_DATABASE)


@pytest.mark.parametrize("replay", [False, True])
def test_scope_preserves_prior_model_installation_and_pending_v150(monkeypatch, replay):
    parents = {
        "V137",
        "V148",
        "V151",
        "V152",
        "V153",
        "V154",
        "V155",
        "V156",
        "V157",
        "V158",
        "V159",
    }
    plan = [m for m in migrations.load_migrations() if m.version in parents | {"V150", "V160"}]
    target = next(m for m in plan if m.version == "V160")
    applied = [(m.version, m.sha256) for m in plan if m.version in parents]
    reviewed = [migrations._migration_metadata(m) for m in plan if m.version not in parents]
    if replay:
        applied.append((target.version, target.sha256))
    cursor = Mock()
    cursor.fetchall.side_effect = (
        [applied, [(target.filename, target.sha256, COMMIT)]] if replay else [applied]
    )
    connection = Mock()
    connection.cursor.side_effect = lambda: nullcontext(cursor)
    connection.execute_string.return_value = []
    monkeypatch.setattr(migrations, "load_migrations", lambda: plan)
    monkeypatch.setattr(migrations, "connect", lambda *_, **__: nullcontext(connection))
    monkeypatch.setattr(migrations, "_reconciled_legacy_migrations", lambda *_: {})
    monkeypatch.setattr(migrations, "_migration_settings", lambda settings, *_: settings)
    assert migrations.apply_migrations(
        Mock(),
        migrations.PROD_DATABASE,
        COMMIT,
        expected_pending=reviewed,
        retained_lineage_only=True,
    ) == ([] if replay else ["V160"])
    assert connection.execute_string.call_count == (0 if replay else 1)
    if not replay:
        assert (
            "CREATE SECURE VIEW LINEAGE_AUDIT.RETAINED_MODEL_RELEASES_V"
            in connection.execute_string.call_args.args[0]
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"database": migrations.DEV_DATABASE},
        {"commit": None},
        {"release_integrity_only": True},
        {"expected_pending": []},
    ],
)
def test_rejects_unapproved_scope_before_connect(monkeypatch, extra):
    connection = Mock()
    monkeypatch.setattr(migrations, "connect", connection)
    args = dict(
        database=migrations.PROD_DATABASE,
        commit=COMMIT,
        expected_pending=[{"version": "V150"}],
        retained_lineage_only=True,
    )
    args.update(extra)
    with pytest.raises(PermissionError):
        migrations.apply_migrations(Mock(), **args)
    connection.assert_not_called()


def test_authorized_body_drift_and_expiry_fail_closed(monkeypatch):
    helper = runpy.run_path(str(ROOT / "scripts/apply_retained_lineage_migration.py"))
    verify = helper["verify_artifacts"]
    target = next(m for m in migrations.load_migrations() if m.version == "V160")
    monkeypatch.setitem(
        verify.__globals__,
        "load_migrations",
        lambda: [
            replace(
                target,
                source=target.source
                + "GRANT SELECT ON ALL TABLES IN SCHEMA PRESENTATION TO ROLE OH_LYME_PROD_READ;\n",
            )
        ],
    )
    with pytest.raises(ValueError, match="DIFFERS_FROM_AUTHORIZED"):
        verify()
    monkeypatch.setitem(verify.__globals__, "load_migrations", lambda: [target])
    clock = Mock()
    clock.now.return_value = datetime(2026, 10, 25, tzinfo=UTC)
    clock.side_effect = datetime
    monkeypatch.setitem(verify.__globals__, "datetime", clock)
    with pytest.raises(ValueError, match="EXPIRED"):
        verify()


def test_chat_or_local_execution_cannot_replace_protected_environment(monkeypatch):
    helper = runpy.run_path(str(ROOT / "scripts/apply_retained_lineage_migration.py"))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(SystemExit, match="PROTECTED_REVIEWED_MAIN"):
        helper["main"]()
