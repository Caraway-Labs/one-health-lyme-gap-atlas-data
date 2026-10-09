"""Proposed operator bounds exercised offline; no workflow or credentials."""

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from lyme_gap_atlas_data import climate_donor_diagnostic as donor
from lyme_gap_atlas_data import climate_membership_diagnostic as bounds


def evidence():
    return json.dumps(
        {
            "unit_price_usd": 6,
            "evidence_reference": "https://www.snowflake.com/en/pricing-options/",
            "verified_by": "fixture-owner",
            "verified_at": datetime.now(UTC).isoformat(),
            "region": "AWS_US_WEST_2",
            "standard_capability_evidence": {
                "edition": "STANDARD",
                "cloud": "AWS",
                "account_locator_sha256": hashlib.sha256(b"FIXTURE_ACCOUNT").hexdigest(),
                "verified_by": "fixture-owner",
                "verified_at": datetime.now(UTC).isoformat(),
                "evidence_reference": "OWNER_SNOWSIGHT_ACCOUNT_DETAILS",
            },
        }
    )


class Cursor:
    def __init__(self):
        self.identity = (*donor.EXPECTED_CONTEXT, "AWS_US_WEST_2", "FIXTURE_ACCOUNT")
        self.calls = []
        self.warehouse = {
            "name": donor.DONOR_WAREHOUSE,
            "size": "X-Small",
            "type": "STANDARD",
            "generation": "2",
            "max_cluster_count": 0,
            "auto_suspend": 60,
        }
        self.manifest = json.loads(
            Path("docs/contracts/semantic-release/governed-2026-09-15-manifest.json").read_text()
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, sql, params=(), timeout=None):
        self.calls.append((sql, timeout))

    def fetchone(self):
        return self.identity

    def fetchall(self):
        sql = self.calls[-1][0]
        if sql.startswith("SHOW"):
            return [tuple(self.warehouse.values())]
        if "r.source_manifest" in sql:
            return [(self.manifest["release_id"], "PUBLISHED", "b" * 64, self.manifest)]
        return [(self.manifest["release_id"], "b" * 64)]

    def get_result_batches(self):
        return []

    @property
    def description(self):
        return [(key,) for key in self.warehouse]


@pytest.fixture
def operator(monkeypatch):
    import lyme_gap_atlas_shared.settings
    import lyme_gap_atlas_shared.snowflake
    import snowflake.connector

    cursor = Cursor()
    calls, closes, timers, handlers = [], [], [], {}
    monkeypatch.setattr(bounds, "PRIOR_DIAGNOSTIC_FORECAST_USD", 4)
    monkeypatch.setattr(lyme_gap_atlas_shared.settings, "SnowflakeSettings", lambda: None)
    monkeypatch.setattr(
        lyme_gap_atlas_shared.snowflake,
        "connection_parameters",
        lambda _: {
            "user": donor.EXPECTED_CONTEXT[0],
            "role": donor.EXPECTED_CONTEXT[1],
            "database": donor.EXPECTED_CONTEXT[2],
            "warehouse": "must-be-overridden",
        },
    )
    connection = SimpleNamespace(cursor=lambda: cursor, close=lambda **kw: closes.append(kw))

    def connect(**kwargs):
        assert timers, "connection watchdog must already be active"
        calls.append(kwargs)
        return connection

    monkeypatch.setattr(snowflake.connector, "connect", connect)
    monkeypatch.setattr(donor.signal, "SIGALRM", 14, raising=False)
    monkeypatch.setattr(donor.signal, "ITIMER_REAL", 0, raising=False)
    monkeypatch.setattr(donor.signal, "setitimer", lambda *args: timers.append(args), raising=False)

    def handler(sig, function):
        old = handlers.get(sig, "original")
        handlers[sig] = function
        return old

    monkeypatch.setattr(donor.signal, "signal", handler)
    monkeypatch.setenv("JANUARY_DIAGNOSTIC_JOB_STARTED_UNIX", str(int(time.time())))
    return SimpleNamespace(
        cursor=cursor,
        calls=calls,
        closes=closes,
        timers=timers,
        handlers=handlers,
        connection=connection,
    )


