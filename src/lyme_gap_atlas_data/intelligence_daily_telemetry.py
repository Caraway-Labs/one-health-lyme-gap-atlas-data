"""Fail-open traces and structured logs for the intelligence daily job.

Telemetry never raises into the job. Export uses the existing OTLP endpoint and
headers when they are present. Without them the job still logs JSON lines and
continues. Statement parameters, row bodies, payloads, and credentials are not
recorded.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import resource
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from contextvars import ContextVar, Token, copy_context
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from lyme_gap_atlas_shared.observability import parse_otlp_headers
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import Status, StatusCode

from .literature_tracing import configure_literature_tracing

SERVICE_NAME = "data-job"
COMPONENT = "intelligence-daily"
HEARTBEAT_SECONDS = 30
DAILY_TRACE_COMMANDS = frozenset(
    {
        "pipeline.run-intelligence-daily",
        "pipeline.recover-intelligence-daily-stuck-run",
    }
)
_LOCK_LABELS = frozenset(
    {
        "ledger.guard.update",
        "ledger.read",
        "ledger.write",
        "ledger.call",
        "capture.merge",
    }
)
_LOGGER = logging.getLogger("atlas.intelligence.daily")
_EVENTS: list[dict[str, Any]] = []
_EVENTS_LOCK = threading.Lock()
_MAX_EVENTS = 500
_EXPORT_QUEUE: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=256)
_EXPORT_THREAD: threading.Thread | None = None
_LOG_PROVIDER: LoggerProvider | None = None
_LOG_EMITTER: Any = None
_STDOUT_READY = False
_ACTIVE: ContextVar[bool] = ContextVar("atlas_daily_observation", default=False)
_PARENT_HEARTBEAT: ContextVar[bool] = ContextVar("atlas_daily_parent_heartbeat", default=False)
_STAGE_QUEUE: ContextVar[Any] = ContextVar("atlas_daily_stage_queue", default=None)
_HEARTBEAT: ContextVar[StageHeartbeat | None] = ContextVar("atlas_daily_heartbeat", default=None)
_GUARD_DEPTH: ContextVar[int] = ContextVar("atlas_daily_guard_depth", default=0)
_LOCK_TIMEOUT: ContextVar[int | None] = ContextVar("atlas_daily_lock_timeout", default=None)
_STATEMENT_TIMEOUT: ContextVar[int | None] = ContextVar(
    "atlas_daily_statement_timeout", default=None
)
_BYTES: ContextVar[int] = ContextVar("atlas_daily_bytes", default=0)
_SOURCE_ID: ContextVar[str | None] = ContextVar("atlas_daily_source_id", default=None)
_RUN_ID: ContextVar[str | None] = ContextVar("atlas_daily_run_id", default=None)
_ATTEMPT: ContextVar[int | None] = ContextVar("atlas_daily_attempt", default=None)
_STAGE: ContextVar[str | None] = ContextVar("atlas_daily_stage", default=None)
_STEP: ContextVar[str | None] = ContextVar("atlas_daily_step", default=None)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_SOURCE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){0,8}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
_PATH = re.compile(r"^/[A-Za-z0-9._~/-]{0,200}$")
_EXCEPTION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,80}$")
_SQLSTATE = re.compile(r"^[0-9A-Z]{5}$")
_FAILURE = re.compile(r"^[A-Z0-9_]{1,80}$")
_FORBIDDEN = re.compile(
    r"(?i)(token|secret|password|private_key|authorization|snowflake://|"
    r"://[^/\s]*@|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})"
)
_STRING_LITERAL = re.compile(r"'(?:\\.|''|[^'])*'|" r'"(?:\\.|""|[^"])*"')
_DOLLAR_QUOTE = re.compile(r"\$([A-Za-z0-9_]*)\$[\s\S]*?\$\1\$")
_QUERY_TAG = re.compile(
    r"(?i)(QUERY_TAG\s*=\s*)(?:"
    r"\$([A-Za-z0-9_]*)\$[\s\S]*?\$\2\$|"
    r"'(?:\\.|''|[^'])*'|"
    r'"(?:\\.|""|[^"])*"|'
    r"[^\s,;]+)"
)
_NUMBER = re.compile(r"\b\d+\b")
_LOCK_TIMEOUT_SQL = re.compile(r"LOCK_TIMEOUT\s*=\s*(\d+)", re.IGNORECASE)
_STATEMENT_TIMEOUT_SQL = re.compile(r"STATEMENT_TIMEOUT_IN_SECONDS\s*=\s*(\d+)", re.IGNORECASE)


def observation_active() -> bool:
    return _ACTIVE.get()


def activate_observation() -> Token[bool]:
    return _ACTIVE.set(True)


def reset_observation(token: Token[bool]) -> None:
    _ACTIVE.reset(token)


@contextmanager
def observed() -> Iterator[None]:
    token = activate_observation()
    try:
        yield
    finally:
        reset_observation(token)


def bind_context(
    *,
    source_id: str | None = None,
    run_id: str | None = None,
    attempt: int | None = None,
    stage: str | None = None,
    step: str | None = None,
) -> None:
    if source_id is not None:
        _SOURCE_ID.set(source_id if _SOURCE.fullmatch(source_id) else None)
    if run_id is not None:
        _RUN_ID.set(run_id if _UUID.fullmatch(run_id) else None)
    if attempt is not None:
        _ATTEMPT.set(attempt if type(attempt) is int and 1 <= attempt <= 31 else None)
    if stage is not None:
        _STAGE.set(stage if _IDENTIFIER.fullmatch(stage) else None)
    if step is not None:
        _STEP.set(step if _IDENTIFIER.fullmatch(step) else None)


def bind_stage_queue(stage_queue: Any) -> None:
    if stage_queue is None:
        return
    _STAGE_QUEUE.set(stage_queue)
    _PARENT_HEARTBEAT.set(True)


def parent_heartbeat_active() -> bool:
    return _PARENT_HEARTBEAT.get()


def spawn_observed(
    target: Callable[..., Any],
    args: tuple[Any, ...] = (),
    *,
    name: str,
    daemon: bool = True,
) -> threading.Thread:
    """Start a thread whose body runs under a copy of the caller's context."""
    copied = copy_context()
    thread = threading.Thread(
        target=copied.run,
        args=(target, *args),
        name=name,
        daemon=daemon,
    )
    thread.start()
    return thread


