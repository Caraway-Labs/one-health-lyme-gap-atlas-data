"""Failing-first coverage for daily-job logs, spans, and redaction."""

from __future__ import annotations

import ast
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from lyme_gap_atlas_data import intelligence_daily_telemetry as telemetry
from lyme_gap_atlas_data.ingestion.intelligence_runtime import PilotBudget, _Cursor
from lyme_gap_atlas_data.sql_sessions import connect

ROOT = Path(__file__).resolve().parents[1]
DAILY_SQL_MODULES = (
    "src/lyme_gap_atlas_data/ingestion/checkpoints.py",
    "src/lyme_gap_atlas_data/ingestion/intelligence_checkpoints.py",
    "src/lyme_gap_atlas_data/ingestion/intelligence_entrez.py",
    "src/lyme_gap_atlas_data/ingestion/intelligence_runtime.py",
    "src/lyme_gap_atlas_data/intelligence_bulk_write.py",
    "src/lyme_gap_atlas_data/intelligence_daily_deadline.py",
    "src/lyme_gap_atlas_data/intelligence_daily_hard_kill.py",
    "src/lyme_gap_atlas_data/intelligence_daily_run_recovery.py",
    "src/lyme_gap_atlas_data/intelligence_raw_runtime.py",
    "src/lyme_gap_atlas_data/intelligence_storage.py",
    "src/lyme_gap_atlas_data/sql_sessions.py",
)
SECRET_MARKER = "ncbi-secret@example.invalid"
TOKEN_MARKER = "DUMMY_OPAQUE_HEADER_SENTINEL"
SQL_PARAM = "bound-patient-payload-token"


class _LockError(Exception):
    def __init__(self) -> None:
        super().__init__(
            f"password={TOKEN_MARKER} email={SECRET_MARKER} snowflake://user:pass@host"
        )
        self.errno = 625
        self.sqlstate = "57014"


class _BlockingCursor:
    def __init__(self) -> None:
        self.rowcount = 1

    def execute(self, statement: str, *args: object, **kwargs: object) -> None:
        del statement, kwargs
        assert args == (SQL_PARAM,)
        time.sleep(0.02)
        raise _LockError()


def setup_function() -> None:
    telemetry.reset_captured_events()


def teardown_function() -> None:
    telemetry.reset_captured_events()


def test_statement_emitter_records_lock_wait_without_parameters() -> None:
    with telemetry.observed(), pytest.raises(_LockError):
        telemetry.instrumented_execute(
            _BlockingCursor(),
            "UPDATE GOVERNANCE.INTELLIGENCE_WRITE_GUARD "
            "SET write_sequence=write_sequence+1 WHERE guard_id=1",
            (SQL_PARAM,),
            {},
        )
    event = telemetry.captured_events()[0]
    assert event["event"] == "snowflake.statement"
    assert event["statement_label"] == "ledger.guard.update"
    assert event["step"] == "ledger.guard.update"
    assert event["exception_class"] == "_LockError"
    assert event["errno"] == 625
    assert event["sqlstate"] == "57014"
    assert event["row_count"] == 1
    assert event["lock_wait_ms"] >= 0
    assert event["duration_ms"] >= 0
    dumped = json.dumps(telemetry.captured_events())
    assert SQL_PARAM not in dumped
    assert SECRET_MARKER not in dumped
    assert TOKEN_MARKER not in dumped
    assert "snowflake://" not in dumped
    assert "password=" not in dumped


def test_http_emitter_drops_query_email_and_credentials() -> None:
    url = (
        "https://user:pass@eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?email={SECRET_MARKER}&api_key={TOKEN_MARKER}"
    )
    with telemetry.observed(), telemetry.http_observation(url) as observed:
        observed["status"] = 200
        observed["bytes"] = 12
        observed["retries"] = 1
    event = next(item for item in telemetry.captured_events() if item["event"] == "http.client")
    assert event["host"] == "eutils.ncbi.nlm.nih.gov"
    assert event["path"] == "/entrez/eutils/esearch.fcgi"
    assert event["http_status"] == 200
    assert event["bytes"] == 12
    assert event["retry_count"] == 1
    dumped = json.dumps(event)
    assert SECRET_MARKER not in dumped
    assert TOKEN_MARKER not in dumped
    assert "user:pass" not in dumped
    assert "api_key" not in dumped


def test_checkpoint_ledger_lease_guard_and_summary_emitters() -> None:
    with telemetry.observed():
        telemetry.bind_context(
            source_id="cdc-mmwr",
            run_id="76e241c4-815f-5c27-b97f-882be9c53903",
            attempt=2,
        )
        telemetry.record_checkpoint("read")
        telemetry.record_checkpoint("write")
        telemetry.record_ledger("read", "lease")
        telemetry.record_lease("acquire")
        telemetry.record_lease("renew")
        telemetry.record_lease("release")
        with telemetry.guard_scope(nested=True):
            telemetry.warn_open_transaction()
        telemetry.emit_source_summary(
            status="FAILED",
            seconds=1.5,
            items=3,
            nbytes=20,
            failure_code="PUBMED_DAILY_FAILED",
        )
        telemetry.emit_run_summary(status="FAILED", seconds=2, sources=5, failed=1)
    events = [item["event"] for item in telemetry.captured_events()]
    assert "checkpoint.read" in events
    assert "checkpoint.write" in events
    assert "ledger.read" in events
    assert "lease.acquire" in events
    assert "lease.renew" in events
    assert "lease.release" in events
    assert "guard.enter" in events
    assert "guard.exit" in events
    assert "guard.transaction_open" in events
    assert "source.summary" in events
    assert "run.summary" in events
    summary = next(
        item for item in telemetry.captured_events() if item["event"] == "source.summary"
    )
    assert summary["service_name"] == "data-job"
    assert summary["component"] == "intelligence-daily"
    assert summary["source_id"] == "cdc-mmwr"
    assert summary["attempt"] == 2
    assert summary["failure_code"] == "PUBMED_DAILY_FAILED"
    assert summary["peak_rss_kb"] >= 0
    guard = next(item for item in telemetry.captured_events() if item["event"] == "guard.enter")
    assert guard["guard_depth"] == 1
    warning = next(
        item for item in telemetry.captured_events() if item["event"] == "guard.transaction_open"
    )
    assert warning["level"] == "WARNING"


