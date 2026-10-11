"""Actual bounded adapter and single-session connector behavior, no database."""

import base64
import hashlib
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
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from typer.testing import CliRunner

from lyme_gap_atlas_data import climate_membership_diagnostic as diag


def test_blocked_membership_cli_exits_nonzero_for_workflow_receipt(monkeypatch):
    from lyme_gap_atlas_data import cli
    from lyme_gap_atlas_data.ingestion import nclimgrid_pilot_measurement as measurement

    monkeypatch.setattr(
        measurement,
        "frozen_membership_report",
        lambda _run_id: {
            "status": "BLOCKED",
            "statements": 0,
            "receipt_name": diag.RECEIPT_NAME,
        },
    )
    result = CliRunner().invoke(
        cli.app,
        [
            "source",
            "nclimgrid-pilot-measure",
            "--action",
            "frozen-membership",
            "--run-id",
            "c2eb2146-005d-44d2-bac4-e2805ca42577",
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "status": "BLOCKED",
        "statements": 0,
        "receipt_name": diag.RECEIPT_NAME,
    }


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
            "name": "OH_LYME_DEV_INGEST_XS_WH",
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
        if "CURRENT_ACCOUNT()" in self.sql:
            return (*identity, "AWS_US_WEST_2", "FIXTURE_ACCOUNT")
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
    # Operational tests simulate an earlier affordable reservation; production remains exhausted.
    monkeypatch.setattr(diag, "PRIOR_DIAGNOSTIC_FORECAST_USD", 4.94375)
    monkeypatch.setenv(
        "JANUARY_DONOR_HANDOFF_PATH", "docs/contracts/climate/reviewed-donors/test.json"
    )
    monkeypatch.setenv("JANUARY_DONOR_HANDOFF_SHA256", "a" * 64)
    monkeypatch.setattr(
        diag,
        "read_donor_handoff",
        lambda *_: {
            "bundle_sha256": "b" * 64,
            "account_locator_sha256": hashlib.sha256(b"FIXTURE_ACCOUNT").hexdigest(),
            "region": "AWS_US_WEST_2",
        },
    )
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

    def freeze(_cursor, path, _sha, _donor):
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


def test_approved_pair_budget_reserves_donor_and_blocks_excess_price(monkeypatch):
    assert pytest.approx(17.788333333333334) == diag.PRIOR_DIAGNOSTIC_FORECAST_USD
    assert diag.APPROVED_TOTAL_FORECAST_USD == 25
    assert diag.producer_forecast(6) == pytest.approx(0.845)
    assert pytest.approx(20.52625) == (diag.PRIOR_DIAGNOSTIC_FORECAST_USD + 2.737916666666667)
    assert diag.budget_runtime(6) == 50
    monkeypatch.setattr(diag, "PRIOR_DIAGNOSTIC_FORECAST_USD", 24)
    with pytest.raises(diag.DiagnosticStop, match="FORECAST_EXCEEDS_APPROVED_TOTAL_CAP"):
        diag.budget_runtime(6)


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
    assert receipt["aggregate_forecast_ceiling_usd"] == pytest.approx(7.681666666666667)
    assert receipt["producer_forecast_reserved_usd"] == pytest.approx(0.845)
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


def standard_evidence():
    return json.dumps(
        json.loads(evidence())
        | {
            "standard_capability_evidence": {
                "edition": "STANDARD",
                "cloud": "AWS",
                "account_locator_sha256": hashlib.sha256(b"FIXTURE_ACCOUNT").hexdigest(),
                "verified_by": "fixture-owner",
                "verified_at": datetime.now(UTC).isoformat(),
                "evidence_reference": "OWNER_SNOWSIGHT_ACCOUNT_DETAILS",
            }
        }
    )


@pytest.mark.parametrize("clusters", [None, 0, 1])
def test_standard_capability_bound_preserves_unknown_or_zero_settings(
    setup, monkeypatch, tmp_path, clusters
):
    cursor, parameters, _ = setup
    cursor.warehouse.pop("enable_query_acceleration")
    if clusters is None:
        cursor.warehouse.pop("max_cluster_count")
    else:
        cursor.warehouse["max_cluster_count"] = clusters

    def freeze(_cursor, path, _sha, _donor):
        path.write_text("fixture membership")
        return {"writes_performed": False}

    monkeypatch.setattr(diag, "freeze_membership", freeze)
    result = diag.diagnostic(tmp_path / diag.ARTIFACT_NAME, "a" * 40, standard_evidence())
    receipt = json.loads((tmp_path / diag.RECEIPT_NAME).read_text())
    assert result["status"] == "READ_ONLY_EXPORT_SUCCEEDED"
    assert receipt["warehouse_cost_observation"]["max_cluster_count"]["value"] == clusters
    assert receipt["warehouse_cost_observation"]["enable_query_acceleration"]["present"] is False
    assert receipt["warehouse_assumptions"]["max_cluster_count"] == clusters
    assert receipt["edition_cost_capabilities"]["query_acceleration"] == "UNAVAILABLE"
    assert receipt["edition_cost_capabilities"]["compute_cluster_cost_bound"] == 1
    assert len(parameters) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_cluster_count", 2),
        ("max_cluster_count", True),
        ("enable_query_acceleration", True),
        ("enable_query_acceleration", "false"),
    ],
)
def test_standard_entitlement_does_not_hide_contradictory_properties(
    setup, monkeypatch, tmp_path, field, value
):
    cursor, _, _ = setup
    cursor.warehouse[field] = value
    monkeypatch.setattr(diag, "freeze_membership", lambda *_: pytest.fail("no membership read"))
    assert (
        diag.diagnostic(tmp_path / diag.ARTIFACT_NAME, "a" * 40, standard_evidence())["status"]
        == "BLOCKED"
    )