def spawn_observed_timer(
    interval: float,
    target: Callable[..., Any],
    args: tuple[Any, ...] = (),
) -> threading.Timer:
    """Start a daemon timer whose callback runs under a copy of the caller's context."""
    copied = copy_context()

    def invoke() -> None:
        copied.run(target, *args)

    timer = threading.Timer(interval, invoke)
    timer.daemon = True
    timer.start()
    return timer


def captured_events() -> tuple[dict[str, Any], ...]:
    with _EVENTS_LOCK:
        return tuple(_EVENTS)


def reset_captured_events() -> None:
    with _EVENTS_LOCK:
        _EVENTS.clear()


def transferred_bytes() -> int:
    return _BYTES.get()


def scrub_sql(statement: str) -> str:
    """Drop literals, dollar quotes, query tags, and numbers from a statement shape."""
    without_tags = _QUERY_TAG.sub(r"\1?", statement)
    without_dollars = _DOLLAR_QUOTE.sub("?", without_tags)
    without_strings = _STRING_LITERAL.sub("?", without_dollars)
    without_numbers = _NUMBER.sub("?", without_strings)
    return re.sub(r"\s+", " ", without_numbers).strip()


def statement_label(statement: str) -> str:
    """Fixed label for a call site, derived from the scrubbed statement shape."""
    shape = scrub_sql(statement).upper()
    if "INTELLIGENCE_WRITE_GUARD" in shape and shape.startswith("UPDATE"):
        return "ledger.guard.update"
    if "INTELLIGENCE_RAW_RETENTION" in shape or "PURGE_INTELLIGENCE_RAW" in shape:
        if shape.startswith(("INSERT", "UPDATE", "MERGE", "DELETE", "CALL")):
            return "ledger.write" if not shape.startswith("CALL") else "ledger.call"
        return "ledger.read"
    if "INGESTION_RUN_CHECKPOINTS" in shape:
        if shape.startswith(("INSERT", "UPDATE", "MERGE", "DELETE")):
            return "checkpoint.write"
        return "checkpoint.read"
    if "INGESTION_RUNS" in shape:
        if shape.startswith(("INSERT", "UPDATE", "MERGE", "DELETE")):
            return "run.write"
        return "run.read"
    if any(
        token in shape
        for token in (
            "INTELLIGENCE_ITEM",
            "ITEM_CAPTURE",
            "ACQUISITION_CONTEXT",
            "RAW_ARTIFACTS",
            "INGESTION_REQUESTS",
        )
    ):
        if shape.startswith(("INSERT", "MERGE", "UPDATE", "DELETE")):
            return "capture.merge"
        return "capture.read"
    if shape.startswith("ALTER SESSION"):
        return "session.alter"
    if shape.startswith("BEGIN"):
        return "transaction.begin"
    if shape.startswith("SELECT CURRENT_"):
        return "session.identity"
    if shape.startswith("CALL "):
        return "ledger.call"
    for prefix, label in (
        ("SELECT", "sql.select"),
        ("INSERT", "sql.insert"),
        ("UPDATE", "sql.update"),
        ("MERGE", "sql.merge"),
        ("DELETE", "sql.delete"),
    ):
        if shape.startswith(prefix):
            return label
    return "sql.statement"