def test_heartbeat_polls_only_while_a_stage_is_open() -> None:
    clock = [0.0]
    heartbeat = telemetry.StageHeartbeat(interval=30, clock=lambda: clock[0])
    with telemetry.observed():
        heartbeat.set_open("LOAD")
        heartbeat.poll()
        assert not any(item["event"] == "stage.heartbeat" for item in telemetry.captured_events())
        clock[0] = 30
        heartbeat.poll()
        clock[0] = 60
        heartbeat.set_open(None)
        heartbeat.poll()
    beats = [item for item in telemetry.captured_events() if item["event"] == "stage.heartbeat"]
    assert len(beats) == 1
    assert beats[0]["stage"] == "LOAD"


def test_stage_span_opens_and_closes() -> None:
    with telemetry.observed(), telemetry.stage_scope("ACQUIRE"):
        pass
    events = [item["event"] for item in telemetry.captured_events()]
    assert events == ["stage.open", "stage.close"]


def test_telemetry_failure_does_not_fail_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(TOKEN_MARKER)

    monkeypatch.setattr(telemetry, "_remember", explode)
    monkeypatch.setattr(telemetry, "_write_stdout", explode)
    monkeypatch.setattr(telemetry, "_enqueue_export", explode)

    class Cursor:
        rowcount = 0

        def execute(self, *_args: object, **_kwargs: object) -> str:
            return "ok"

    with telemetry.observed():
        assert telemetry.instrumented_execute(Cursor(), "SELECT 1", (), {}) == "ok"


def test_missing_otlp_env_does_not_configure_export(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", raising=False)
    monkeypatch.setattr(telemetry, "_LOG_EMITTER", None)
    telemetry.configure_daily_log_export()
    assert telemetry._LOG_EMITTER is None


def test_logs_endpoint_reuses_the_traces_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otel.example.invalid/v1/traces")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", raising=False)
    assert telemetry._logs_endpoint() == "https://otel.example.invalid/v1/logs"


def test_sql_literals_are_not_statement_labels() -> None:
    label = telemetry.statement_label(
        f"SELECT '{SECRET_MARKER}' FROM GOVERNANCE.INGESTION_RUNS WHERE id='{TOKEN_MARKER}'"
    )
    assert label == "run.read"
    shape = telemetry.scrub_sql(f"SELECT '{SECRET_MARKER}'")
    assert SECRET_MARKER not in shape
    assert TOKEN_MARKER not in telemetry.scrub_sql(f"UPDATE t SET a='{TOKEN_MARKER}'")


def test_cursor_wrapper_and_connection_record_statements(monkeypatch: pytest.MonkeyPatch) -> None:
    class Raw:
        rowcount = 2

        def __enter__(self) -> Raw:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, statement: str, *args: object, **kwargs: object) -> str:
            del statement, args, kwargs
            return "ran"

    budget = PilotBudget(seconds=30)
    wrapped = _Cursor(Raw(), budget)
    with telemetry.observed():
        assert wrapped.execute("SELECT CURRENT_ROLE()", SQL_PARAM) == "ran"
    event = telemetry.captured_events()[0]
    assert event["statement_label"] == "session.identity"
    assert SQL_PARAM not in json.dumps(event)

    class FakeConnection:
        def __enter__(self) -> FakeConnection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def cursor(self) -> Raw:
            return Raw()

    monkeypatch.setattr(
        "lyme_gap_atlas_data.sql_sessions.shared_connect", lambda *_a, **_k: FakeConnection()
    )
    telemetry.reset_captured_events()
    with telemetry.observed():
        connection = connect(SimpleNamespace())
        assert isinstance(connection, telemetry.ObservedConnection)
        with connection.cursor() as cursor:
            cursor.execute(
                "MERGE INTO GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES t USING s ON t.id=s.id",
                {"email": SECRET_MARKER},
            )
    merged = telemetry.captured_events()[0]
    assert merged["statement_label"] == "capture.merge"
    assert SECRET_MARKER not in json.dumps(merged)
    assert "lock_wait_ms" in merged


def test_every_daily_snowflake_module_uses_the_instrumented_wrapper() -> None:
    runtime = (ROOT / "src/lyme_gap_atlas_data/ingestion/intelligence_runtime.py").read_text()
    sessions = (ROOT / "src/lyme_gap_atlas_data/sql_sessions.py").read_text()
    assert "instrumented_execute" in runtime
    assert "ObservedConnection" in sessions
    for relative in (
        "src/lyme_gap_atlas_data/intelligence_daily_deadline.py",
        "src/lyme_gap_atlas_data/intelligence_daily_hard_kill.py",
        "src/lyme_gap_atlas_data/intelligence_daily_run_recovery.py",
    ):
        assert "observed()" in (ROOT / relative).read_text()
    execute_sites = 0
    for relative in DAILY_SQL_MODULES:
        source = (ROOT / relative).read_text()
        assert "snowflake.connector.connect" not in source or relative.endswith("sql_sessions.py")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "execute":
                execute_sites += 1
                if isinstance(func.value, ast.Name):
                    assert func.value.id != "connector"
    assert execute_sites >= 40
