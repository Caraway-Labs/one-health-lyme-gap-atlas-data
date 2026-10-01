from __future__ import annotations

import logging
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest
import requests
import typer
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from lyme_gap_atlas_data import cli
from lyme_gap_atlas_data.literature_tracing import InvocationSpanProcessor


class FakeSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, Any] = {}
        self.status: Any = None
        self.ended = False

    def set_attribute(self, name: str, value: Any) -> None:
        self.attributes[name] = value

    def set_status(self, status: Any) -> None:
        self.status = status

    def end(self) -> None:
        self.ended = True

    def __enter__(self) -> FakeSpan:
        return self

    def __exit__(self, *_args: object) -> None:
        self.end()


class FakeProvider:
    def __init__(self) -> None:
        self.flushes = 0
        self.shutdowns = 0

    def force_flush(self) -> None:
        self.flushes += 1

    def shutdown(self) -> None:
        self.shutdowns += 1


def _configure_observed_app(monkeypatch: pytest.MonkeyPatch, span: FakeSpan) -> FakeProvider:
    provider = FakeProvider()
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "configure_tracing", lambda _service: None)
    monkeypatch.setenv("TOPX_ENV", "prod")

    def start_span(_name: str, **kwargs: object) -> FakeSpan:
        assert kwargs == {"record_exception": False, "set_status_on_exception": False}
        return span

    tracer = SimpleNamespace(start_as_current_span=start_span)
    monkeypatch.setattr(cli.trace, "get_tracer", lambda _service: tracer)
    monkeypatch.setattr(cli.trace, "get_tracer_provider", lambda: provider)
    return provider


def test_cli_root_span_has_only_safe_success_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    span = FakeSpan()
    provider = _configure_observed_app(monkeypatch, span)
    monkeypatch.setattr(
        cli.sys, "argv", ["atlas-data", "pipeline", "discover", "--token", "secret"]
    )
    monkeypatch.setattr(typer.Typer, "__call__", lambda *_args, **_kwargs: None)

    cli.ObservedTyper()()

    assert span.attributes["atlas.command"] == "pipeline.discover"
    assert span.attributes["atlas.environment"] == "prod"
    assert span.attributes["atlas.outcome"] == "success"
    assert "secret" not in repr(span.attributes)
    assert span.ended is True
    assert (provider.flushes, provider.shutdowns) == (1, 1)


def test_cli_initializes_observability_once_per_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    span = FakeSpan()
    provider = FakeProvider()
    logging_initializations = 0
    tracing_initializations: list[str] = []

    def configure_log() -> None:
        nonlocal logging_initializations
        logging_initializations += 1

    monkeypatch.setattr(cli, "configure_logging", configure_log)
    monkeypatch.setattr(cli, "configure_tracing", tracing_initializations.append)
    monkeypatch.setattr(
        cli.trace,
        "get_tracer",
        lambda _service: SimpleNamespace(start_as_current_span=lambda _name, **_kwargs: span),
    )
    monkeypatch.setattr(cli.trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(typer.Typer, "__call__", lambda *_args, **_kwargs: None)

    cli.ObservedTyper()()

    assert logging_initializations == 1
    assert tracing_initializations == [cli.SERVICE_NAME]


def test_cli_root_span_marks_a_failure_without_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    span = FakeSpan()
    provider = _configure_observed_app(monkeypatch, span)
    monkeypatch.setattr(cli.sys, "argv", ["atlas-data", "load", "--release", "do-not-record"])

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("do-not-record")

    monkeypatch.setattr(typer.Typer, "__call__", fail)

    with pytest.raises(RuntimeError, match="do-not-record"):
        cli.ObservedTyper()()

    assert span.attributes["atlas.command"] == "load"
    assert span.attributes["atlas.outcome"] == "failure"
    assert span.attributes["error.type"] == "RuntimeError"
    assert "do-not-record" not in repr(span.attributes)
    assert span.status.status_code.name == "ERROR"
    assert (provider.flushes, provider.shutdowns) == (1, 1)


def test_pmc_extraction_command_requires_explicit_confirmation() -> None:
    command = next(
        item for item in cli.pipeline_app.registered_commands if item.name == "pmc-extract"
    )
    assert command.callback is not None
    with pytest.raises(typer.BadParameter, match="steward approves"):
        command.callback(estimated_cost_usd=1.0, confirm=False)


def test_exported_cli_span_never_contains_exception_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "configure_tracing", lambda _service: None)
    monkeypatch.setattr(cli.trace, "get_tracer", lambda _service: provider.get_tracer("test"))
    monkeypatch.setattr(cli.trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(cli.sys, "argv", ["atlas-data", "pipeline", "pmc-extract"])

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("SECRET_MODEL_INPUT_SENTINEL")

    monkeypatch.setattr(typer.Typer, "__call__", fail)
    with pytest.raises(RuntimeError, match="SECRET_MODEL_INPUT_SENTINEL"):
        cli.ObservedTyper()()
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].events == ()
    assert "SECRET_MODEL_INPUT_SENTINEL" not in repr(spans[0].attributes)
    assert "SECRET_MODEL_INPUT_SENTINEL" not in repr(spans[0].status)