class ObservedCursor:
    """Cursor proxy that records every statement without exposing parameters."""

    daily_observed = True

    def __init__(self, cursor: Any) -> None:
        self.raw = cursor

    def __getattr__(self, name: str) -> Any:
        return getattr(self.raw, name)

    def __enter__(self) -> ObservedCursor:
        self.raw.__enter__()
        return self

    def __exit__(self, *args: Any) -> Any:
        return self.raw.__exit__(*args)

    def execute(self, statement: str, *args: Any, **kwargs: Any) -> Any:
        return instrumented_execute(self.raw, statement, args, kwargs)


class ObservedConnection:
    """Connection proxy whose cursors record Snowflake statements."""

    def __init__(self, connection: Any) -> None:
        self.raw = connection

    def __getattr__(self, name: str) -> Any:
        return getattr(self.raw, name)

    def __enter__(self) -> ObservedConnection:
        self.raw.__enter__()
        return self

    def __exit__(self, *args: Any) -> Any:
        return self.raw.__exit__(*args)

    def cursor(self, *args: Any, **kwargs: Any) -> ObservedCursor:
        return ObservedCursor(self.raw.cursor(*args, **kwargs))


def note_session_limits(statement: str) -> None:
    lock_match = _LOCK_TIMEOUT_SQL.search(statement)
    statement_match = _STATEMENT_TIMEOUT_SQL.search(statement)
    if lock_match is not None:
        _LOCK_TIMEOUT.set(_bounded_int(lock_match.group(1), 3600))
    if statement_match is not None:
        _STATEMENT_TIMEOUT.set(_bounded_int(statement_match.group(1), 3600))


