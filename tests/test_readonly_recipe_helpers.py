"""Safety boundaries and timestamp semantics for the fixed read-only recipes."""

import json
import runpy
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = runpy.run_path(str(ROOT / "scripts/verify_atlas_readonly_recipes.py"))


def test_timestamp_roundtrip_accepts_equivalent_utc_serialization_but_not_loss():
    assert HELPER["same_timestamp"]("2026-01-03T03:04:05Z", "2026-01-03T03:04:05+00:00")
    assert not HELPER["same_timestamp"]("2026-01-03T03:04:06Z", "2026-01-03T03:04:05+00:00")
    assert not HELPER["same_timestamp"](datetime(2026, 1, 3, 3, 4, 5), "2026-01-03T03:04:05+00:00")


def test_wrong_driver_identity_stops_before_any_recipe_execution():
    calls = []

    class Cursor:
        def execute(self, query):
            calls.append(query)

        def fetchone(self):
            return "OH_LYME_PROD_READ", "ONE_HEALTH_LYME_GAP_ATLAS_PROD"

    with pytest.raises(ValueError, match="unexpected driver identity"):
        HELPER["cursor_checks"](Cursor())
    assert calls == ["SELECT CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()"]


def test_cli_identity_mismatch_never_connects_driver(monkeypatch):
    import snowflake.connector

    monkeypatch.setattr(snowflake.connector, "__version__", HELPER["CONNECTOR_VERSION"])
    row = {
        "CURRENT_ROLE": "OH_LYME_PROD_READ",
        "CURRENT_DATABASE": "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
    }
    monkeypatch.setattr(
        "subprocess.run",
        lambda *_args, **_kwargs: type("Result", (), {"stdout": json.dumps([row])})(),
    )
    monkeypatch.setattr(
        snowflake.connector,
        "connect",
        lambda **_kwargs: pytest.fail("must not connect on mismatch"),
    )
    report = HELPER["verify_dev"]()
    assert report["status"] == "BLOCKED"
    assert report["reason"] == "UNEXPECTED_DEV_IDENTITY"
    assert report["mutation_started"] is False


def test_private_cli_failure_is_constant_unknown_without_echo(monkeypatch, capsys):
    import snowflake.connector

    monkeypatch.setattr(snowflake.connector, "__version__", HELPER["CONNECTOR_VERSION"])

    def fail(*_args, **_kwargs):
        raise RuntimeError("private diagnostic and parameters must not be retained")

    monkeypatch.setattr("subprocess.run", fail)
    report = HELPER["verify_dev"]()
    assert report["status"] == "UNKNOWN"
    assert report["reason"] == "READ_ONLY_CHECK_UNAVAILABLE"
    assert "private" not in json.dumps(report)
    assert capsys.readouterr() == ("", "")


def test_unreviewed_driver_version_blocks_before_any_connection(monkeypatch):
    import snowflake.connector

    monkeypatch.setattr(snowflake.connector, "__version__", "unreviewed")
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: pytest.fail("must not inspect"))
    assert HELPER["verify_dev"]()["reason"] == "DRIVER_VERSION_NOT_REVIEWED"