def test_standard_evidence_must_match_live_account_before_show(setup, monkeypatch, tmp_path):
    cursor, _, _ = setup
    value = json.loads(standard_evidence())
    value["standard_capability_evidence"]["account_locator_sha256"] = "a" * 64
    result = diag.diagnostic(tmp_path / diag.ARTIFACT_NAME, "a" * 40, json.dumps(value))
    receipt = json.loads((tmp_path / diag.RECEIPT_NAME).read_text())
    assert result["status"] == "BLOCKED"
    assert receipt["failure"]["category"] == "STANDARD_CAPABILITY_ACCOUNT_MISMATCH"
    assert len(cursor.calls) == 1


@pytest.mark.parametrize("mutation", ["edition", "future", "private_field"])
def test_standard_capability_receipt_rejects_unsupported_or_unreviewed_evidence(mutation):
    value = json.loads(standard_evidence())
    capability = value["standard_capability_evidence"]
    if mutation == "edition":
        capability["edition"] = "ENTERPRISE"
    elif mutation == "future":
        capability["verified_at"] = "2999-01-01T00:00:00Z"
    else:
        capability["account_identifier"] = "private-account"
    with pytest.raises(diag.DiagnosticStop, match="STANDARD_CAPABILITY_EVIDENCE"):
        diag.budget_evidence(json.dumps(value))


def test_owner_standard_evidence_does_not_expire_after_one_day():
    value = json.loads(standard_evidence())
    value["standard_capability_evidence"]["verified_at"] = "2025-01-01T00:00:00Z"
    assert (
        diag.budget_evidence(json.dumps(value))["standard_capability_evidence"]["edition"]
        == "STANDARD"
    )


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


def test_ordered_membership_remote_batch_requires_one_attempt_transport(monkeypatch):
    from snowflake.connector.result_batch import JSONResultBatch, RemoteChunkInfo

    batch = JSONResultBatch(
        1, {}, RemoteChunkInfo("https://example.invalid/chunk", 1, 1), [], [], False
    )
    raw = Cursor()
    raw.get_result_batches = lambda: [batch]
    raw.fetchmany = lambda _: [("fixture",)]
    bounded = diag.BoundedCursor(raw, diag.time.monotonic(), {"statements": 1})
    bounded.stage = "ORDERED_MEMBERSHIP"
    monkeypatch.setattr(diag.result_batch, "MAX_DOWNLOAD_RETRY", 10)
    with pytest.raises(diag.DiagnosticStop, match="REMOTE_RESULT_BATCH"):
        bounded.fetchmany(1000)
    original = diag.arm_single_attempt_result_downloads()
    try:
        assert original == 10
        assert bounded.fetchmany(1000) == [("fixture",)]
        bounded.stage = "PREFLIGHT"
        with pytest.raises(diag.DiagnosticStop, match="REMOTE_RESULT_BATCH"):
            bounded.fetchmany(1000)
    finally:
        diag.result_batch.MAX_DOWNLOAD_RETRY = original


