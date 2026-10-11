"""Actual V143 metadata must use the bounded intelligence migration route."""

import json
import os
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from lyme_gap_atlas_data import cli, migrations
from lyme_gap_atlas_data.ingestion import intelligence_runtime as runtime


def reviewed() -> list[dict[str, str]]:
    item = next(item for item in migrations.load_migrations() if item.version == "V143")
    return [{"version": item.version, "filename": item.filename, "sha256": item.sha256}]


def invoke(batch: list[dict[str, str]], *, accounting: bool = True):
    return CliRunner().invoke(
        cli.app,
        [
            "pipeline",
            "apply-reviewed-dev-migrations",
            "--database",
            migrations.DEV_DATABASE,
            "--expected-pending-json",
            json.dumps(batch),
            *(["--feed-preflight-accounting-confirmed"] if accounting else []),
            "--confirm",
        ],
    )


def test_actual_v143_checksum_and_dev_only_scope() -> None:
    assert reviewed() == [migrations.INTELLIGENCE_CLEANUP_MIGRATION]
    assert "V143" in {
        item["version"] for item in migrations.migration_plan(migrations.DEV_DATABASE)
    }
    assert "V143" not in {
        item["version"] for item in migrations.migration_plan(migrations.PROD_DATABASE)
    }


def test_deadline_identity_and_accounting_precede_v143_application(monkeypatch):
    events: list[str] = []

    class Timer:
        def __init__(self, seconds, callback, args):
            assert seconds == 50 and callback is os._exit and args == (124,)
            self.daemon = False

        def start(self):
            events.append("deadline")

        def cancel(self):
            events.append("cancel")

    monkeypatch.setattr(runtime.threading, "Timer", Timer)
    monkeypatch.setattr(cli, "_settings", lambda: events.append("settings") or object())
    monkeypatch.setattr(
        runtime, "verify_prerequisite_identity", lambda *_: events.append("identity")
    )
    monkeypatch.setattr(
        cli, "pending_migration_plan", lambda *_: events.append("pending") or reviewed()
    )
    monkeypatch.setattr(
        cli, "reconcile_legacy_dev_migrations", lambda *_: events.append("reconcile") or []
    )

    def apply(*_, **kwargs):
        assert kwargs["expected_pending"] == reviewed()
        assert kwargs["protected_intelligence_prerequisite"] is True
        events.append("apply")
        return ["V143"]

    monkeypatch.setattr(cli, "apply_migrations", apply)
    assert invoke(reviewed()).exit_code == 0
    assert events == ["deadline", "settings", "identity", "pending", "reconcile", "apply", "cancel"]
    events.clear()
    assert invoke(reviewed(), accounting=False).exit_code != 0
    assert events == []


def test_wrong_identity_and_mixed_v143_batch_stop_before_mutation(monkeypatch):
    pending, reconcile, apply = Mock(), Mock(), Mock()
    monkeypatch.setattr(cli, "pending_migration_plan", pending)
    monkeypatch.setattr(cli, "reconcile_legacy_dev_migrations", reconcile)
    monkeypatch.setattr(cli, "apply_migrations", apply)
    settings = Mock()
    monkeypatch.setattr(cli, "_settings", settings)
    mixed = reviewed() + [migrations.INTELLIGENCE_PREREQUISITE_MIGRATION]
    assert invoke(mixed).exit_code != 0
    settings.assert_not_called()
    monkeypatch.setattr(
        runtime,
        "verify_prerequisite_identity",
        lambda *_: (_ for _ in ()).throw(PermissionError("wrong identity")),
    )
    assert invoke(reviewed()).exit_code != 0
    pending.assert_not_called()
    reconcile.assert_not_called()
    apply.assert_not_called()


def test_generic_runner_cannot_silently_execute_v143(monkeypatch):
    actual = next(item for item in migrations.load_migrations() if item.version == "V143")
    monkeypatch.setattr(migrations, "load_migrations", lambda: [actual])
    cursor = Mock()
    cursor.fetchall.return_value = []
    connection = Mock()
    connection.cursor.side_effect = lambda: nullcontext(cursor)
    monkeypatch.setattr(migrations, "connect", lambda *_, **__: nullcontext(connection))
    for expected in (None, reviewed()):
        with pytest.raises(PermissionError, match="protected intelligence prerequisite"):
            migrations.apply_migrations(Mock(), migrations.DEV_DATABASE, expected_pending=expected)
    connection.execute_string.assert_not_called()
    assert migrations.apply_migrations(
        Mock(),
        migrations.DEV_DATABASE,
        expected_pending=reviewed(),
        protected_intelligence_prerequisite=True,
    ) == ["V143"]


def test_hosted_workflow_selector_routes_actual_v143() -> None:
    import yaml

    workflow = yaml.safe_load(
        (Path(__file__).parents[1] / ".github/workflows/deploy-dev.yml").read_text()
    )
    script = next(
        step["run"]
        for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("name") == "Configure and verify the DEV Snowflake service connection"
    )
    selector = script.split("feed_batch=\"$(uv run python - <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    environment = os.environ.copy()
    environment["EXPECTED_PENDING_JSON"] = json.dumps(reviewed())
    result = subprocess.run(
        [sys.executable, "-c", selector], capture_output=True, text=True, env=environment
    )
    assert result.returncode == 0 and result.stdout.strip() == "true"
