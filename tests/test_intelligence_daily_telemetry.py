"""Failing-first coverage for daily-job logs, spans, and redaction."""

from __future__ import annotations

import ast
import json
import queue
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lyme_gap_atlas_data import intelligence_daily_telemetry as telemetry
from lyme_gap_atlas_data import intelligence_polling as polling
from lyme_gap_atlas_data.ingestion.intelligence_runtime import PilotBudget, _Cursor
from lyme_gap_atlas_data.intelligence_raw_runtime import SnowflakeRawLedger
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
DAILY_THREAD_MODULES = DAILY_SQL_MODULES + (
    "src/lyme_gap_atlas_data/intelligence_polling.py",
    "src/lyme_gap_atlas_data/intelligence_daily_telemetry.py",
    "src/lyme_gap_atlas_data/ingestion/intelligence_feed.py",
    "src/lyme_gap_atlas_data/literature_tracing.py",
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
    assert event["guarded_statement_ms"] >= 0
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
        with telemetry.record_checkpoint("read"):
            time.sleep(0.01)
        with telemetry.record_checkpoint("write"):
            pass
        with telemetry.record_ledger("read", "lease"):
            pass
        with telemetry.record_lease("acquire"):
            pass
        with telemetry.record_lease("get"):
            pass
        with telemetry.record_lease("renew"):
            pass
        with telemetry.record_lease("release"):
            pass
        with telemetry.guard_scope(nested=True):
            telemetry.warn_open_transaction()
        with telemetry.guard_scope(nested=False):
            pass
        telemetry.emit_source_summary(
            status="FAILED",
            seconds=1.5,
            items=3,
            nbytes=20,
            failure_code="PUBMED_DAILY_FAILED",
        )
        telemetry.emit_run_summary(
            status="FAILED",
            seconds=2,
            sources=5,
            failed=3,
            failure_class="RuntimeError",
        )
    events = [item["event"] for item in telemetry.captured_events()]
    assert "checkpoint.read" in events
    assert "checkpoint.write" in events
    assert "ledger.read" in events
    assert "lease.acquire" in events
    assert "lease.get" in events
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
    assert guard["nested"] is True
    assert "transaction_open" not in guard
    warning = next(
        item for item in telemetry.captured_events() if item["event"] == "guard.transaction_open"
    )
    assert warning["level"] == "WARNING"
    assert warning["transaction_open"] is True
    outer = [
        item
        for item in telemetry.captured_events()
        if item["event"] == "guard.enter" and item["guard_depth"] == 1 and item["nested"] is False
    ]
    assert outer
    assert "transaction_open" not in outer[0]
    read = next(item for item in telemetry.captured_events() if item["event"] == "checkpoint.read")
    assert read["duration_ms"] >= 0
    summary = next(item for item in telemetry.captured_events() if item["event"] == "run.summary")
    assert summary["failed"] == 3
    assert summary["exception_class"] == "RuntimeError"
    assert summary["failure_code"] == "RUN_FAILED"


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
    for item in telemetry.captured_events():
        assert item["rss_kib"] >= 0
        assert item["peak_rss_kib"] >= 0


def test_stage_and_source_rss_lines_do_not_leak_feed_content() -> None:
    marker = "https://tools.cdc.gov/api/secret-item"
    title = "MMWR secret title body"
    with (
        telemetry.observed(),
        telemetry.source_span("cdc-mmwr"),
        telemetry.stage_scope("NORMALIZE"),
    ):
        telemetry.emit(
            "stage.note",
            description=title,
            url=marker,
            body=title,
        )
    blob = json.dumps(telemetry.captured_events())
    assert marker not in blob
    assert title not in blob
    assert "http" not in blob
    names = [item["event"] for item in telemetry.captured_events()]
    assert names[:2] == ["source.open", "stage.open"]
    assert "source.close" in names
    assert "stage.close" in names
    for item in telemetry.captured_events():
        if item["event"] in {"source.open", "source.close", "stage.open", "stage.close"}:
            assert item["rss_kib"] >= 0
            assert item["peak_rss_kib"] >= 0


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
    assert "guarded_statement_ms" in merged


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


def test_scrub_sql_drops_escapes_dollar_quotes_and_query_tags() -> None:
    secret = "ncbi-secret-value"
    samples = (
        f"SELECT '{secret}'",
        "SELECT 'it\\'" + secret + "'",
        "SELECT 'it''" + secret + "'",
        'SELECT "say \\"' + secret + '\\""',
        f"SELECT $${secret}$$",
        f"SELECT $tag${secret}$tag$",
        f"ALTER SESSION SET QUERY_TAG='{secret}'",
        f"ALTER SESSION SET QUERY_TAG={secret},LOCK_TIMEOUT=5",
        f"ALTER SESSION SET QUERY_TAG=$${secret}$$",
        f'ALTER SESSION SET QUERY_TAG="{secret}"',
        f"ALTER SESSION SET query_tag='{secret}'",
    )
    for sample in samples:
        scrubbed = telemetry.scrub_sql(sample)
        assert secret not in scrubbed
        assert "QUERY_TAG" not in scrubbed.upper() or "?" in scrubbed
    tagged = telemetry.scrub_sql(f"ALTER SESSION SET QUERY_TAG={secret},LOCK_TIMEOUT=5")
    assert "LOCK_TIMEOUT" in tagged
    assert secret not in tagged


def test_heartbeat_thread_emits_stage_heartbeat() -> None:
    heartbeat = telemetry.StageHeartbeat(interval=0.05)
    try:
        with telemetry.observed():
            heartbeat.set_open("LOAD")
            heartbeat.start()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if any(item["event"] == "stage.heartbeat" for item in telemetry.captured_events()):
                    break
                time.sleep(0.02)
    finally:
        heartbeat.stop()
    beats = [item for item in telemetry.captured_events() if item["event"] == "stage.heartbeat"]
    assert beats
    assert beats[0]["stage"] == "LOAD"
    assert beats[0]["step"] == "heartbeat"


class _Alive:
    def is_alive(self) -> bool:
        return True


def test_parent_heartbeat_thread_emits_stage_heartbeat() -> None:
    stage_queue: queue.Queue[str] = queue.Queue()
    stage_queue.put("FETCH")
    stop = threading.Event()
    thread = None
    try:
        with telemetry.observed():
            thread = polling.start_parent_stage_heartbeat(
                _Alive(),
                stage_queue,
                "cdc-mmwr",
                stop,
                name="test-parent-heartbeat",
                interval=0.05,
            )
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if any(item["event"] == "stage.heartbeat" for item in telemetry.captured_events()):
                    break
                time.sleep(0.02)
    finally:
        stop.set()
        if thread is not None:
            thread.join(1)
    beats = [item for item in telemetry.captured_events() if item["event"] == "stage.heartbeat"]
    assert beats
    assert beats[0]["stage"] == "FETCH"
    assert beats[0]["source_id"] == "cdc-mmwr"
    assert beats[0]["rss_kib"] >= 0
    assert beats[0]["peak_rss_kib"] >= beats[0]["rss_kib"]


def test_pubmed_failure_checkpoint_save_is_instrumented() -> None:
    class Cursor:
        rowcount = 1

        def execute(self, statement: str, *args: object, **kwargs: object) -> None:
            del statement, args, kwargs

    class Checkpoints:
        def save(self, state: object) -> None:
            del state
            telemetry.instrumented_execute(
                Cursor(),
                "MERGE INTO GOVERNANCE.INGESTION_RUN_CHECKPOINTS target "
                "USING source ON target.checkpoint_id = source.checkpoint_id",
                (),
                {},
            )

    with telemetry.observed():
        polling._wait_bounded(
            polling._save_claimed_pubmed_failures,
            Checkpoints(),
            [("76e241c4-815f-5c27-b97f-882be9c53903", "pubmed-tick-borne")],
            "PUBMED_DAILY_FAILED",
            {},
            seconds=2,
        )
    events = [
        item for item in telemetry.captured_events() if item["event"] == "snowflake.statement"
    ]
    assert events
    assert events[0]["statement_label"] == "checkpoint.write"


def test_snowflake_lease_read_is_labeled_get() -> None:
    ledger = SnowflakeRawLedger.__new__(SnowflakeRawLedger)
    ledger.local = threading.local()

    class Cursor:
        def execute(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def fetchall(self) -> list[object]:
            return []

    @contextmanager
    def guard() -> Any:
        ledger.local.cursor = Cursor()
        yield

    ledger.guard = guard  # type: ignore[method-assign]
    with telemetry.observed():
        assert ledger.get("lease", "abc") is None
    events = [item["event"] for item in telemetry.captured_events()]
    assert "lease.get" in events
    assert "lease.renew" not in events
    read = next(item for item in telemetry.captured_events() if item["event"] == "ledger.read")
    assert read["duration_ms"] >= 0


def test_run_summary_counts_failed_sources_and_survives_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def execute(source_id: str, path: str, **kwargs: object) -> dict[str, str]:
        del path, kwargs
        outcome = "FAILED" if source_id in {"cdc-mmwr", "cdc-outbreaks"} else "SUCCEEDED"
        return {"source_id": source_id, "outcome": outcome}

    monkeypatch.setattr(polling, "execute_daily_source", execute)
    monkeypatch.setattr(
        polling,
        "_isolate_pubmed_walk",
        lambda *args, **kwargs: (
            {"source_id": "pubmed-tick-borne", "status": "FAILED"},
            {"source_id": "pubmed-lyme-borrelia", "status": "SUCCEEDED"},
        ),
    )
    with telemetry.observed():
        payload = polling._run_production_daily_observed(
            object(),
            preflight_only=False,
            reopen_attempt=1,
            selection=None,
            pubmed_only=None,
            started=time.monotonic(),
        )
    assert payload["status"] == "FAILED"
    summary = next(item for item in telemetry.captured_events() if item["event"] == "run.summary")
    assert summary["failed"] == 3
    assert summary["status"] == "FAILED"
    assert "exception_class" not in summary

    def explode(source_id: str, path: str, **kwargs: object) -> None:
        del source_id, path, kwargs
        raise RuntimeError("source-boom")

    monkeypatch.setattr(polling, "execute_daily_source", explode)
    telemetry.reset_captured_events()
    with telemetry.observed(), pytest.raises(RuntimeError, match="source-boom"):
        polling._run_production_daily_observed(
            object(),
            preflight_only=False,
            reopen_attempt=1,
            selection=None,
            pubmed_only=None,
            started=time.monotonic(),
        )
    failed = next(item for item in telemetry.captured_events() if item["event"] == "run.summary")
    assert failed["status"] == "FAILED"
    assert failed["failed"] == 0
    assert failed["exception_class"] == "RuntimeError"


def _thread_ctor(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        name = func.attr
    elif isinstance(func, ast.Name):
        name = func.id
    else:
        return None
    if name in {"Thread", "Timer", "ThreadPoolExecutor"}:
        return name
    return None


def _callback(node: ast.Call, ctor: str) -> ast.expr | None:
    if ctor == "Timer":
        return node.args[1] if len(node.args) > 1 else None
    named = next((keyword.value for keyword in node.keywords if keyword.arg == "target"), None)
    if named is not None:
        return named
    return node.args[0] if node.args else None


def _is_context_run(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "run"


def _is_process_exit(node: ast.expr | None) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "_exit"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _thread_call_is_allowed(node: ast.Call, ctor: str, function_name: str | None) -> bool:
    if function_name in {"spawn_observed", "spawn_observed_timer"}:
        return True
    callback = _callback(node, ctor)
    if _is_context_run(callback):
        return True
    # Process exit does not read observation state. The callback stays os._exit.
    return ctor == "Timer" and _is_process_exit(callback)


def _visit_threads(
    node: ast.AST,
    *,
    function_name: str | None,
    relative: str,
    offenders: list[str],
) -> None:
    current = function_name
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        current = node.name
    if isinstance(node, ast.Call):
        ctor = _thread_ctor(node)
        if ctor is not None and not _thread_call_is_allowed(node, ctor, current):
            offenders.append(f"{relative}:{node.lineno}:{ctor}")
    for child in ast.iter_child_nodes(node):
        _visit_threads(child, function_name=current, relative=relative, offenders=offenders)


def _copies_context(function: ast.FunctionDef) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if isinstance(called, ast.Name) and called.id == "copy_context":
            return True
        if isinstance(called, ast.Attribute) and called.attr == "copy_context":
            return True
    return False


def test_daily_threads_inherit_observation_context() -> None:
    offenders: list[str] = []
    helpers: dict[str, ast.FunctionDef] = {}
    for relative in DAILY_THREAD_MODULES:
        tree = ast.parse((ROOT / relative).read_text())
        _visit_threads(tree, function_name=None, relative=relative, offenders=offenders)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in {
                "spawn_observed",
                "spawn_observed_timer",
            }:
                helpers[node.name] = node
    assert offenders == []
    assert _copies_context(helpers["spawn_observed"])
    assert _copies_context(helpers["spawn_observed_timer"])