def instrumented_execute(
    cursor: Any, statement: str, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> Any:
    """Run one statement and record a span and a log line around it."""
    if not observation_active():
        return cursor.execute(statement, *args, **kwargs)
    label = statement_label(statement) if isinstance(statement, str) else "sql.statement"
    if isinstance(statement, str):
        with suppress(Exception):
            note_session_limits(statement)
    started = time.perf_counter()
    error: BaseException | None = None
    try:
        with _span("snowflake.statement", step=label, statement_label=label):
            try:
                return cursor.execute(statement, *args, **kwargs)
            except BaseException as exc:
                error = exc
                raise
    finally:
        row_count = _row_count(cursor)
        duration_ms = _duration_ms(started)
        with suppress(Exception):
            record_statement(
                label,
                statement if isinstance(statement, str) else "",
                duration_ms=duration_ms,
                row_count=row_count,
                error=error,
            )


def record_statement(
    label: str,
    statement: str,
    *,
    duration_ms: int,
    row_count: int | None,
    error: BaseException | None,
) -> None:
    if not observation_active():
        return
    errno, sqlstate = _dbapi_error(error)
    fields: dict[str, Any] = {
        "statement_label": label,
        "step": label,
        "duration_ms": duration_ms,
        "row_count": row_count,
        "exception_class": type(error).__name__ if error is not None else None,
        "errno": errno,
        "sqlstate": sqlstate,
        "lock_timeout_seconds": _LOCK_TIMEOUT.get(),
        "statement_timeout_seconds": _STATEMENT_TIMEOUT.get(),
        "guard_depth": _GUARD_DEPTH.get(),
    }
    shape = scrub_sql(statement)
    if shape and _FORBIDDEN.search(shape) is None:
        fields["statement_shape"] = shape[:300]
    if label in _LOCK_LABELS or _GUARD_DEPTH.get() > 0:
        # Duration of the guarded statement, not Snowflake's lock-wait timer.
        fields["guarded_statement_ms"] = duration_ms
    emit("snowflake.statement", **fields)
    if errno in {625, 630}:
        emit("lock.timeout", level="WARNING", **fields)


def record_http(
    url: str,
    *,
    status: int | None,
    duration_ms: int,
    nbytes: int | None,
    retry_count: int,
    exception_class: str | None,
) -> None:
    if not observation_active():
        return
    host, path = _http_target(url)
    safe_status = status if type(status) is int and 100 <= status <= 599 else None
    safe_bytes = nbytes if type(nbytes) is int and 0 <= nbytes <= 10_000_000 else None
    if safe_bytes is not None:
        _BYTES.set(min(_BYTES.get() + safe_bytes, 10_000_000))
    retries = retry_count if type(retry_count) is int and 0 <= retry_count <= 20 else 0
    emit(
        "http.client",
        step="http.get",
        host=host,
        path=path,
        http_status=safe_status,
        duration_ms=duration_ms,
        bytes=safe_bytes,
        retry_count=retries,
        exception_class=exception_class if _exception_class(exception_class) else None,
    )


@contextmanager
def http_observation(url: str) -> Iterator[dict[str, Any]]:
    """Time one outbound call. The yielded dict receives status, bytes, and retries."""
    started = time.perf_counter()
    state: dict[str, Any] = {"status": None, "bytes": None, "error": None, "retries": 0}
    if not observation_active():
        yield state
        return
    host, path = _http_target(url)
    try:
        with _span("http.client", step="http.get", host=host, path=path):
            yield state
    except BaseException as exc:
        state["error"] = type(exc).__name__
        raise
    finally:
        status = state.get("status")
        nbytes = state.get("bytes")
        retries = state.get("retries")
        error = state.get("error")
        record_http(
            url,
            status=status if type(status) is int else None,
            duration_ms=_duration_ms(started),
            nbytes=nbytes if type(nbytes) is int else None,
            retry_count=retries if type(retries) is int else 0,
            exception_class=error if isinstance(error, str) else None,
        )


@contextmanager
def _observed_step(step: str, **fields: Any) -> Iterator[None]:
    """Emit one step and keep its span open for the body so duration is real."""
    if not observation_active():
        yield
        return
    started = time.perf_counter()
    try:
        with _span(step, step=step, **fields) as span:
            try:
                yield
            finally:
                if span is not None:
                    with suppress(Exception):
                        span.set_attribute("duration_ms", _duration_ms(started))
    finally:
        emit(step, step=step, duration_ms=_duration_ms(started), **fields)


@contextmanager
def record_checkpoint(operation: str) -> Iterator[None]:
    step = "checkpoint.read" if operation == "read" else "checkpoint.write"
    with _observed_step(step):
        yield


@contextmanager
def record_ledger(operation: str, kind: str) -> Iterator[None]:
    step = "ledger.read" if operation == "read" else "ledger.write"
    safe_kind = kind if _IDENTIFIER.fullmatch(kind) else None
    with _observed_step(step, statement_label=safe_kind):
        yield


@contextmanager
def record_lease(action: str) -> Iterator[None]:
    if action not in {"acquire", "get", "renew", "release"}:
        yield
        return
    with _observed_step(f"lease.{action}"):
        yield


@contextmanager
def guard_scope(*, nested: bool) -> Iterator[int]:
    if not observation_active():
        yield _GUARD_DEPTH.get()
        return
    depth = _GUARD_DEPTH.get() + 1
    token = _GUARD_DEPTH.set(depth)
    emit(
        "guard.enter",
        step="guard.enter",
        guard_depth=depth,
        nested=nested,
    )
    try:
        with _span(
            "intelligence-daily.guard",
            step="guard.enter",
            guard_depth=depth,
            nested=nested,
        ):
            yield depth
    finally:
        emit("guard.exit", step="guard.exit", guard_depth=depth)
        _GUARD_DEPTH.reset(token)


def warn_open_transaction() -> None:
    emit(
        "guard.transaction_open",
        level="WARNING",
        step="guard.enter",
        guard_depth=_GUARD_DEPTH.get(),
        transaction_open=True,
    )


@contextmanager
def stage_scope(stage: str) -> Iterator[None]:
    if not observation_active():
        yield
        return
    publish_stage(stage)
    token = _STAGE.set(stage if _IDENTIFIER.fullmatch(stage) else None)
    _emit_with_memory("stage.open", step=stage, stage=stage)
    try:
        with _span("intelligence-daily.stage", stage=stage, step=stage, **process_memory_fields()):
            yield
    finally:
        _emit_with_memory("stage.close", step=stage, stage=stage)
        publish_stage(None)
        _STAGE.reset(token)


@contextmanager
def source_span(source_id: str) -> Iterator[None]:
    if not observation_active():
        yield
        return
    bind_context(source_id=source_id)
    _emit_with_memory("source.open", step="source")
    try:
        with _span("intelligence-daily.source", source_id=source_id, step="source"):
            yield
    finally:
        _emit_with_memory("source.close", step="source")


@contextmanager
def job_span() -> Iterator[None]:
    if not observation_active():
        yield
        return
    with _span("intelligence-daily.job", step="job"):
        yield


@contextmanager
def step_span(step: str) -> Iterator[None]:
    if not observation_active():
        yield
        return
    token = _STEP.set(step if _IDENTIFIER.fullmatch(step) else None)
    try:
        with _span("intelligence-daily.step", step=step):
            yield
    finally:
        _STEP.reset(token)


class StageHeartbeat:
    """Parent-side or in-process heartbeat. The thread only queues a log line."""

    def __init__(self, *, interval: float = HEARTBEAT_SECONDS, clock: Any = time.monotonic) -> None:
        self.interval = interval
        self.clock = clock
        self._open: str | None = None
        self._last = self.clock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def set_open(self, stage: str | None) -> None:
        self._open = stage if isinstance(stage, str) and _IDENTIFIER.fullmatch(stage) else None

    def poll(self) -> None:
        stage = self._open
        if stage is None:
            return
        now = self.clock()
        if now - self._last + 1e-9 < self.interval:
            return
        self._last = now
        _emit_with_memory("stage.heartbeat", step="heartbeat", stage=stage)

    def start(self) -> None:
        current = _HEARTBEAT.get()
        if current is None:
            _HEARTBEAT.set(self)
        if self._thread is not None:
            return
        self._thread = spawn_observed(self._loop, name="intelligence-daily-heartbeat")

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(1)
        if _HEARTBEAT.get() is self:
            _HEARTBEAT.set(None)

    def _loop(self) -> None:
        while not self._stop.wait(min(self.interval, 1)):
            with suppress(Exception):
                publish_progress(self._open)
                self.poll()


def publish_stage(stage: str | None) -> None:
    heartbeat = _HEARTBEAT.get()
    if heartbeat is not None:
        heartbeat.set_open(stage)
    stage_queue = _STAGE_QUEUE.get()
    if stage_queue is not None:
        with suppress(Exception):
            stage_queue.put_nowait("" if stage is None else stage)


def publish_progress(stage: str | None) -> None:
    """Queue a liveness pulse. The parent treats it as progress, not as content."""
    stage_queue = _STAGE_QUEUE.get()
    if stage_queue is None:
        return
    marker = stage if isinstance(stage, str) and _IDENTIFIER.fullmatch(stage) else "LIVE"
    with suppress(Exception):
        stage_queue.put_nowait(marker)


def emit_source_summary(
    *,
    status: str,
    seconds: float,
    items: int | None,
    nbytes: int | None,
    failure_code: str | None,
) -> None:
    emit(
        "source.summary",
        step="source.summary",
        status=status if _IDENTIFIER.fullmatch(status) else "FAILED",
        seconds=_bounded_seconds(seconds),
        items=items if type(items) is int and 0 <= items <= 1_000_000 else None,
        bytes=(
            nbytes if type(nbytes) is int and 0 <= nbytes <= 10_000_000 else transferred_bytes()
        ),
        failure_code=(
            failure_code
            if isinstance(failure_code, str) and _FAILURE.fullmatch(failure_code)
            else None
        ),
        peak_rss_kb=peak_rss_kb(),
    )


def emit_run_summary(
    *,
    status: str,
    seconds: float,
    sources: int,
    failed: int,
    failure_class: str | None = None,
) -> None:
    safe_status = status if status in {"SUCCEEDED", "FAILED", "DISABLED"} else "FAILED"
    safe_failed = failed if type(failed) is int and 0 <= failed <= 100 else None
    safe_class = (
        failure_class
        if isinstance(failure_class, str) and _EXCEPTION.fullmatch(failure_class)
        else None
    )
    emit(
        "run.summary",
        step="run.summary",
        status=safe_status,
        seconds=_bounded_seconds(seconds),
        items=sources if type(sources) is int and 0 <= sources <= 100 else None,
        failed=safe_failed,
        exception_class=safe_class,
        failure_code=None if safe_status != "FAILED" else "RUN_FAILED",
        peak_rss_kb=peak_rss_kb(),
    )


def carrier_from_current() -> dict[str, str]:
    carrier: dict[str, str] = {}
    with suppress(Exception):
        inject(carrier)
    safe: dict[str, str] = {}
    for key, value in carrier.items():
        if (
            isinstance(key, str)
            and isinstance(value, str)
            and _IDENTIFIER.fullmatch(key)
            and len(value) <= 200
            and _FORBIDDEN.search(value) is None
        ):
            safe[key] = value
    return safe


def attach_carrier(carrier: Mapping[str, str] | None) -> None:
    if not carrier:
        return
    with suppress(Exception):
        otel_context.attach(extract(dict(carrier)))


def prepare_worker(spec: Mapping[str, Any]) -> None:
    """Configure export in a spawned child. Failures stay in the child."""
    with suppress(Exception):
        configure_literature_tracing(SERVICE_NAME)
    with suppress(Exception):
        configure_daily_log_export()
    activate_observation()
    trace_carrier = spec.get("_trace")
    if isinstance(trace_carrier, Mapping):
        attach_carrier(
            {
                str(key): value
                for key, value in trace_carrier.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        )
    bind_stage_queue(spec.get("_stage_queue"))


def configure_daily_log_export() -> None:
    """Ship logs to OTLP ``/v1/logs`` with the existing traces credential."""
    global _EXPORT_THREAD, _LOG_PROVIDER, _LOG_EMITTER
    endpoint = _logs_endpoint()
    if not endpoint or _LOG_EMITTER is not None:
        return
    try:
        headers = parse_otlp_headers(os.getenv("OTEL_EXPORTER_OTLP_HEADERS"))
    except Exception:
        return
    try:
        exporter = OTLPLogExporter(endpoint=endpoint, headers=headers, timeout=3)
        provider = LoggerProvider(
            resource=Resource.create(
                {
                    "service.name": SERVICE_NAME,
                    "service_name": SERVICE_NAME,
                    "component": COMPONENT,
                }
            ),
            shutdown_on_exit=False,
        )
        provider.add_log_record_processor(
            BatchLogRecordProcessor(
                exporter,
                max_queue_size=256,
                schedule_delay_millis=1000,
                max_export_batch_size=64,
                export_timeout_millis=3000,
            )
        )
        _LOG_PROVIDER = provider
        _LOG_EMITTER = provider.get_logger(COMPONENT)
    except Exception:
        _LOG_EMITTER = None
        return
    if _EXPORT_THREAD is None:
        _EXPORT_THREAD = spawn_observed(_export_loop, name="intelligence-daily-log-export")


def shutdown_daily_logs() -> None:
    thread = _EXPORT_THREAD
    provider = _LOG_PROVIDER
    if thread is not None:
        with suppress(Exception):
            _EXPORT_QUEUE.put_nowait(None)
        if thread is not threading.current_thread():
            thread.join(3)
    if provider is not None:
        completed = threading.Event()

        def flush() -> None:
            with suppress(Exception):
                provider.force_flush(timeout_millis=3000)
                provider.shutdown()
            completed.set()

        spawn_observed(flush, name="intelligence-daily-log-flush")
        completed.wait(3)


def emit(event: str, *, level: str = "INFO", **fields: Any) -> None:
    if not observation_active():
        return
    try:
        payload = _payload(event, level, fields)
        _remember(payload)
        _write_stdout(payload)
        _enqueue_export(payload)
    except Exception:
        return


def _emit_with_memory(event: str, **fields: Any) -> None:
    memory = process_memory_fields()
    emit(
        event,
        rss_kib=memory["rss_kib"],
        peak_rss_kib=memory["peak_rss_kib"],
        **fields,
    )


def process_memory_fields() -> dict[str, int]:
    """Current and peak RSS in kibibytes. No other process fields."""
    rss, peak = _proc_rss_kib()
    return {
        "rss_kib": rss if isinstance(rss, int) and rss >= 0 else 0,
        "peak_rss_kib": peak if isinstance(peak, int) and peak >= 0 else peak_rss_kb(),
    }


def _proc_rss_kib() -> tuple[int | None, int | None]:
    rss: int | None = None
    peak: int | None = None
    try:
        status = Path("/proc/self/status").read_text(encoding="utf-8")
    except OSError:
        status = ""
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            rss = _status_kib(line)
        elif line.startswith("VmHWM:"):
            peak = _status_kib(line)
    if peak is None:
        peak = peak_rss_kb() or None
    return rss, peak


def _status_kib(line: str) -> int | None:
    digits = "".join(char for char in line if char.isdigit())
    if not digits:
        return None
    return int(digits)


def peak_rss_kb() -> int:
    try:
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except Exception:
        return 0
    if sys.platform == "darwin":
        value //= 1024
    if value < 0:
        return 0
    return min(value, 100_000_000)


def _logs_endpoint() -> str | None:
    explicit = os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not isinstance(endpoint, str) or not endpoint.strip():
        return None
    trimmed = endpoint.strip()
    if trimmed.endswith("/v1/traces"):
        return trimmed[: -len("/v1/traces")] + "/v1/logs"
    if trimmed.endswith("/v1/logs"):
        return trimmed
    return trimmed.rstrip("/") + "/v1/logs"


def _payload(event: str, level: str, fields: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event": event if _IDENTIFIER.fullmatch(event) else "telemetry.event",
        "level": level if level in {"DEBUG", "INFO", "WARNING", "ERROR"} else "INFO",
        "service_name": SERVICE_NAME,
        "component": COMPONENT,
    }
    source_id = _SOURCE_ID.get()
    run_id = _RUN_ID.get()
    attempt = _ATTEMPT.get()
    stage = _STAGE.get()
    step = _STEP.get()
    if source_id is not None:
        payload["source_id"] = source_id
    if run_id is not None:
        payload["run_id"] = run_id
    if attempt is not None:
        payload["attempt"] = attempt
    if stage is not None:
        payload["stage"] = stage
    if step is not None and "step" not in fields:
        payload["step"] = step
    for key, value in fields.items():
        safe = _field(key, value)
        if safe is not None:
            payload[key] = safe
    return payload


def _field(key: str, value: Any) -> Any:
    if not _IDENTIFIER.fullmatch(key) or isinstance(value, (bytes, bytearray)):
        return None
    if value is None:
        return None
    if key == "statement_shape" and isinstance(value, str):
        if (
            len(value) > 300
            or _FORBIDDEN.search(value) is not None
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            return None
        return value
    if key == "path" and isinstance(value, str) and _PATH.fullmatch(value):
        return value
    if key == "host" and isinstance(value, str) and _HOST.fullmatch(value):
        return value
    if type(value) is bool:
        return value
    if (
        type(value) is int
        and not isinstance(value, bool)
        and -1_000_000_000 <= value <= 1_000_000_000
    ):
        return value
    if type(value) is float and 0 <= value <= 86_400:
        return round(value, 3)
    if isinstance(value, str) and _IDENTIFIER.fullmatch(value) and _FORBIDDEN.search(value) is None:
        return value[:200]
    return None


def _remember(payload: dict[str, Any]) -> None:
    with _EVENTS_LOCK:
        _EVENTS.append(dict(payload))
        if len(_EVENTS) > _MAX_EVENTS:
            del _EVENTS[: len(_EVENTS) - _MAX_EVENTS]


def _write_stdout(payload: dict[str, Any]) -> None:
    line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if _FORBIDDEN.search(line):
        return
    _LOGGER.info(line)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _enqueue_export(payload: dict[str, Any]) -> None:
    if _LOG_EMITTER is None:
        return
    with suppress(queue.Full):
        _EXPORT_QUEUE.put_nowait(payload)


def _export_loop() -> None:
    while True:
        try:
            item = _EXPORT_QUEUE.get()
        except Exception:
            return
        if item is None:
            return
        emitter = _LOG_EMITTER
        if emitter is None:
            continue
        with suppress(Exception):
            attributes = {
                key: value
                for key, value in item.items()
                if key != "event" and isinstance(value, (str, int, float, bool))
            }
            emitter.emit(body=str(item.get("event", "telemetry.event"))[:80], attributes=attributes)


@contextmanager
def _span(name: str, **attributes: Any) -> Iterator[Any]:
    started = False
    span_cm: Any = None
    current: Any = None
    try:
        span_cm = trace.get_tracer(SERVICE_NAME).start_as_current_span(
            name, record_exception=False, set_status_on_exception=False
        )
        current = span_cm.__enter__()
        started = True
        _apply_span_attributes(current, attributes)
    except Exception:
        if started and span_cm is not None:
            with suppress(Exception):
                span_cm.__exit__(None, None, None)
        yield None
        return
    try:
        yield current
    except BaseException as exc:
        with suppress(Exception):
            current.set_attribute("exception_class", type(exc).__name__)
            current.set_status(Status(StatusCode.ERROR, type(exc).__name__))
        raise
    finally:
        if started:
            with suppress(Exception):
                span_cm.__exit__(None, None, None)


def _apply_span_attributes(span: Any, attributes: Mapping[str, Any]) -> None:
    base = _payload("span", "INFO", attributes)
    for key in (
        "service_name",
        "component",
        "source_id",
        "run_id",
        "attempt",
        "stage",
        "step",
        "statement_label",
        "duration_ms",
        "row_count",
        "exception_class",
        "errno",
        "sqlstate",
        "guarded_statement_ms",
        "nested",
        "lock_timeout_seconds",
        "statement_timeout_seconds",
        "guard_depth",
        "host",
        "path",
        "http_status",
        "bytes",
        "retry_count",
        "status",
        "failure_code",
        "rss_kib",
        "peak_rss_kib",
    ):
        if key in base and base[key] is not None:
            span.set_attribute(key, base[key])
        elif key in attributes:
            safe = _field(key, attributes[key])
            if safe is not None:
                span.set_attribute(key, safe)


def _http_target(url: str) -> tuple[str | None, str | None]:
    try:
        parts = urlsplit(url)
    except Exception:
        return None, None
    host = parts.hostname if isinstance(parts.hostname, str) else None
    raw_path = parts.path or "/"
    if host is None or not _HOST.fullmatch(host) or "@" in host:
        host = None
    path = raw_path if _PATH.fullmatch(raw_path) and "?" not in raw_path else None
    return host, path


def _dbapi_error(error: BaseException | None) -> tuple[int | None, str | None]:
    if error is None:
        return None, None
    errno = getattr(error, "errno", None)
    sqlstate = getattr(error, "sqlstate", None)
    safe_errno = errno if type(errno) is int and 0 <= errno <= 1_000_000 else None
    safe_state = sqlstate if isinstance(sqlstate, str) and _SQLSTATE.fullmatch(sqlstate) else None
    return safe_errno, safe_state


def _row_count(cursor: Any) -> int | None:
    try:
        value = cursor.rowcount
    except Exception:
        return None
    if type(value) is int and not isinstance(value, bool) and 0 <= value <= 10_000_000:
        return value
    return None


def _duration_ms(started: float) -> int:
    elapsed = time.perf_counter() - started
    if elapsed <= 0:
        return 0
    return min(int(elapsed * 1000), 86_400_000)


def _bounded_int(value: str, limit: int) -> int | None:
    if not value.isdigit():
        return None
    number = int(value)
    if 0 <= number <= limit:
        return number
    return None


def _bounded_seconds(value: float) -> float:
    if type(value) not in {int, float} or value < 0:
        return 0.0
    return round(min(float(value), 86_400.0), 3)


def _exception_class(value: str | None) -> bool:
    return isinstance(value, str) and _EXCEPTION.fullmatch(value) is not None


def _logger_ready() -> None:
    global _STDOUT_READY
    if _STDOUT_READY:
        return
    _LOGGER.setLevel(logging.INFO)
    _LOGGER.propagate = False
    _STDOUT_READY = True


_logger_ready()
