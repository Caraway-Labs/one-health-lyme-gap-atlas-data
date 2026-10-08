"""Offline deadline proof for the exact feed prerequisite batch."""

import json
import os
import subprocess
import sys
from unittest.mock import Mock

from typer.testing import CliRunner

from lyme_gap_atlas_data import cli
from lyme_gap_atlas_data.ingestion import intelligence_runtime as runtime
from lyme_gap_atlas_data.migrations import (
    INTELLIGENCE_PREREQUISITE_MIGRATION,
    load_migrations,
)


def reviewed():
    item = next(item for item in load_migrations() if item.version == "V142")
    return [{"version": item.version, "filename": item.filename, "sha256": item.sha256}]


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
        assert kwargs["protected_intelligence_prerequisite"] is True
        events.append("apply")
        return ["V142"]

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
            "--feed-preflight-accounting-confirmed",
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


def test_accounting_confirmation_is_required_before_settings(monkeypatch):
    settings = Mock()
    monkeypatch.setattr(cli, "_settings", settings)
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
    settings.assert_not_called()


def test_wrong_identity_stops_before_pending_or_mutation(monkeypatch):
    events = []
    timer(monkeypatch, events)
    monkeypatch.setattr(cli, "_settings", lambda: events.append("settings") or object())

    def wrong_identity(*_):
        assert events == ["start", "settings"]
        events.append("identity")
        raise PermissionError("INTELLIGENCE_PREREQUISITE_IDENTITY")

    monkeypatch.setattr(runtime, "verify_prerequisite_identity", wrong_identity)
    pending, reconcile, apply = Mock(), Mock(), Mock()
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
            "--feed-preflight-accounting-confirmed",
            "--confirm",
        ],
    )
    assert result.exit_code != 0
    assert events == ["start", "settings", "identity", "cancel"]
    pending.assert_not_called()
    reconcile.assert_not_called()
    apply.assert_not_called()


def test_v142_metadata_drift_cannot_fall_through_generic_route(monkeypatch):
    settings = Mock()
    monkeypatch.setattr(cli, "_settings", settings)
    for changed in (
        reviewed()[0] | {"sha256": "a" * 64},
        reviewed()[0] | {"filename": "V142__wrong.sql"},
        reviewed()[0] | {"version": "V999"},
    ):
        result = CliRunner().invoke(
            cli.app,
            [
                "pipeline",
                "apply-reviewed-dev-migrations",
                "--database",
                "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
                "--expected-pending-json",
                json.dumps([changed]),
                "--feed-preflight-accounting-confirmed",
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
            "--feed-preflight-accounting-confirmed",
            "--confirm",
        ],
    )
    assert result.exit_code != 0
    apply.assert_not_called()
    reconcile.assert_not_called()
    assert events == ["start", "cancel"]
    assert "ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS" not in os.environ


def test_checksum_tracks_numbered_migration_bytes():
    assert reviewed() == [INTELLIGENCE_PREREQUISITE_MIGRATION]


def test_real_process_exits_while_settings_are_blocked_without_sql():
    code = """
import json, threading, time
from typer.testing import CliRunner
from lyme_gap_atlas_data import cli
from lyme_gap_atlas_data.migrations import load_migrations
timer = threading.Timer
threading.Timer = lambda seconds, callback, args: timer(0.1, callback, args=args)
cli._settings = lambda: time.sleep(5)
item = next(item for item in load_migrations() if item.version == "V142")
reviewed = [{"version":item.version,"filename":item.filename,"sha256":item.sha256}]
CliRunner().invoke(cli.app,["pipeline","apply-reviewed-dev-migrations","--database","ONE_HEALTH_LYME_GAP_ATLAS_DEV","--expected-pending-json",json.dumps(reviewed),"--feed-preflight-accounting-confirmed","--confirm"])
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
