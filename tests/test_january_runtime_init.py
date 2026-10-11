"""The protected runtime smoke reports only finite initialization facts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_january_runtime_init.py"
WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/deploy-dev.yml"
SPEC = importlib.util.spec_from_file_location("january_runtime_init", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runtime_init = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_init)


def parameters() -> dict[str, object]:
    return {
        "account": "FIXTURE_ACCOUNT",
        "user": "OH_LYME_DEV_PIPELINE_SVC",
        "role": "OH_LYME_DEV_RUNTIME",
        "database": "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
        "warehouse": "OH_LYME_DEV_INGEST_XS_WH",
    }


@pytest.fixture(autouse=True)
def approved_budget(monkeypatch):
    monkeypatch.setenv("JANUARY_DIAGNOSTIC_BUDGET_EVIDENCE", "fixture")
    monkeypatch.setattr(
        runtime_init,
        "budget_evidence",
        lambda _: {
            "standard_capability_evidence": {
                "account_locator_sha256": hashlib.sha256(b"FIXTURE_ACCOUNT").hexdigest()
            }
        },
    )


def test_key_parse_failure_reports_stage_without_secret(monkeypatch, capsys):
    monkeypatch.setattr(runtime_init, "SnowflakeSettings", lambda: None)
    monkeypatch.setattr(
        runtime_init,
        "connection_parameters",
        lambda _: (_ for _ in ()).throw(ValueError("private key SECRET")),
    )
    monkeypatch.setattr(runtime_init, "connect", lambda **_: pytest.fail("must not connect"))
    assert runtime_init.main() == 1
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "status": "BLOCKED",
        "stage": "KEY_PARSE",
        "exception_type": "ValueError",
    }
    assert "SECRET" not in output


def test_connection_initializes_without_sql(monkeypatch, capsys):
    closed = []
    monkeypatch.setattr(runtime_init, "SnowflakeSettings", lambda: None)
    monkeypatch.setattr(runtime_init, "connection_parameters", lambda _: parameters())
    monkeypatch.setattr(
        runtime_init,
        "connect",
        lambda **kwargs: (
            closed.append(kwargs),
            SimpleNamespace(close=lambda **_: closed.append("closed")),
        )[1],
    )
    assert runtime_init.main() == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "CONNECTED_NO_SQL",
        "stage": "CONNECT",
    }
    assert closed[-1] == "closed"
    assert closed[0]["login_timeout"] == 5
    assert closed[0]["role"] == "OH_LYME_DEV_RUNTIME"


def test_missing_account_stops_before_connect(monkeypatch, capsys):
    monkeypatch.setattr(runtime_init, "SnowflakeSettings", lambda: None)
    monkeypatch.setattr(
        runtime_init,
        "connection_parameters",
        lambda _: parameters() | {"account": ""},
    )
    monkeypatch.setattr(runtime_init, "connect", lambda **_: pytest.fail("must not connect"))
    assert runtime_init.main() == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "BLOCKED",
        "stage": "CONFIGURED_IDENTITY",
    }


def test_protected_smoke_exits_before_migration_and_pair():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert (
        workflow[True]["workflow_dispatch"]["inputs"]["diagnose_january_runtime_init"]["type"]
        == "boolean"
    )
    step = next(
        step["run"]
        for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("name") == "Configure and verify the DEV Snowflake service connection"
    )
    smoke = step.split('if [ "$DIAGNOSE_JANUARY_RUNTIME_INIT" = "true" ]; then', 1)[1].split(
        'if [ "$DIAGNOSE_JANUARY_PAIR" = "true" ]; then', 1
    )[0]
    assert "verify_january_runtime_init.py" in smoke
    assert "timeout 25s" in smoke
    assert 'test -n "$JANUARY_DIAGNOSTIC_BUDGET_EVIDENCE"' in smoke
    assert "exit 0" in smoke
    assert "apply-reviewed-dev-migrations" not in smoke
    assert "verify_january_donor_dev.py" not in smoke