def test_pinned_chunk_downloader_makes_one_get_on_failure(monkeypatch):
    from snowflake.connector.result_batch import JSONResultBatch, RemoteChunkInfo

    batch = JSONResultBatch(
        1, {}, RemoteChunkInfo("https://example.invalid/chunk", 1, 1), [], [], False
    )
    attempts = []

    def fail_get(**_):
        attempts.append(True)
        raise RuntimeError("synthetic transport failure")

    monkeypatch.setattr(
        diag.result_batch.SessionManagerFactory,
        "get_manager",
        lambda **_: SimpleNamespace(get=fail_get),
    )
    original = diag.arm_single_attempt_result_downloads()
    try:
        with pytest.raises(RuntimeError, match="synthetic transport failure"):
            batch._download()
        assert attempts == [True]
    finally:
        diag.result_batch.MAX_DOWNLOAD_RETRY = original


def test_oversize_diagnostic_output_preserves_previous_artifact(setup, monkeypatch, tmp_path):
    output = tmp_path / diag.ARTIFACT_NAME
    output.write_text("previous")
    monkeypatch.setattr(diag, "MAX_ARTIFACT_BYTES", 1)

    def freeze(_cursor, path, _sha, _donor):
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


@pytest.mark.parametrize(
    "path", ["", "outside/donor.json", "docs/contracts/climate/reviewed-donors/donor.txt"]
)
def test_missing_or_out_of_contract_donor_never_connects(setup, monkeypatch, tmp_path, path):
    _, parameters, _ = setup
    monkeypatch.setenv("JANUARY_DONOR_HANDOFF_PATH", path)
    result = diag.diagnostic(tmp_path / diag.ARTIFACT_NAME, "a" * 40, evidence())
    assert result["status"] == "BLOCKED"
    assert not parameters


def test_exhausted_approved_budget_never_connects_with_valid_handoff(setup, monkeypatch, tmp_path):
    _, parameters, _ = setup
    monkeypatch.setattr(diag, "PRIOR_DIAGNOSTIC_FORECAST_USD", 24)
    result = diag.diagnostic(tmp_path / diag.ARTIFACT_NAME, "a" * 40, evidence())
    assert result["status"] == "BLOCKED"
    assert not parameters


def test_key_initialization_error_reports_finite_substage_without_secret(
    setup, monkeypatch, tmp_path
):
    import lyme_gap_atlas_shared.snowflake

    _, connections, _ = setup
    monkeypatch.setattr(
        lyme_gap_atlas_shared.snowflake,
        "connection_parameters",
        lambda _: (_ for _ in ()).throw(ValueError("private key SECRET")),
    )
    report = diag.diagnostic(tmp_path / diag.ARTIFACT_NAME, "a" * 40, evidence())
    receipt_text = (tmp_path / diag.RECEIPT_NAME).read_text()
    receipt = json.loads(receipt_text)
    assert report["status"] == "BLOCKED" and not connections
    assert receipt["failure"]["stage"] == "PRE_CONNECTION"
    assert receipt["failure"]["initialization_substage"] == "KEY_PARSE"
    assert receipt["failure"]["category"] == "READ_DEPENDENCY_UNAVAILABLE"
    assert "SECRET" not in receipt_text


@pytest.mark.parametrize("escape", ["allowed_directory", "ancestor", "nested", "file"])
def test_symlink_escape_rejected_before_file_consumption_or_connection(
    setup, monkeypatch, tmp_path, escape
):
    _, parameters, _ = setup
    checkout = tmp_path / "checkout"
    outside = tmp_path / "outside"
    checkout.mkdir()
    outside.mkdir()
    (outside / "donor.json").write_text("outside content must not be consumed")
    allowed = checkout / "docs/contracts/climate/reviewed-donors"
    if escape == "ancestor":
        target = checkout / "docs"
        candidate = allowed / "donor.json"
        external_allowed = outside / "contracts/climate/reviewed-donors"
        external_allowed.mkdir(parents=True)
        (external_allowed / "donor.json").write_text("outside content must not be consumed")
    elif escape == "allowed_directory":
        target = allowed
        candidate = allowed / "donor.json"
    else:
        allowed.mkdir(parents=True)
        target = allowed / ("nested" if escape == "nested" else "donor.json")
        candidate = target / "donor.json" if escape == "nested" else target
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(
            outside / "donor.json" if escape == "file" else outside,
            target_is_directory=escape != "file",
        )
    except OSError:
        pytest.skip("platform does not permit symlink creation; Linux CI runs this gate")
    monkeypatch.chdir(checkout)
    monkeypatch.setenv("JANUARY_DONOR_HANDOFF_PATH", str(candidate))
    monkeypatch.setattr(diag, "read_donor_handoff", lambda *_: pytest.fail("must not consume file"))
    result = diag.diagnostic(tmp_path / diag.ARTIFACT_NAME, "a" * 40, evidence())
    receipt = json.loads((tmp_path / diag.RECEIPT_NAME).read_text())
    assert result["status"] == "BLOCKED" and not parameters
    assert receipt["failure"]["category"] == "MEMBERSHIP_DONOR_HANDOFF_PATH"


