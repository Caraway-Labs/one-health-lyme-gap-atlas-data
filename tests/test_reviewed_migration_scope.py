"""Offline proof that protected DEV scope mismatches never reach mutation."""

import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from snowflake.connector.errors import ProgrammingError
from typer.testing import CliRunner

from lyme_gap_atlas_data import cli, migrations


def metadata(version: str) -> dict[str, str]:
    return {"version": version, "filename": f"{version}__fixture.sql", "sha256": "a" * 64}


@pytest.mark.parametrize("with_cleanup", [False, True])
def test_cdc_scope_preserves_pending_cleanup(monkeypatch, with_cleanup):
    all_migrations = migrations.load_migrations()
    plan = [m for m in all_migrations if m.version in {"V149", "V150", "V155", "V156"}]
    applied = [
        (m.version, m.sha256)
        for m in plan
        if m.version in {"V149", "V155"} or (not with_cleanup and m.version == "V150")
    ]
    monkeypatch.setattr(migrations, "load_migrations", lambda: plan)
    monkeypatch.setattr(migrations, "_reconciled_legacy_migrations", lambda *_: {})
    monkeypatch.setattr(migrations, "_migration_settings", lambda settings, *_: settings)
    cursor = Mock()
    cursor.fetchall.return_value = applied
    connection = Mock()
    connection.cursor.side_effect = lambda: nullcontext(cursor)
    monkeypatch.setattr(migrations, "connect", lambda *_, **__: nullcontext(connection))
    reviewed = [migrations._migration_metadata(m) for m in plan if m.version not in dict(applied)]
    if not with_cleanup:
        with pytest.raises(PermissionError):
            migrations.apply_migrations(
                Mock(), migrations.PROD_DATABASE, expected_pending=reviewed, cdc_admission_only=True
            )
        connection.execute_string.assert_not_called()
        return
    assert migrations.apply_migrations(
        Mock(), migrations.PROD_DATABASE, expected_pending=reviewed, cdc_admission_only=True
    ) == ["V156"]
    assert connection.execute_string.call_count == 1
    assert "CDC_SOURCE_AUTHORITY_BASE_V" in connection.execute_string.call_args.args[0]


@pytest.mark.parametrize(
    "database,scope",
    [
        (migrations.DEV_DATABASE, [metadata("V156")]),
        (migrations.PROD_DATABASE, None),
        (migrations.PROD_DATABASE, [metadata("V155"), metadata("V156")]),
    ],
)
def test_cdc_invalid_scope_never_connects(monkeypatch, database, scope):
    connect = Mock()
    monkeypatch.setattr(migrations, "connect", connect)
    with pytest.raises(PermissionError):
        migrations.apply_migrations(
            Mock(), database, expected_pending=scope, cdc_admission_only=True
        )
    connect.assert_not_called()


@pytest.mark.parametrize(
    "actual,reviewed",
    [
        ([metadata("V134"), metadata("V135")], [metadata("V134")]),
        ([metadata("V134")], [metadata("V134"), metadata("V135")]),
        ([metadata("V135")], []),
        ([], [metadata("V135")]),
        ([metadata("V135") | {"sha256": "b" * 64}], [metadata("V135")]),
        ([metadata("V135") | {"filename": "V135__changed.sql"}], [metadata("V135")]),
    ],
)
def test_scope_mismatch_stops_before_reconciliation_and_application(
    monkeypatch: pytest.MonkeyPatch,
    actual: list[dict[str, str]],
    reviewed: list[dict[str, str]],
) -> None:
    monkeypatch.setattr(cli, "_settings", Mock())
    monkeypatch.setattr(cli, "pending_migration_plan", lambda *_: actual)
    reconcile = Mock()
    apply = Mock()
    monkeypatch.setattr(cli, "reconcile_legacy_dev_migrations", reconcile)
    monkeypatch.setattr(cli, "apply_migrations", apply)
    result = CliRunner().invoke(
        cli.app,
        [
            "pipeline",
            "apply-reviewed-dev-migrations",
            "--database",
            migrations.DEV_DATABASE,
            "--expected-pending-json",
            json.dumps(reviewed),
            "--confirm",
        ],
    )
    assert result.exit_code != 0
    assert "pending_migrations" in result.stdout
    assert json.loads(result.stdout)["pending_migrations"] == actual
    reconcile.assert_not_called()
    apply.assert_not_called()


