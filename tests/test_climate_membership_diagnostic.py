"""Actual bounded adapter and single-session connector behavior, no database."""

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from lyme_gap_atlas_data import climate_membership_diagnostic as diag

QID = "00000000-0000-0000-0000-000000000001"


def evidence():
    return json.dumps(
        {
            "unit_price_usd": 20,
            "evidence_reference": "owner-billing-record-1",
            "verified_by": "fixture-owner",
            "verified_at": datetime.now(UTC).isoformat(),
        }
    )


class Cursor:
    sfqid = QID

    def __init__(self):
        self.sql = ""
        self.calls = []
        self.fail_donor = False
        self.warehouse = {
            "size": "X-Small",
            "type": "STANDARD",
            "generation": "1",
            "max_cluster_count": 1,
            "auto_suspend": 60,
            "enable_query_acceleration": False,
        }

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, sql, params=(), timeout=None):
        self.sql = sql
        self.calls.append((sql, timeout))
        if self.fail_donor and "r.source_manifest" in sql:
            error = RuntimeError("private-endpoint-and-credentials")
            error.errno = 2003
            error.sfqid = QID
            raise error

    @property
    def description(self):
        return [(key,) for key in self.warehouse]

    def fetchone(self):
        return (
            "OH_LYME_DEV_PIPELINE_SVC",
            "OH_LYME_DEV_RUNTIME",
            "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            "OH_LYME_DEV_INGEST_XS_WH",
        )

    def fetchall(self):
        if self.sql.startswith("SHOW"):
            return [tuple(self.warehouse.values())]
        return [(QID, "FAIL", 10, 0, 0)]


@pytest.fixture
def setup(monkeypatch):
    import lyme_gap_atlas_shared.settings
    import lyme_gap_atlas_shared.snowflake
    import snowflake.connector

    cursor = Cursor()
    parameters = []
    closed = []

    def connect(**kwargs):
        parameters.append(kwargs)
        return SimpleNamespace(cursor=lambda: cursor, close=lambda **kwargs: closed.append(kwargs))

    monkeypatch.setattr(snowflake.connector, "connect", connect)
    monkeypatch.setattr(lyme_gap_atlas_shared.settings, "SnowflakeSettings", lambda: None)
    monkeypatch.setattr(lyme_gap_atlas_shared.snowflake, "connection_parameters", lambda _: {})
    monkeypatch.setattr(diag.signal, "SIGALRM", 14, raising=False)
    monkeypatch.setattr(diag.signal, "ITIMER_REAL", 0, raising=False)
    monkeypatch.setattr(diag.signal, "signal", lambda *_: None)
    monkeypatch.setattr(diag.signal, "setitimer", lambda *_: None, raising=False)
    monkeypatch.setattr(diag.shutil, "disk_usage", lambda _: SimpleNamespace(free=1024**3))
    return cursor, parameters, closed


def test_failure_retains_exact_stage_query_and_role_without_driver_text(
    setup, monkeypatch, tmp_path
):
    cursor, parameters, closed = setup
    cursor.fail_donor = True
    monkeypatch.setattr(
        diag,
        "freeze_membership",
        lambda c, *_: c.execute("SELECT r.source_manifest FROM PRESENTATION.test"),
    )
    result = diag.diagnostic(tmp_path / diag.ARTIFACT_NAME, "a" * 40, evidence())
    receipt_text = (tmp_path / diag.RECEIPT_NAME).read_text()
    receipt = json.loads(receipt_text)
    assert receipt["failure"] == {
        "stage": "ANNUAL_DONOR",
        "category": "OBJECT_OR_ACCESS_UNAVAILABLE",
        "query_id": QID,
    }
    assert receipt["effective_context"][1] == "OH_LYME_DEV_RUNTIME"
    assert "private-endpoint" not in receipt_text and "effective_context" not in result
    assert len(parameters) == 1 and closed == [{"retry": False}]
    assert parameters[0]["session_parameters"]["STATEMENT_TIMEOUT_IN_SECONDS"] == 15
    assert parameters[0]["session_parameters"]["STATEMENT_QUEUED_TIMEOUT_IN_SECONDS"] == 5
    assert all(0 < timeout <= 15 for _, timeout in cursor.calls)
    assert receipt["usage_state"] == "SESSION_QUERY_HISTORY_NOT_BILLED_CHARGES"
    assert receipt["billing"]["actual_billed_usd"] is None