def test_producer_exports_only_after_observed_bounds_and_closes_without_retry(operator, tmp_path):
    result = donor.producer(tmp_path / donor.ARTIFACT_NAME, "a" * 40, evidence())
    assert result["status"] == "READ_ONLY_DONOR_EXPORT_SUCCEEDED"
    assert result["statements"] == 5
    assert len(operator.calls) == 1 and operator.closes == [{"retry": False}]
    parameters = operator.calls[0]
    assert parameters["warehouse"] == donor.DONOR_WAREHOUSE
    assert parameters["login_timeout"] == parameters["network_timeout"] == 5
    assert parameters["session_parameters"]["STATEMENT_TIMEOUT_IN_SECONDS"] == 5
    assert parameters["session_parameters"]["ABORT_DETACHED_QUERY"] is True
    assert 0 < operator.timers[0][1] <= 15
    assert 0 < operator.timers[-2][1] <= 15
    assert operator.timers[-1][1] == 0
    assert all(timeout <= 5 for _, timeout in operator.cursor.calls)
    artifact = json.loads((tmp_path / donor.ARTIFACT_NAME).read_text())
    receipt = (tmp_path / donor.RECEIPT_NAME).read_text()
    parsed_receipt = json.loads(receipt)
    assert parsed_receipt["approved_total_forecast_usd"] == 25
    assert parsed_receipt["aggregate_forecast_ceiling_usd"] == pytest.approx(
        parsed_receipt["prior_diagnostic_full_forecast_reserved_usd"]
        + parsed_receipt["pair_forecast_reserved_usd"]
    )
    assert "FIXTURE_ACCOUNT" not in receipt
    assert "FIXTURE_ACCOUNT" not in (tmp_path / donor.ARTIFACT_NAME).read_text()
    assert artifact["account_locator_sha256"] == hashlib.sha256(b"FIXTURE_ACCOUNT").hexdigest()
    assert artifact["region"] == "AWS_US_WEST_2"


def test_approved_twenty_five_dollar_guard_blocks_excess_price_before_connection(
    operator, monkeypatch, tmp_path
):
    monkeypatch.setattr(bounds, "PRIOR_DIAGNOSTIC_FORECAST_USD", 20)
    value = json.loads(evidence())
    value["unit_price_usd"] = 20
    result = donor.producer(tmp_path / donor.ARTIFACT_NAME, "a" * 40, json.dumps(value))
    assert result["status"] == "BLOCKED" and not operator.calls
    receipt = json.loads((tmp_path / donor.RECEIPT_NAME).read_text())
    assert receipt["failure"]["category"] == "FORECAST_EXCEEDS_APPROVED_TOTAL_CAP"
    assert receipt["aggregate_forecast_ceiling_usd"] > 25
    assert not (tmp_path / donor.ARTIFACT_NAME).exists()


@pytest.mark.parametrize(
    "mutation",
    ["account", "region", "warehouse", "role", "suspend", "qas", "generation", "clusters"],
)
def test_wrong_binding_or_cost_context_never_reads_donor(operator, tmp_path, mutation):
    if mutation in {"account", "region", "warehouse", "role"}:
        identity = list(operator.cursor.identity)
        identity[{"account": 5, "region": 4, "warehouse": 3, "role": 1}[mutation]] = "wrong"
        operator.cursor.identity = tuple(identity)
    else:
        field, value = {
            "suspend": ("auto_suspend", 0),
            "qas": ("enable_query_acceleration", True),
            "generation": ("generation", "unknown"),
            "clusters": ("max_cluster_count", 2),
        }[mutation]
        operator.cursor.warehouse[field] = value
    result = donor.producer(tmp_path / donor.ARTIFACT_NAME, "a" * 40, evidence())
    assert result["status"] == "BLOCKED"
    assert not any("r.source_manifest" in sql for sql, _ in operator.cursor.calls)
    assert not (tmp_path / donor.ARTIFACT_NAME).exists()
    assert operator.closes == [{"retry": False}]


def test_connection_timeout_retains_receipt_without_second_connection(
    operator, monkeypatch, tmp_path
):
    import snowflake.connector

    attempts = []

    def connect(**kwargs):
        attempts.append(kwargs)
        operator.handlers[14](14, None)
        pytest.fail("watchdog should stop connection")

    monkeypatch.setattr(snowflake.connector, "connect", connect)
    result = donor.producer(tmp_path / donor.ARTIFACT_NAME, "a" * 40, evidence())
    assert result["status"] == "BLOCKED" and len(attempts) == 1
    assert result["statements"] == 0
    assert not operator.closes