@pytest.mark.parametrize("reviewed", [[], [metadata("V135")], [metadata("V134"), metadata("V135")]])
def test_exact_approved_set_reconciles_then_applies_with_second_guard(
    monkeypatch: pytest.MonkeyPatch, reviewed: list[dict[str, str]]
) -> None:
    settings = object()
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(cli, "pending_migration_plan", lambda *_: list(reversed(reviewed)))
    calls = Mock()
    calls.reconcile.return_value = []
    calls.apply.return_value = [item["version"] for item in reviewed]
    monkeypatch.setattr(cli, "reconcile_legacy_dev_migrations", calls.reconcile)
    monkeypatch.setattr(cli, "apply_migrations", calls.apply)
    result = CliRunner().invoke(
        cli.app,
        [
            "pipeline",
            "apply-reviewed-dev-migrations",
            "--database",
            migrations.DEV_DATABASE,
            "--expected-pending-json",
            json.dumps(reviewed),
            "--confirm",
        ],
    )
    assert result.exit_code == 0, result.exception
    assert [call[0] for call in calls.mock_calls] == ["reconcile", "apply"]
    calls.apply.assert_called_once_with(
        settings,
        migrations.DEV_DATABASE,
        None,
        expected_pending=reviewed,
        protected_intelligence_prerequisite=False,
    )


@pytest.mark.parametrize("value", ["", "null", "{}", "[{}]", '[{"version":"V135"}]'])
def test_missing_or_malformed_review_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        migrations.parse_reviewed_pending_set(value)


def test_duplicate_review_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        migrations.parse_reviewed_pending_set(json.dumps([metadata("V135")] * 2))