@pytest.mark.parametrize("mutation", ["generation", "acceleration", "clusters", "suspend", "disk"])
def test_assumptions_fail_before_source_read(setup, monkeypatch, tmp_path, mutation):
    cursor, _, _ = setup
    if mutation == "generation":
        cursor.warehouse["generation"] = "2"
    elif mutation == "acceleration":
        cursor.warehouse["enable_query_acceleration"] = True
    elif mutation == "clusters":
        cursor.warehouse["max_cluster_count"] = 2
    elif mutation == "suspend":
        cursor.warehouse["auto_suspend"] = 120
    else:
        monkeypatch.setattr(diag.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    monkeypatch.setattr(diag, "freeze_membership", lambda *_: pytest.fail("must not read sources"))
    assert (
        diag.diagnostic(tmp_path / diag.ARTIFACT_NAME, "a" * 40, evidence())["status"] == "BLOCKED"
    )


def test_statement_runtime_and_write_limits_prevent_execution(monkeypatch):
    raw = Cursor()
    receipt = {"statements": 40}
    bounded = diag.BoundedCursor(raw, diag.time.monotonic(), receipt)
    with pytest.raises(diag.DiagnosticStop, match="STATEMENT_LIMIT"):
        bounded.execute("SELECT 1")
    receipt["statements"] = 0
    with pytest.raises(diag.DiagnosticStop, match="READ_ONLY"):
        bounded.execute("GRANT SELECT ON test TO ROLE other")
    monkeypatch.setattr(diag.time, "monotonic", lambda: bounded.started + 300)
    with pytest.raises(diag.DiagnosticStop, match="RUNTIME_LIMIT"):
        bounded.execute("SELECT 1")
    assert raw.calls == []


def test_actual_connector_retry_context_cannot_advance_to_retry():
    from snowflake.connector.time_util import TimeoutBackoffCtx

    context = TimeoutBackoffCtx(backoff_generator=diag.no_retry_backoff())
    with pytest.raises(diag.DiagnosticStop, match="AUTOMATIC_RETRY_PROHIBITED"):
        context.increment()


def test_oversize_diagnostic_output_preserves_previous_artifact(setup, monkeypatch, tmp_path):
    output = tmp_path / diag.ARTIFACT_NAME
    output.write_text("previous")
    monkeypatch.setattr(diag, "MAX_ARTIFACT_BYTES", 1)

    def freeze(_cursor, path, _sha):
        path.write_text("oversize")
        return {}

    monkeypatch.setattr(diag, "freeze_membership", freeze)
    assert diag.diagnostic(output, "a" * 40, evidence())["status"] == "BLOCKED"
    assert output.read_text() == "previous"
    assert not (tmp_path / ("pending-" + diag.ARTIFACT_NAME)).exists()


@pytest.mark.parametrize("value", ["", "{}", '{"unit_price_usd":21}', '"private-value"'])
def test_missing_or_invalid_price_receipt_is_closed(value):
    with pytest.raises(diag.DiagnosticStop):
        diag.budget_evidence(value)


def test_actual_workflow_skips_separate_identity_session_for_diagnostic(tmp_path):
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    if not bash:
        pytest.skip("bash required")
    workflow = yaml.safe_load(Path(".github/workflows/run-ingestion.yml").read_text())
    step = next(
        s
        for s in workflow["jobs"]["ingest"]["steps"]
        if s.get("name") == "Execute orchestrator operation with ephemeral Snowflake key"
    )
    script = step["run"].replace("${{ inputs.operation }}", "nclimgrid-pilot-measurement")
    script = script.replace("${{ inputs.tier }}", "B").replace("${{ inputs.recapture }}", "false")
    log = tmp_path / "calls.txt"
    env = dict(os.environ) | {
        "RUNNER_TEMP": str(tmp_path),
        "TEST_UV_CALLS": str(log),
        "SNOWFLAKE_USER": "fixture",
        "SNOWFLAKE_ROLE": "fixture",
        "SNOWFLAKE_PRIVATE_KEY_B64": "QUJD",
        "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE": "fixture",
        "MEASUREMENT_ACTION": "frozen-membership",
        "INGESTION_RUN_ID": "fixture",
    }
    stub = 'uv() { printf "%s\\n" "$*" >> "$TEST_UV_CALLS"; };\n'
    result = subprocess.run(
        [bash, "--noprofile", "--norc", "-e", "-c", stub + script],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == [
        "run atlas-data source nclimgrid-pilot-measure --action frozen-membership --run-id fixture"
    ]
    assert not (tmp_path / "oh-lyme-ingestion-key.p8").exists()
