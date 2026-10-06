"""Actual bounded adapter and single-session connector behavior, no database."""

import json
import os
import shutil
import subprocess
import time
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
            "unit_price_usd": 6,
            "evidence_reference": "https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf",
            "verified_by": "fixture-owner",
            "verified_at": datetime.now(UTC).isoformat(),
            "region": "AWS_US_WEST_2",
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
        identity = (
            "OH_LYME_DEV_PIPELINE_SVC",
            "OH_LYME_DEV_RUNTIME",
            "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            "OH_LYME_DEV_INGEST_XS_WH",
        )
        return (*identity, "AWS_US_WEST_2") if "CURRENT_REGION" in self.sql else identity

    def fetchall(self):
        if self.sql.startswith("SHOW"):
            return [tuple(self.warehouse.values())]
        return [(QID, "FAIL", 10, 0, 0)]

    def get_result_batches(self):
        return []


@pytest.fixture
def setup(monkeypatch):
    import lyme_gap_atlas_shared.settings
    import lyme_gap_atlas_shared.snowflake
    import snowflake.connector

    cursor = Cursor()
    monkeypatch.setenv("JANUARY_DIAGNOSTIC_JOB_STARTED_UNIX", str(int(time.time())))
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
        cursor.warehouse["generation"] = "unsupported"
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


@pytest.mark.parametrize(
    "field,value,missing",
    [
        ("enable_query_acceleration", "false", False),
        ("generation", None, True),
        ("auto_suspend", None, False),
        ("max_cluster_count", 2, False),
    ],
)
def test_cost_failure_receipt_identifies_field_and_result_type_without_weakening_guard(
    setup, monkeypatch, tmp_path, field, value, missing
):
    cursor, parameters, _ = setup
    if missing:
        del cursor.warehouse[field]
    else:
        cursor.warehouse[field] = value
    cursor.warehouse["comment"] = "private-account-details"
    monkeypatch.setattr(diag, "freeze_membership", lambda *_: pytest.fail("no source reads"))
    result = diag.diagnostic(tmp_path / diag.ARTIFACT_NAME, "a" * 40, evidence())
    receipt_text = (tmp_path / diag.RECEIPT_NAME).read_text()
    receipt = json.loads(receipt_text)
    assert result["status"] == "BLOCKED"
    assert receipt["failure"]["category"] == "WAREHOUSE_COST_ASSUMPTIONS_UNVERIFIED"
    assert receipt["warehouse_cost_failed_fields"] == [field]
    assert receipt["warehouse_cost_observation"][field] == {
        "present": not missing,
        "python_type": type(value).__name__,
        "value": value,
    }
    assert "private-account-details" not in receipt_text
    assert len(parameters) == 1 and len(cursor.calls) == 2
    assert receipt["usage_state"] == "NOT_QUERIED"


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


def test_previous_success_is_not_relabelled_as_failed_transport_query():
    cursor = Cursor()
    receipt = {"statements": 0}
    bounded = diag.BoundedCursor(cursor, diag.time.monotonic(), receipt)
    bounded.execute("SELECT 1")

    def network_failure(*_, **__):
        raise RuntimeError("private-network-message")

    cursor.execute = network_failure
    with pytest.raises(diag.DiagnosticStop, match="READ_FAILED"):
        bounded.execute("SELECT r.source_manifest FROM PRESENTATION.test")
    assert receipt["failure"]["query_id"] is None
    assert receipt["failure"]["stage"] == "ANNUAL_DONOR"
    assert diag.failure_query_id(RuntimeError("fetch"), cursor, QID) is None
    error = RuntimeError("statement failure")
    error.sfqid = QID
    assert diag.failure_query_id(error, cursor, QID) == QID


