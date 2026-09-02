from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import typer

from lyme_gap_atlas_data import cli


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
    tracer = SimpleNamespace(start_span=lambda _name: span)
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