def real_donor_document():
    manifest = json.loads(
        Path("docs/contracts/semantic-release/governed-2026-09-15-manifest.json").read_text()
    )
    return {
        "contract_version": "atlas-january-reviewed-donor-v1",
        "producer_code_sha": "1" * 40,
        "produced_at": datetime.now(UTC).isoformat(),
        "operator_role": "OH_LYME_DEV_MIGRATION_DEPLOYER",
        "account_locator_sha256": hashlib.sha256(b"FIXTURE_ACCOUNT").hexdigest(),
        "region": "AWS_US_WEST_2",
        "release_id": manifest["release_id"],
        "bundle_sha256": "b" * 64,
        "annual_manifest": manifest,
    }


def test_real_preconnection_handoff_budget_settings_and_key_path(monkeypatch, tmp_path):
    """Use the production validators and shared key parser; stop at mocked connect."""
    import snowflake.connector

    checkout = tmp_path / "checkout"
    allowed = checkout / "docs/contracts/climate/reviewed-donors"
    allowed.mkdir(parents=True)
    path = allowed / "january-reviewed-donor.json"
    payload = json.dumps(real_donor_document(), sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.chdir(checkout)
    monkeypatch.setenv("JANUARY_DONOR_HANDOFF_PATH", str(path))
    monkeypatch.setenv("JANUARY_DONOR_HANDOFF_SHA256", digest)
    monkeypatch.setenv("JANUARY_DIAGNOSTIC_JOB_STARTED_UNIX", str(int(time.time())))
    monkeypatch.setattr(diag, "PRIOR_DIAGNOSTIC_FORECAST_USD", 15.050416666666667)
    budget = json.loads(evidence())
    budget["standard_capability_evidence"] = {
        "edition": "STANDARD",
        "cloud": "AWS",
        "account_locator_sha256": hashlib.sha256(b"FIXTURE_ACCOUNT").hexdigest(),
        "verified_by": "fixture-owner",
        "verified_at": datetime.now(UTC).isoformat(),
        "evidence_reference": "OWNER_SNOWSIGHT_ACCOUNT_DETAILS",
    }
    password = b"fixture-password"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password),
    )
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "FIXTURE_ACCOUNT")
    monkeypatch.setenv("SNOWFLAKE_USER", "OH_LYME_DEV_PIPELINE_SVC")
    monkeypatch.setenv("SNOWFLAKE_ROLE", "OH_LYME_DEV_RUNTIME")
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "ONE_HEALTH_LYME_GAP_ATLAS_DEV")
    monkeypatch.setenv("SNOWFLAKE_WAREHOUSE", "OH_LYME_DEV_INGEST_XS_WH")
    monkeypatch.setenv("SNOWFLAKE_AUTH_METHOD", "key_pair")
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_B64", base64.b64encode(pem).decode())
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE", password.decode())
    monkeypatch.setattr(diag.shutil, "disk_usage", lambda _: SimpleNamespace(free=1024**3))
    monkeypatch.setattr(diag.signal, "SIGALRM", 14, raising=False)
    monkeypatch.setattr(diag.signal, "ITIMER_REAL", 0, raising=False)
    monkeypatch.setattr(diag.signal, "signal", lambda *_: None)
    monkeypatch.setattr(diag.signal, "setitimer", lambda *_: None, raising=False)
    seen = []

    def stop_at_connect(**parameters):
        seen.append(parameters)
        raise RuntimeError("synthetic connection stop")

    monkeypatch.setattr(snowflake.connector, "connect", stop_at_connect)
    result = diag.diagnostic(tmp_path / diag.ARTIFACT_NAME, "a" * 40, json.dumps(budget))
    receipt = json.loads((tmp_path / diag.RECEIPT_NAME).read_text())
    assert result["status"] == "BLOCKED"
    assert receipt["reviewed_donor_handoff_sha256"] == digest
    assert receipt["donor_bundle_sha256"] == "b" * 64
    assert receipt["aggregate_forecast_ceiling_usd"] == pytest.approx(17.788333333333334)
    assert receipt["failure"]["initialization_substage"] == "CONNECT"
    assert receipt["failure"]["category"] == "READ_DEPENDENCY_UNAVAILABLE"
    assert seen[0]["user"] == "OH_LYME_DEV_PIPELINE_SVC"
    assert seen[0]["role"] == "OH_LYME_DEV_RUNTIME"
    assert seen[0]["authenticator"] == "SNOWFLAKE_JWT"
    assert seen[0]["client_fetch_threads"] == seen[0]["client_prefetch_threads"] == 1
    assert seen[0]["client_fetch_use_mp"] is False
    assert "synthetic connection stop" not in (tmp_path / diag.RECEIPT_NAME).read_text()