def test_gen2_official_forecast_succeeds_without_claiming_billed_price(
    setup, monkeypatch, tmp_path
):
    cursor, _, _ = setup
    cursor.warehouse["generation"] = "2"
    value = json.loads(evidence()) | {
        "unit_price_usd": 4,
        "evidence_reference": "https://www.snowflake.com/en/pricing-options/",
        "region": "AWS_US_WEST_2",
    }

    def freeze(_cursor, path, _sha):
        path.write_text("verified")
        return {"writes_performed": False}

    monkeypatch.setattr(diag, "freeze_membership", freeze)
    report = diag.diagnostic(tmp_path / diag.ARTIFACT_NAME, "a" * 40, json.dumps(value))
    receipt = json.loads((tmp_path / diag.RECEIPT_NAME).read_text())
    assert report["status"] == "READ_ONLY_EXPORT_SUCCEEDED"
    assert receipt["published_warehouse_credits_per_hour"] == 1.35
    assert 30 <= receipt["runtime_limit_seconds"] <= 240
    assert receipt["compute_and_cloud_services_forecast_ceiling_usd"] + 1 <= 5
    assert receipt["forecast_basis"] == "OFFICIAL_PUBLIC_PRICE_FORECAST_NOT_ACCOUNT_INVOICE"
    assert receipt["billing"]["actual_billed_unit_price_usd"] is None


def test_combined_reservations_never_exceed_original_total_cap():
    seconds = diag.budget_runtime(6)
    assert seconds == 50
    aggregate = diag.PRIOR_DIAGNOSTIC_FORECAST_USD + ((seconds * 5.75 / 3600 + 1.35 / 60) * 6) + 1
    assert aggregate == pytest.approx(4.94375) and aggregate <= 5
    with pytest.raises(diag.DiagnosticStop, match="FORECAST_EXCEEDS_FIVE_DOLLAR_CAP"):
        diag.budget_runtime(20)


def test_execution_watchdog_caps_at_fifty_seconds_and_preserves_upload_reserve(
    setup, monkeypatch, tmp_path
):
    timers = []
    monkeypatch.setattr(diag.signal, "setitimer", lambda *args: timers.append(args))
    monkeypatch.setattr(diag, "freeze_membership", lambda *_: None)
    diag.diagnostic(tmp_path / diag.ARTIFACT_NAME, "a" * 40, evidence())
    receipt = json.loads((tmp_path / diag.RECEIPT_NAME).read_text())
    assert timers[0][1] == receipt["runtime_limit_seconds"] == 50
    assert receipt["cleanup_upload_reserved_seconds"] == 60 and diag.MAX_SECONDS == 300
    assert receipt["aggregate_forecast_ceiling_usd"] == pytest.approx(4.94375)
    assert receipt["billing"]["actual_billed_usd"] is None


def test_late_job_stops_before_connection_but_retains_receipt(setup, monkeypatch, tmp_path):
    _, parameters, _ = setup
    monkeypatch.setenv("JANUARY_DIAGNOSTIC_JOB_STARTED_UNIX", str(int(time.time()) - 240))
    report = diag.diagnostic(tmp_path / diag.ARTIFACT_NAME, "a" * 40, evidence())
    assert report["status"] == "BLOCKED" and not parameters
    receipt = json.loads((tmp_path / diag.RECEIPT_NAME).read_text())
    assert receipt["failure"]["category"] == "INSUFFICIENT_JOB_TIME_FOR_RECEIPT"


def test_private_billing_reference_is_rejected_in_log_visible_input():
    value = json.loads(evidence()) | {"evidence_reference": "private-account-invoice"}
    with pytest.raises(diag.DiagnosticStop, match="PUBLIC_PRICING_ONLY"):
        diag.budget_evidence(json.dumps(value))


def test_actual_remote_result_batch_cannot_start_chunk_download(monkeypatch):
    from snowflake.connector.result_batch import JSONResultBatch, RemoteChunkInfo

    batch = JSONResultBatch(
        1, {}, RemoteChunkInfo("https://example.invalid/chunk", 1, 1), [], [], False
    )
    raw = Cursor()
    raw.get_result_batches = lambda: [batch]
    downloads = []

    def download(*_, **__):
        downloads.append(True)
        pytest.fail("remote chunk GET is prohibited in this diagnostic")

    monkeypatch.setattr(batch, "_download", download)
    raw.fetchmany = lambda _: list(batch.create_iter())
    bounded = diag.BoundedCursor(raw, diag.time.monotonic(), {"statements": 0})
    with pytest.raises(diag.DiagnosticStop, match="REMOTE_RESULT_BATCH"):
        bounded.fetchmany(1000)
    assert downloads == []


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