def test_active_query_watchdog_requests_sdk_interrupt_then_bounded_cleanup(
    operator, monkeypatch, tmp_path
):
    interrupts = []

    def interrupt(sig):
        interrupts.append(sig)
        raise KeyboardInterrupt

    monkeypatch.setattr(donor.signal, "raise_signal", interrupt)

    def execute(sql, params=(), timeout=None):
        operator.cursor.calls.append((sql, timeout))
        operator.handlers[14](14, None)

    operator.cursor.execute = execute
    result = donor.producer(tmp_path / donor.ARTIFACT_NAME, "a" * 40, evidence())
    receipt = json.loads((tmp_path / donor.RECEIPT_NAME).read_text())
    assert result["status"] == "BLOCKED" and len(operator.calls) == 1
    assert interrupts == [donor.signal.SIGINT]
    assert receipt["cancellation_state"] == "SDK_INTERRUPT_REQUESTED_NOT_CONFIRMED"
    assert receipt["failure"]["category"] == "DONOR_RUNTIME_LIMIT"
    assert operator.closes == [{"retry": False}]


def test_cleanup_failure_preserves_existing_donor_and_removes_pending(operator, tmp_path):
    output = tmp_path / donor.ARTIFACT_NAME
    output.write_text("existing-reviewed-donor")

    def close(**_):
        operator.handlers[14](14, None)

    operator.connection.close = close
    result = donor.producer(output, "a" * 40, evidence())
    assert result["status"] == "BLOCKED"
    assert output.read_text() == "existing-reviewed-donor"
    assert not (tmp_path / ("pending-" + donor.ARTIFACT_NAME)).exists()


def test_statement_limit_and_no_retry_generator_are_enforced_before_extra_request():
    cursor = Cursor()
    bounded = bounds.BoundedCursor(
        cursor, time.monotonic(), {"statements": 6, "statement_limit": 6}
    )
    with pytest.raises(bounds.DiagnosticStop, match="STATEMENT_LIMIT"):
        bounded.execute("SELECT 1")
    assert not cursor.calls
    retries = bounds.no_retry_backoff()
    assert next(retries) == 0
    with pytest.raises(bounds.DiagnosticStop, match="AUTOMATIC_RETRY_PROHIBITED"):
        next(retries)


def test_failed_login_restores_retry_environment(operator, monkeypatch, tmp_path):
    import snowflake.connector

    monkeypatch.setenv("MAX_CON_RETRY_ATTEMPTS", "fixture-prior")

    def connect(**_):
        assert os.environ["MAX_CON_RETRY_ATTEMPTS"] == "0"
        raise RuntimeError("private driver details")

    monkeypatch.setattr(snowflake.connector, "connect", connect)
    result = donor.producer(tmp_path / donor.ARTIFACT_NAME, "a" * 40, evidence())
    assert result["status"] == "BLOCKED"
    assert os.environ["MAX_CON_RETRY_ATTEMPTS"] == "fixture-prior"
    assert "private driver details" not in (tmp_path / donor.RECEIPT_NAME).read_text()


def test_pinned_sdk_interrupt_cancels_active_request_without_cancellation_sql():
    from unittest.mock import MagicMock

    from snowflake.connector.cursor import SnowflakeCursor

    connection = MagicMock()
    connection.log_max_query_length = 1000
    connection.network_timeout = 5
    connection._next_sequence_counter.return_value = 1
    connection.is_closed.return_value = False
    cursor = SnowflakeCursor(connection)

    def query(*_, **__):
        # Invoke the actual SDK-installed handler, without sending an OS signal.
        handler = donor.signal.getsignal(donor.signal.SIGINT)
        handler(donor.signal.SIGINT, None)
        pytest.fail("SDK interrupt must stop the query")

    connection.cmd_query.side_effect = query
    with pytest.raises(KeyboardInterrupt):
        cursor._execute_helper("SELECT 1", timeout=5)
    connection._cancel_query.assert_called_once_with("SELECT 1", cursor._request_id)
    assert connection.cmd_query.call_count == 1
