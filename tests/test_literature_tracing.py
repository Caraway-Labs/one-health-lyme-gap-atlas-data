"""Real SDK spans exercise bounded whole-invocation export, without network I/O."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from typing import Any

import pytest
import requests
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode

from lyme_gap_atlas_data import literature_tracing as module


class Recorder(SpanProcessor):
    def __init__(self) -> None:
        self.spans: list[ReadableSpan] = []
        self.received = Event()
        self.shutdowns = 0
        self.budgets: list[int] = []

    def on_end(self, span: ReadableSpan) -> None:
        self.spans.append(span)
        self.received.set()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        self.budgets.append(timeout_millis)
        return True

    def shutdown(self) -> None:
        self.shutdowns += 1


def make_provider(**limits: Any) -> tuple[TracerProvider, Recorder, module.InvocationSpanProcessor]:
    recorder = Recorder()
    processor = module.InvocationSpanProcessor(recorder, **limits)
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(processor)
    return provider, recorder, processor


def test_early_children_wait_for_error_root_and_preserve_hierarchy() -> None:
    provider, recorder, _ = make_provider()
    tracer = provider.get_tracer("fixture")
    with tracer.start_as_current_span("atlas-data.cli") as root:
        with tracer.start_as_current_span("fixture.early_success"):
            pass
        assert recorder.spans == []
        root.set_status(Status(StatusCode.ERROR, "fixture_failure"))
    assert [span.name for span in recorder.spans] == ["atlas-data.cli", "fixture.early_success"]
    assert recorder.spans[0].status.status_code is StatusCode.ERROR
    assert recorder.spans[1].parent is not None
    assert recorder.spans[0].context is not None
    assert recorder.spans[1].parent.span_id == recorder.spans[0].context.span_id
    assert provider.force_flush()
    provider.shutdown()
    assert recorder.shutdowns == 1


def test_span_limit_streams_without_dropping_or_aborting_command(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider, recorder, _ = make_provider(max_spans=2)
    tracer = provider.get_tracer("fixture")
    with tracer.start_as_current_span("atlas-data.cli"):
        for index in range(3):
            with tracer.start_as_current_span(f"fixture.child.{index}"):
                pass
        assert len(recorder.spans) == 3
    assert len(recorder.spans) == 4
    assert "span_limit" in caplog.text
    provider.shutdown()


def test_duration_limit_releases_finished_spans_while_command_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider, recorder, _ = make_provider(max_duration_seconds=0.02)
    tracer = provider.get_tracer("fixture")
    with tracer.start_as_current_span("atlas-data.cli"):
        with tracer.start_as_current_span("fixture.child"):
            pass
        assert recorder.received.wait(1)
        assert [span.name for span in recorder.spans] == ["fixture.child"]
    assert len(recorder.spans) == 2
    assert "duration_limit" in caplog.text
    provider.shutdown()


@pytest.mark.parametrize("action", ["force_flush", "shutdown"])
def test_explicit_early_flush_or_shutdown_preserves_finished_spans(
    action: str, caplog: pytest.LogCaptureFixture
) -> None:
    provider, recorder, processor = make_provider()
    tracer = provider.get_tracer("fixture")
    root = tracer.start_span("atlas-data.cli")
    context = trace.set_span_in_context(root)
    child = tracer.start_span("fixture.child", context=context)
    child.end()
    getattr(processor, action)()
    assert [span.name for span in recorder.spans] == ["fixture.child"]
    root.end()
    assert "before_root" in caplog.text
    provider.shutdown()


def test_unrelated_trace_does_not_wait_for_invocation_root() -> None:
    provider, recorder, _ = make_provider()
    tracer = provider.get_tracer("fixture")
    with tracer.start_as_current_span("atlas-data.cli"):
        with tracer.start_as_current_span("fixture.child"):
            pass
        other = tracer.start_span("fixture.unrelated", context=Context())
        other.end()
        assert [span.name for span in recorder.spans] == ["fixture.unrelated"]
    assert len(recorder.spans) == 3
    provider.shutdown()


def test_concurrent_children_are_released_once_after_root() -> None:
    provider, recorder, _ = make_provider()
    tracer = provider.get_tracer("fixture")
    with tracer.start_as_current_span("atlas-data.cli") as root:
        context = trace.set_span_in_context(root)
        children = [tracer.start_span("fixture.child", context=context) for _ in range(32)]
        threads = [Thread(target=child.end) for child in children]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert recorder.spans == []
    assert len(recorder.spans) == 33
    assert recorder.spans[0].name == "atlas-data.cli"
    assert len({span.context.span_id for span in recorder.spans if span.context}) == 33
    provider.shutdown()


@pytest.mark.parametrize("action", ["force_flush", "shutdown"])
def test_delegate_cannot_ignore_export_wait_budget(
    action: str, caplog: pytest.LogCaptureFixture
) -> None:
    release = Event()
    finished = Event()

    class Blocked(Recorder):
        def force_flush(self, timeout_millis: int = 30000) -> bool:
            release.wait(2)
            finished.set()
            return True

        def shutdown(self) -> None:
            self.force_flush()

    processor = module.InvocationSpanProcessor(Blocked(), flush_timeout_millis=10)
    started = monotonic()
    result = getattr(processor, action)()
    assert monotonic() - started < 1
    if action == "force_flush":
        assert result is False
    assert "flush_timeout" in caplog.text
    release.set()
    assert finished.wait(1)


def test_delegate_errors_are_fail_open_and_never_log_payloads(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Broken(Recorder):
        def on_end(self, span: ReadableSpan) -> None:
            raise RuntimeError("SECRET_EXPORTER_SENTINEL")

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            raise RuntimeError("SECRET_EXPORTER_SENTINEL")

        def shutdown(self) -> None:
            raise RuntimeError("SECRET_EXPORTER_SENTINEL")

    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(module.InvocationSpanProcessor(Broken()))
    with provider.get_tracer("fixture").start_as_current_span("atlas-data.cli"):
        pass
    assert provider.force_flush() is False
    provider.shutdown()
    assert "SECRET_EXPORTER_SENTINEL" not in caplog.text
    assert "processor_unavailable" in caplog.text
    assert "exporter_unavailable" in caplog.text


def test_standard_batch_queue_and_attribute_limits_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = InMemorySpanExporter()
    providers: list[TracerProvider] = []
    exporter_args: list[dict[str, Any]] = []

    def exporter_factory(**kwargs: Any) -> InMemorySpanExporter:
        exporter_args.append(kwargs)
        return exporter

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.invalid/v1/traces")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "authorization=fixture-opaque")
    monkeypatch.setattr(module, "OTLPSpanExporter", exporter_factory)
    monkeypatch.setattr(module.trace, "set_tracer_provider", providers.append)
    module.configure_literature_tracing("fixture")
    provider = providers[0]
    with provider.get_tracer("fixture").start_as_current_span("atlas-data.cli") as root:
        for index in range(80):
            root.set_attribute(f"fixture.value.{index}", index)
        root.set_attribute("fixture.long", "x" * 4096)
        root.add_event("SECRET_EVENT_SENTINEL")
        assert exporter.get_finished_spans() == ()
    assert provider.force_flush()
    exported = exporter.get_finished_spans()[0]
    assert len(exported.attributes or {}) <= 64
    assert all(
        len(value) <= 1024
        for value in (exported.attributes or {}).values()
        if isinstance(value, str)
    )
    assert exported.events == ()
    assert (exported.attributes or {})["fixture.long"] == "x" * 1024
    assert exporter_args[0] == {
        "endpoint": "https://collector.invalid/v1/traces",
        "headers": {"authorization": "fixture-opaque"},
        "timeout": 3,
    }
    provider.shutdown()


def test_disabled_tracing_has_no_parallel_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setattr(
        module.trace, "set_tracer_provider", lambda _provider: pytest.fail("unexpected provider")
    )
    module.configure_literature_tracing("fixture")
    with trace.use_span(trace.INVALID_SPAN):
        assert module.trace_fields() == {}


@pytest.mark.parametrize("exception_type", [requests.RequestException, requests.ConnectionError])
def test_real_exporter_transport_reason_is_redacted_and_connection_retry_preserved(
    exception_type: type[requests.RequestException],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinel = "UNMISTAKABLY_FAKE_OTLP_TRANSPORT_SENTINEL"
    calls: list[int] = []
    providers: list[TracerProvider] = []

    def post(*_args: Any, **_kwargs: Any) -> None:
        calls.append(1)
        raise exception_type(sentinel)

    monkeypatch.setattr(requests.Session, "post", post)
    monkeypatch.setattr(
        requests.Session, "send", lambda *_args, **_kwargs: pytest.fail("network I/O forbidden")
    )
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.invalid/v1/traces")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "authorization=fixture-valid")
    monkeypatch.setattr(module.trace, "set_tracer_provider", providers.append)
    module.configure_literature_tracing("fixture")
    provider = providers[0]
    with provider.get_tracer("fixture").start_as_current_span("atlas-data.cli"):
        pass
    assert provider.force_flush()
    provider.shutdown()
    captured = capsys.readouterr()
    assert sentinel not in caplog.text + captured.out + captured.err
    if exception_type is requests.ConnectionError:
        assert len(calls) >= 2
        assert "Transient error connection_error" in caplog.text
        assert "timeout, max retries or shutdown" in caplog.text
    else:
        assert len(calls) == 1
        assert "code: None, reason: request_exception" in caplog.text


def test_real_exporter_http_status_survives_reason_redaction(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sentinel = "UNMISTAKABLY_FAKE_OTLP_RESPONSE_SENTINEL"
    providers: list[TracerProvider] = []
    response = requests.Response()
    response.status_code = 400
    response.reason = sentinel
    monkeypatch.setattr(requests.Session, "post", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(
        requests.Session, "send", lambda *_args, **_kwargs: pytest.fail("network I/O forbidden")
    )
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.invalid/v1/traces")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "authorization=fixture-valid")
    monkeypatch.setattr(module.trace, "set_tracer_provider", providers.append)
    module.configure_literature_tracing("fixture")
    provider = providers[0]
    with provider.get_tracer("fixture").start_as_current_span("atlas-data.cli"):
        pass
    assert provider.force_flush()
    provider.shutdown()
    assert sentinel not in caplog.text
    assert "code: 400, reason: http_response" in caplog.text


def test_context_failure_does_not_block_durable_diagnostics(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def unavailable() -> None:
        raise RuntimeError("SECRET_CONTEXT_SENTINEL")

    monkeypatch.setattr(module.trace, "get_current_span", unavailable)
    assert module.trace_fields() == {}
    assert "trace_context_unavailable" in caplog.text
    assert "SECRET_CONTEXT_SENTINEL" not in caplog.text


def test_trace_identity_comes_from_actual_sdk_context() -> None:
    provider = TracerProvider(shutdown_on_exit=False)
    with provider.get_tracer("fixture").start_as_current_span("fixture.root") as span:
        assert module.trace_fields() == {
            "trace_id": format(span.get_span_context().trace_id, "032x")
        }
    provider.shutdown()


def test_timer_start_failure_falls_back_without_ending_command(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class FailedTimer:
        daemon = False

        def __init__(self, *_args: object) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("SECRET_TIMER_SENTINEL")

        def cancel(self) -> None:
            pass

    monkeypatch.setattr(module, "Timer", FailedTimer)
    provider, recorder, _ = make_provider()
    with provider.get_tracer("fixture").start_as_current_span("atlas-data.cli"):
        with provider.get_tracer("fixture").start_as_current_span("fixture.child"):
            pass
        assert len(recorder.spans) == 1
    assert len(recorder.spans) == 2
    assert "timer_unavailable" in caplog.text
    assert "SECRET_TIMER_SENTINEL" not in caplog.text
    provider.shutdown()


def test_hard_exit_keeps_committed_attempt_context_even_when_buffer_is_lost(
    tmp_path: Path,
) -> None:
    diagnostic_path, export_path = tmp_path / "diagnostic.json", tmp_path / "exported"
    script = """
