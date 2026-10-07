"""Offline deadline proof for the exact feed prerequisite batch."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

from typer.testing import CliRunner

from lyme_gap_atlas_data import cli
from lyme_gap_atlas_data.ingestion import intelligence_runtime as runtime


def reviewed():
    return [
        {
            "version": "V999",
            "filename": "V999__offline_fixture.sql",
            "sha256": runtime.INTELLIGENCE_PREREQUISITE_SHA256,
        }
    ]


def timer(monkeypatch, events):
    class Timer:
        def __init__(self, seconds, callback, args):
            assert seconds == 50 and callback is os._exit and args == (124,)
            self.daemon = False

        def start(self):
            assert self.daemon
            events.append("start")

        def cancel(self):
            events.append("cancel")

    monkeypatch.setattr(runtime.threading, "Timer", Timer)


def test_deadline_covers_settings_guards_apply_and_cleanup(monkeypatch):
    events = []
    timer(monkeypatch, events)
    monkeypatch.setattr(runtime, "verify_prerequisite_identity", lambda *_: None)
    monkeypatch.setenv("ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS", "30")

    def settings():
        assert events == ["start"]
        assert os.environ["ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS"] == "10"
        events.append("settings")
        return object()

    def pending(*args):
        events.append("pending")
        return reviewed()

    def reconcile(*args):
        assert os.environ["ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS"] == "10"
        events.append("reconcile")
        return []

    def apply(*args, **kwargs):
        assert kwargs["expected_pending"] == reviewed()
        events.append("apply")
        return ["V999"]

    monkeypatch.setattr(cli, "_settings", settings)
    monkeypatch.setattr(cli, "pending_migration_plan", pending)
    monkeypatch.setattr(cli, "reconcile_legacy_dev_migrations", reconcile)
    monkeypatch.setattr(cli, "apply_migrations", apply)
    result = CliRunner().invoke(
        cli.app,
        [
            "pipeline",
            "apply-reviewed-dev-migrations",
            "--database",
            "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            "--expected-pending-json",
            json.dumps(reviewed()),
            "--confirm",
        ],
    )
    assert result.exit_code == 0, result.exception
    assert events == ["start", "settings", "pending", "reconcile", "apply", "cancel"]
    assert os.environ["ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS"] == "30"


def test_mixed_batch_is_rejected_before_settings_or_connection(monkeypatch):
    settings = Mock()
    monkeypatch.setattr(cli, "_settings", settings)
    mixed = reviewed() + [{"version": "V998", "filename": "V998__other.sql", "sha256": "a" * 64}]
    result = CliRunner().invoke(
        cli.app,
        [
            "pipeline",
            "apply-reviewed-dev-migrations",
            "--database",
            "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            "--expected-pending-json",
            json.dumps(mixed),
            "--confirm",
        ],
    )
    assert result.exit_code != 0
    settings.assert_not_called()


def test_pending_mismatch_still_cannot_mutate_and_restores_environment(monkeypatch):
    events = []
    timer(monkeypatch, events)
    monkeypatch.setattr(runtime, "verify_prerequisite_identity", lambda *_: None)
    monkeypatch.delenv("ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(cli, "_settings", Mock())
    monkeypatch.setattr(cli, "pending_migration_plan", lambda *_: [])
    apply, reconcile = Mock(), Mock()
    monkeypatch.setattr(cli, "apply_migrations", apply)
    monkeypatch.setattr(cli, "reconcile_legacy_dev_migrations", reconcile)
    result = CliRunner().invoke(
        cli.app,
        [
            "pipeline",
            "apply-reviewed-dev-migrations",
            "--database",
            "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            "--expected-pending-json",
            json.dumps(reviewed()),
            "--confirm",
        ],
    )
    assert result.exit_code != 0
    apply.assert_not_called()
    reconcile.assert_not_called()
    assert events == ["start", "cancel"]
    assert "ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS" not in os.environ


def test_checksum_tracks_existing_canonical_sql_bytes():
    data = (
        Path(__file__).parents[1] / "docs/contracts/intelligence/v2/dev-minimum-access-reviewed.sql"
    ).read_bytes()
    assert hashlib.sha256(data).hexdigest() == runtime.INTELLIGENCE_PREREQUISITE_SHA256


def test_real_process_exits_while_settings_are_blocked_without_sql():
    code = """
import json, threading, time
from typer.testing import CliRunner
from lyme_gap_atlas_data import cli
from lyme_gap_atlas_data.ingestion import intelligence_runtime as runtime
timer = threading.Timer
threading.Timer = lambda seconds, callback, args: timer(0.1, callback, args=args)
cli._settings = lambda: time.sleep(5)
reviewed = [{"version":"V999","filename":"V999__offline_fixture.sql",
             "sha256":runtime.INTELLIGENCE_PREREQUISITE_SHA256}]
CliRunner().invoke(cli.app,["pipeline","apply-reviewed-dev-migrations","--database","ONE_HEALTH_LYME_GAP_ATLAS_DEV","--expected-pending-json",json.dumps(reviewed),"--confirm"])
raise AssertionError("blocked settings escaped deadline")
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=20)
    assert result.returncode == 124


def test_deadline_preserves_stronger_existing_statement_timeout(monkeypatch):
    events = []
    timer(monkeypatch, events)
    monkeypatch.setenv("ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS", "5")
    with runtime.prerequisite_batch_deadline():
        assert os.environ["ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS"] == "5"
    assert os.environ["ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS"] == "5"
    assert events == ["start", "cancel"]