def test_unreadable_pending_ledger_is_not_an_empty_set(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = Mock()
    cursor.execute.side_effect = ProgrammingError("ledger unavailable")
    connection = SimpleNamespace(cursor=lambda: nullcontext(cursor))
    monkeypatch.setattr(migrations, "connect", lambda *_, **__: nullcontext(connection))
    with pytest.raises(ProgrammingError):
        migrations.pending_migration_plan(Mock(), migrations.DEV_DATABASE)


def test_apply_rechecks_scope_before_sql_or_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    source = "SELECT 135;\n"
    migration = migrations.Migration(
        "V135", "V135__fixture.sql", source, hashlib.sha256(source.encode()).hexdigest()
    )
    monkeypatch.setattr(migrations, "load_migrations", lambda: [migration])
    cursor = Mock()
    cursor.fetchall.return_value = []
    connection = Mock()
    connection.cursor.return_value = nullcontext(cursor)
    monkeypatch.setattr(migrations, "connect", lambda *_, **__: nullcontext(connection))
    with pytest.raises(ValueError, match="reviewed pending set"):
        migrations.apply_migrations(Mock(), migrations.DEV_DATABASE, expected_pending=[])
    connection.execute_string.assert_not_called()
    connection.commit.assert_not_called()

    assert all(call.args[0].startswith(("SELECT", "USE")) for call in cursor.execute.call_args_list)


def test_generic_runner_cannot_execute_actual_v142(monkeypatch: pytest.MonkeyPatch) -> None:
    v142 = next(item for item in migrations.load_migrations() if item.version == "V142")
    monkeypatch.setattr(migrations, "load_migrations", lambda: [v142])
    cursor = Mock()
    cursor.fetchall.return_value = []
    connection = Mock()
    connection.cursor.side_effect = lambda: nullcontext(cursor)
    monkeypatch.setattr(migrations, "connect", lambda *_, **__: nullcontext(connection))
    for reviewed in (None, [migrations.INTELLIGENCE_PREREQUISITE_MIGRATION]):
        with pytest.raises(PermissionError, match="protected intelligence prerequisite"):
            migrations.apply_migrations(Mock(), migrations.DEV_DATABASE, expected_pending=reviewed)
    connection.execute_string.assert_not_called()
    connection.commit.assert_not_called()
    assert migrations.apply_migrations(
        Mock(),
        migrations.DEV_DATABASE,
        expected_pending=[migrations.INTELLIGENCE_PREREQUISITE_MIGRATION],
        protected_intelligence_prerequisite=True,
    ) == ["V142"]
    connection.execute_string.assert_called_once()


@pytest.mark.parametrize("count", [0, 1, 2])
def test_runner_applies_only_exact_reviewed_pending_set(
    monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    plan = []
    for index in range(count):
        version = f"V{134 + index}"
        source = f"SELECT {134 + index};\n"
        plan.append(
            migrations.Migration(
                version,
                f"{version}__fixture.sql",
                source,
                hashlib.sha256(source.encode()).hexdigest(),
            )
        )
    monkeypatch.setattr(migrations, "load_migrations", lambda: plan)
    cursor = Mock()
    cursor.fetchall.return_value = []
    connection = Mock()
    connection.cursor.side_effect = lambda: nullcontext(cursor)
    monkeypatch.setattr(migrations, "connect", lambda *_, **__: nullcontext(connection))
    reviewed = [
        {"version": item.version, "filename": item.filename, "sha256": item.sha256} for item in plan
    ]
    assert migrations.apply_migrations(
        Mock(), migrations.DEV_DATABASE, expected_pending=reviewed
    ) == [item.version for item in plan]
    assert connection.execute_string.call_count == count
    assert connection.commit.call_count == count


def test_inflight_v135_metadata_is_accepted_without_changing_migration() -> None:
    plan = migrations.migration_plan(migrations.DEV_DATABASE)
    v135 = next(item for item in plan if item["version"] == "V135")
    assert v135["filename"] == "V135__intelligence_item_revisions_and_captures.sql"
    assert migrations.parse_reviewed_pending_set(json.dumps([v135])) == [v135]


@pytest.mark.parametrize("database", [migrations.PROD_DATABASE, "ONE_HEALTH_LYME_GAP_ATLAS"])
def test_reviewed_dev_command_rejects_other_targets_before_connection(
    monkeypatch: pytest.MonkeyPatch, database: str
) -> None:
    settings = Mock()
    monkeypatch.setattr(cli, "_settings", settings)
    result = CliRunner().invoke(
        cli.app,
        [
            "pipeline",
            "apply-reviewed-dev-migrations",
            "--database",
            database,
            "--expected-pending-json",
            "[]",
            "--confirm",
        ],
    )
    assert result.exit_code != 0
    settings.assert_not_called()


def test_pending_plan_filters_environment_and_applied_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = Mock()
    cursor.fetchall.return_value = [("V134",)]
    connection = SimpleNamespace(cursor=lambda: nullcontext(cursor))
    monkeypatch.setattr(migrations, "connect", lambda *_, **__: nullcontext(connection))
    monkeypatch.setattr(
        migrations, "migration_plan", lambda _: [metadata("V134"), metadata("V135")]
    )
    assert migrations.pending_migration_plan(Mock(), migrations.DEV_DATABASE) == [metadata("V135")]


def test_workflow_uses_reviewed_input_without_expression_interpolation() -> None:
    workflow = Path(".github/workflows/deploy-dev.yml").read_text(encoding="utf-8")
    assert "EXPECTED_PENDING_JSON: ${{ inputs.expected_pending_json }}" in workflow
    assert '--expected-pending-json "$EXPECTED_PENDING_JSON"' in workflow
    assert "atlas-data pipeline apply-reviewed-dev-migrations" in workflow
    assert "atlas-data pipeline reconcile-legacy-dev-migrations" not in workflow
    assert "atlas-data pipeline apply-migrations" not in workflow