import json, os, sys
from pathlib import Path
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor
from lyme_gap_atlas_data.literature_tracing import InvocationSpanProcessor
from lyme_gap_atlas_data import pmc_extraction_worker as module
class Export(SpanProcessor):
    def on_end(self, span):
        Path(sys.argv[2]).write_text('exported')
class Cursor:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, args):
        if "'attempt_context'" in sql: self.details = args[3]
class Connection:
    def __init__(self): self.c = Cursor()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def cursor(self): return self.c
    def autocommit(self, value): pass
    def commit(self): Path(sys.argv[1]).write_text(self.c.details)
    def rollback(self): pass
module.connect = lambda settings: Connection()
provider = TracerProvider(shutdown_on_exit=False)
provider.add_span_processor(InvocationSpanProcessor(Export()))
trace.set_tracer_provider(provider)
tracer = provider.get_tracer('fixture')
with tracer.start_as_current_span('atlas-data.cli') as root:
    with tracer.start_as_current_span('fixture.persist'):
        paper = module.ApprovedPaper(
            '1','PMC1','fixture','fixture','2026-01-01',(),'en',('match',),'approved'
        )
        module.SnowflakePMCExtractionLedger(bucket='fixture').record_attempt(paper,'b'*64,'fixture',10,900)
    os._exit(143)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(diagnostic_path), str(export_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 143, result.stderr
    persisted = json.loads(diagnostic_path.read_text())
    assert len(persisted["trace_id"]) == 32
    assert int(persisted["trace_id"], 16) != 0
    assert persisted["run_id"]
    assert not export_path.exists()