def test_bad_exporter_configuration_cannot_abort_command(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(
        cli,
        "configure_tracing",
        lambda _service: (_ for _ in ()).throw(ValueError("SECRET_OTLP_HEADER_SENTINEL")),
    )
    monkeypatch.setattr(typer.Typer, "__call__", lambda *_args, **_kwargs: "completed")
    assert cli.ObservedTyper()() == "completed"
    assert "SECRET_OTLP_HEADER_SENTINEL" not in caplog.text
    assert "tracing_unavailable" in caplog.text


def test_real_literature_cli_stderr_suppresses_nested_validation_payload() -> None:
    script = """
from pydantic import BaseModel, ValidationError
from lyme_gap_atlas_data import cli
from lyme_gap_atlas_data.contribution_admission import ContributionAdmissionError
class Payload(BaseModel):
    value: int
def fail(**kwargs):
    try:
        Payload(value="SECRET_PROMPT_ARTICLE_SENTINEL")
    except ValidationError as error:
        raise ContributionAdmissionError("SECRET_RESPONSE_SENTINEL") from error
cli.run_pmc_extraction = fail
cli.app(args=["pipeline", "pmc-extract", "--estimated-cost-usd", "0.20", "--confirm"])
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 1
    assert "response_contract_validation" in result.stderr
    assert "SECRET_PROMPT_ARTICLE_SENTINEL" not in result.stderr + result.stdout
    assert "SECRET_RESPONSE_SENTINEL" not in result.stderr + result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("SECRET_COMMAND_SENTINEL"), KeyboardInterrupt(), SystemExit(7), SystemExit(0)],
)
def test_literature_cli_releases_root_before_children_on_exit(
    failure: BaseException, monkeypatch: pytest.MonkeyPatch
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(InvocationSpanProcessor(SimpleSpanProcessor(exporter)))
    tracer = provider.get_tracer("fixture")
    configured: list[str] = []
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "configure_literature_tracing", configured.append)
    monkeypatch.setattr(
        cli, "configure_tracing", lambda _service: pytest.fail("wrong tracing path")
    )
    monkeypatch.setattr(cli.trace, "get_tracer", lambda _service: tracer)
    monkeypatch.setattr(cli.trace, "get_tracer_provider", lambda: provider)

    def callback(*_args: object, **_kwargs: object) -> None:
        with tracer.start_as_current_span(
            "fixture.early_success", record_exception=False, set_status_on_exception=False
        ):
            pass
        assert exporter.get_finished_spans() == ()
        raise failure

    monkeypatch.setattr(typer.Typer, "__call__", callback)
    with pytest.raises(type(failure)):
        cli.ObservedTyper()(args=["pipeline", "pmc-extract", "--unused", "SECRET_OPTION_SENTINEL"])
    spans = exporter.get_finished_spans()
    assert [span.name for span in spans] == ["atlas-data.cli", "fixture.early_success"]
    assert configured == [cli.SERVICE_NAME]
    root, child = spans
    assert root.attributes is not None
    assert root.attributes["atlas.command"] == "pipeline.pmc-extract"
    assert root.context is not None and child.parent is not None
    assert child.parent.span_id == root.context.span_id
    assert root.attributes["atlas.trace_id"] == format(root.context.trace_id, "032x")
    failed = not isinstance(failure, SystemExit) or failure.code != 0
    assert root.status.status_code.name == ("ERROR" if failed else "UNSET")
    assert all(span.events == () for span in spans)
    assert "SECRET_COMMAND_SENTINEL" not in repr(spans)
    assert "SECRET_OPTION_SENTINEL" not in repr(root.attributes)


def test_literature_config_failure_remains_fail_open(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(cli, "configure_logging", lambda: None)

    def unavailable(_service: str) -> None:
        raise ValueError("SECRET_HEADER_SENTINEL")

    monkeypatch.setattr(cli, "configure_literature_tracing", unavailable)
    monkeypatch.setattr(typer.Typer, "__call__", lambda *_args, **_kwargs: "completed")
    assert cli.ObservedTyper()(args=["pipeline", "literature-preflight"]) == "completed"
    assert "tracing_unavailable" in caplog.text
    assert "SECRET_HEADER_SENTINEL" not in caplog.text


def test_real_sdk_invalid_header_is_rejected_before_exporter_and_cli_completes(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinel = "UNMISTAKABLY_FAKE_OTLP_AUTH_SENTINEL"
    malformed = f"{sentinel}\ninvalid"
    monkeypatch.setattr(logging.getLogger(OTLPSpanExporter.__module__), "filters", [])
    monkeypatch.setattr(
        requests.Session,
        "send",
        lambda *_args, **_kwargs: pytest.fail("network I/O is forbidden"),
    )
    # Exercise the locked, real SDK with one real span: requests preparation
    # rejects this header before send, but the SDK logs its credential-bearing reason.
    exporter = OTLPSpanExporter(
        endpoint="https://collector.invalid/v1/traces",
        headers={"authorization": malformed},
        timeout=0.1,
    )
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with provider.get_tracer("fixture").start_as_current_span("fixture.real_sdk_span"):
        pass
    provider.shutdown()
    assert sentinel in caplog.text
    caplog.clear()
    capsys.readouterr()

    # Use the real parsed-header/configuration path and the existing CLI catch.
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.invalid/v1/traces")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", f"authorization={malformed}")
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(typer.Typer, "__call__", lambda *_args, **_kwargs: "completed")
    assert cli.ObservedTyper()(args=["pipeline", "literature-preflight"]) == "completed"
    captured = capsys.readouterr()
    assert "tracing_unavailable" in caplog.text
    assert sentinel not in caplog.text + captured.out + captured.err
    assert all(record.exc_info is None for record in caplog.records)