@pytest.mark.parametrize("control", ["valid", "digest", "oversize"])
def test_confined_real_donor_controls_before_exhausted_budget(
    setup, monkeypatch, tmp_path, control
):
    from lyme_gap_atlas_data.climate_membership import MAX_DONOR_BYTES, read_donor_handoff

    _, parameters, _ = setup
    document = real_donor_document()
    checkout = tmp_path / "checkout"
    allowed = checkout / "docs/contracts/climate/reviewed-donors"
    allowed.mkdir(parents=True)
    path = allowed / "donor.json"
    payload = (
        json.dumps(document).encode() if control != "oversize" else b"x" * (MAX_DONOR_BYTES + 1)
    )
    path.write_bytes(payload)
    monkeypatch.chdir(checkout)
    monkeypatch.setenv(
        "JANUARY_DONOR_HANDOFF_PATH", "docs/contracts/climate/reviewed-donors/donor.json"
    )
    digest = hashlib.sha256(payload).hexdigest() if control != "digest" else "0" * 64
    monkeypatch.setenv("JANUARY_DONOR_HANDOFF_SHA256", digest)
    monkeypatch.setattr(diag, "read_donor_handoff", read_donor_handoff)
    monkeypatch.setattr(diag, "PRIOR_DIAGNOSTIC_FORECAST_USD", 24)
    if control == "oversize":
        original_open = Path.open

        def open_path(candidate, *args, **kwargs):
            if candidate == path:
                pytest.fail("must not consume oversized file")
            return original_open(candidate, *args, **kwargs)

        monkeypatch.setattr(Path, "open", open_path)
    result = diag.diagnostic(tmp_path / diag.ARTIFACT_NAME, "a" * 40, evidence())
    receipt = json.loads((tmp_path / diag.RECEIPT_NAME).read_text())
    expected = {
        "valid": "FORECAST_EXCEEDS_APPROVED_TOTAL_CAP",
        "digest": "MEMBERSHIP_DONOR_DIGEST",
        "oversize": "MEMBERSHIP_DONOR_SIZE",
    }[control]
    assert result["status"] == "BLOCKED" and not parameters
    assert receipt["failure"]["category"] == expected


@pytest.mark.parametrize(
    "field,value", [("account_locator_sha256", "0" * 64), ("region", "AWS_US_EAST_1")]
)
def test_producer_consumer_binding_mismatch_blocks_before_warehouse_or_export(
    setup, monkeypatch, tmp_path, field, value
):
    cursor, _, _ = setup
    donor = {
        "bundle_sha256": "b" * 64,
        "account_locator_sha256": hashlib.sha256(b"FIXTURE_ACCOUNT").hexdigest(),
        "region": "AWS_US_WEST_2",
        field: value,
    }
    monkeypatch.setattr(diag, "read_donor_handoff", lambda *_: donor)
    result = diag.diagnostic(tmp_path / diag.ARTIFACT_NAME, "a" * 40, evidence())
    assert result["status"] == "BLOCKED"
    assert len(cursor.calls) == 1
