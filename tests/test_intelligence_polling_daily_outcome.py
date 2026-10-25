"""Daily per-source outcomes expose an allowlisted code, stage and timings."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lyme_gap_atlas_data import intelligence_polling as polling
from lyme_gap_atlas_data.ingestion import intelligence_runtime as runtime
from lyme_gap_atlas_data.ingestion.types import RunStatus, Stage
from lyme_gap_atlas_data.settings import PipelineSettings

ROOT = Path(__file__).parents[1]


def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    value = PipelineSettings(
        topx_env="prod",
        enable_production_execution=True,
        snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        intelligence_daily_enabled=True,
    )
    monkeypatch.setattr("lyme_gap_atlas_data.settings.PipelineSettings", lambda: value)
    monkeypatch.setattr(polling, "_terminalize_claimed_daily_run", lambda run_id: None)
    monkeypatch.setattr(polling, "terminalize_daily_pilot_deadline", lambda run_id: None)


def _registry(source_id: str) -> dict[str, Any]:
    return json.loads((ROOT / f"config/intelligence/{source_id}-source-v2.json").read_text())


def _checkpoint(stage: str, status: str) -> SimpleNamespace:
    return SimpleNamespace(stage=SimpleNamespace(value=stage), status=SimpleNamespace(value=status))


def _install(
    monkeypatch: pytest.MonkeyPatch,
    claim: Any,
    run: Any,
) -> None:
    def compose(definition: Any, *, budget_seconds: int = 300) -> tuple[Any, Any]:
        source_id = definition.source_id
        budget = runtime.PilotBudget(seconds=budget_seconds)

        def claim_daily(*args: Any) -> Any:
            return claim(source_id, budget, *args)

        def run_source(*args: Any, **kwargs: Any) -> Any:
            return run(source_id, budget, *args, **kwargs)

        orchestrator = SimpleNamespace(
            store=SimpleNamespace(claim_daily_run=claim_daily),
            run=run_source,
            pilot_budget=budget,
        )
        return orchestrator, SimpleNamespace(extra={"intelligence_registry": _registry(source_id)})

    monkeypatch.setattr(runtime, "canonical_pilot", compose)


def _lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    captured = capsys.readouterr().out
    return [
        line for line in captured.splitlines() if line.startswith(polling.DAILY_OUTCOME_LOG_PREFIX)
    ]


def _payloads(lines: list[str]) -> list[dict[str, Any]]:
    prefix = polling.DAILY_OUTCOME_LOG_PREFIX
    return [json.loads(line.removeprefix(prefix)) for line in lines]


def test_known_governance_error_names_claim_stage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _settings(monkeypatch)

    def claim(source_id: str, budget: Any, *args: Any) -> bool:
        raise PermissionError("INTELLIGENCE_DAILY_REOPEN_PRIOR_TERMINAL_FAILED")

    def run(source_id: str, budget: Any, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("run must not start after a failed claim")

    _install(monkeypatch, claim, run)
    result = polling.run_production_daily()
    assert result["status"] == "FAILED"
    assert len(result["sources"]) == len(runtime.PROD_SOURCE_DEFINITIONS)
    for row in result["sources"]:
        assert row["status"] == "FAILED"
        assert row["outcome"] == "FAILED"
        assert row["error_code"] == "INTELLIGENCE_DAILY_REOPEN_PRIOR_TERMINAL_FAILED"
        assert row["failed_stage"] == "CLAIM"
        assert "CLAIM" in row["stage_timings_ms"]
    payloads = _payloads(_lines(capsys))
    assert len(payloads) == len(runtime.PROD_SOURCE_DEFINITIONS)
    assert {row["failed_stage"] for row in payloads} == {"CLAIM"}
    assert {row["error_code"] for row in payloads} == {
        "INTELLIGENCE_DAILY_REOPEN_PRIOR_TERMINAL_FAILED"
    }


def test_unknown_exception_code_omits_message_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _settings(monkeypatch)
    secret = "password=super-secret-value"

    def claim(source_id: str, budget: Any, *args: Any) -> bool:
        return True

    def run(source_id: str, budget: Any, *args: Any, **kwargs: Any) -> Any:
        if source_id == "cdc-mmwr":
            budget.observe_stages([_checkpoint("NORMALIZE", "RUNNING")])
            raise ValueError(secret)
        return SimpleNamespace(status=RunStatus.SUCCEEDED)

    _install(monkeypatch, claim, run)
    result = polling.run_production_daily()
    failed = next(row for row in result["sources"] if row["source_id"] == "cdc-mmwr")
    assert failed["status"] == "FAILED"
    assert failed["error_code"] == "UNCLASSIFIED_ValueError"
    assert failed["failed_stage"] == "NORMALIZE"
    rendered = json.dumps(result)
    assert secret not in rendered
    assert "super-secret" not in rendered
    lines = _lines(capsys)
    assert len(lines) == len(runtime.PROD_SOURCE_DEFINITIONS)
    logged = "\n".join(lines)
    assert secret not in logged
    assert "super-secret" not in logged
    payload = next(row for row in _payloads(lines) if row["source_id"] == "cdc-mmwr")
    assert payload["error_code"] == "UNCLASSIFIED_ValueError"
    assert payload["failed_stage"] == "NORMALIZE"
    assert all(len(line.encode("utf-8")) < 4096 for line in lines)


def test_allowlisted_code_with_trailing_text_is_not_published(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _settings(monkeypatch)
    secret = "INTELLIGENCE_DAILY_REOPEN_PRIOR_TERMINAL_FAILED password=sekret"

    def claim(source_id: str, budget: Any, *args: Any) -> bool:
        raise PermissionError(secret)

    def run(source_id: str, budget: Any, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("run must not start")

    _install(monkeypatch, claim, run)
    result = polling.run_production_daily()
    row = result["sources"][0]
    assert row["error_code"] == "UNCLASSIFIED_PermissionError"
    assert row["failed_stage"] == "CLAIM"
    assert secret not in json.dumps(result)
    assert "sekret" not in "\n".join(_lines(capsys))


def test_completed_outcome_records_stage_timings_ms(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _settings(monkeypatch)
    clocks: dict[str, list[float]] = {}

    def claim(source_id: str, budget: Any, *args: Any) -> bool:
        return True

    def run(source_id: str, budget: Any, *args: Any, **kwargs: Any) -> Any:
        clock = clocks[source_id]
        budget.observe_stages([_checkpoint("ACQUIRE", "RUNNING")])
        clock[0] = 1.5
        budget.observe_stages(
            [_checkpoint("ACQUIRE", "COMPLETED"), _checkpoint("VALIDATE", "RUNNING")]
        )
        clock[0] = 1.75
        budget.observe_stages(
            [_checkpoint("VALIDATE", "COMPLETED"), _checkpoint("NORMALIZE", "RUNNING")]
        )
        clock[0] = 2.0
        budget.observe_stages(
            [_checkpoint("NORMALIZE", "COMPLETED"), _checkpoint("LOAD", "RUNNING")]
        )
        clock[0] = 3.25
        budget.observe_stages(
            [_checkpoint("LOAD", "COMPLETED"), _checkpoint("PUBLISH_STAGE", "RUNNING")]
        )
        clock[0] = 3.5
        budget.observe_stages([_checkpoint("PUBLISH_STAGE", "COMPLETED")])
        return SimpleNamespace(status=RunStatus.SUCCEEDED)

    def compose(definition: Any, *, budget_seconds: int = 300) -> tuple[Any, Any]:
        source_id = definition.source_id
        clocks[source_id] = [0.0]
        budget = runtime.PilotBudget(clock=lambda: clocks[source_id][0], seconds=budget_seconds)
        orchestrator = SimpleNamespace(
            store=SimpleNamespace(claim_daily_run=lambda *args: claim(source_id, budget, *args)),
            run=lambda *args, **kwargs: run(source_id, budget, *args, **kwargs),
            pilot_budget=budget,
        )
        return orchestrator, SimpleNamespace(extra={"intelligence_registry": _registry(source_id)})

    monkeypatch.setattr(runtime, "canonical_pilot", compose)
    result = polling.run_production_daily()
    assert result["status"] == "SUCCEEDED"
    expected = {
        "FETCH": 1500,
        "PARSE": 250,
        "NORMALIZE": 250,
        "WRITE": 1250,
        "PUBLISH": 250,
    }
    for row in result["sources"]:
        assert row["status"] == "COMPLETED"
        assert row["outcome"] == "SUCCEEDED"
        assert row["failed_stage"] is None
        assert "error_code" not in row
        timings = row["stage_timings_ms"]
        assert isinstance(timings["CLAIM"], int)
        assert timings["CLAIM"] >= 0
        for stage, milliseconds in expected.items():
            assert timings[stage] == milliseconds
    payloads = _payloads(_lines(capsys))
    assert [row["source_id"] for row in payloads] == list(runtime.PROD_SOURCE_DEFINITIONS)
    for payload in payloads:
        assert payload["status"] == "COMPLETED"
        for stage in expected:
            assert payload["stage_timings_ms"][stage] == expected[stage]
        assert len(json.dumps(payload).encode("utf-8")) < 4096


def test_completed_outcome_line_reports_new_changed_and_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _settings(monkeypatch)

    def claim(source_id: str, budget: Any, *args: Any) -> bool:
        return True

    def run(source_id: str, budget: Any, *args: Any, **kwargs: Any) -> Any:
        detail = {
            "wrote": False,
            "items_seen": 3,
            "items_new": 1,
            "items_changed": 0,
            "items_unchanged": 2,
            "note": "password=not-for-the-log",
        }
        load = SimpleNamespace(detail=detail)
        return SimpleNamespace(
            status=RunStatus.SUCCEEDED,
            checkpoint=lambda stage: load if stage is Stage.LOAD else None,
        )

    _install(monkeypatch, claim, run)
    result = polling.run_production_daily()
    assert result["status"] == "SUCCEEDED"
    for row in result["sources"]:
        assert row["status"] == "COMPLETED"
        assert row["outcome"] == "SUCCEEDED"
        assert row["items_seen"] == 3
        assert row["items_new"] == 1
        assert row["items_changed"] == 0
        assert row["items_unchanged"] == 2
        assert "note" not in row
    payloads = _payloads(_lines(capsys))
    assert len(payloads) == len(result["sources"])
    for payload in payloads:
        assert payload["items_new"] + payload["items_changed"] + payload["items_unchanged"] == 3
        assert "password" not in json.dumps(payload)
    accepted = polling._accept_child_result(
        "cdc-mmwr",
        {
            "outcome": "SUCCEEDED",
            "items_seen": 3,
            "items_new": 0,
            "items_changed": 0,
            "items_unchanged": 3,
            "items_note": "password=dropped",
        },
    )
    assert accepted["status"] == "COMPLETED"
    assert accepted["items_unchanged"] == 3
    assert "items_note" not in accepted
    rejected = polling._accept_child_result(
        "cdc-mmwr",
        {
            "outcome": "SUCCEEDED",
            "items_seen": "3",
            "items_new": 0,
            "items_changed": 0,
            "items_unchanged": 3,
        },
    )
    assert "items_seen" not in rejected


def test_failed_checkpoint_publishes_code_without_free_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _settings(monkeypatch)
    secret = "password=checkpoint-secret"

    def claim(source_id: str, budget: Any, *args: Any) -> bool:
        return True

    def run(source_id: str, budget: Any, *args: Any, **kwargs: Any) -> Any:
        if source_id == "cdc-mmwr":
            return SimpleNamespace(
                status=RunStatus.FAILED,
                stages=[
                    SimpleNamespace(
                        stage=SimpleNamespace(value="ACQUIRE"),
                        status=SimpleNamespace(value="FAILED"),
                        redacted_diagnostic_code="MALFORMED_FEED",
                    )
                ],
            )
        if source_id == "cdc-outbreaks":
            return SimpleNamespace(
                status=RunStatus.FAILED,
                stages=[
                    SimpleNamespace(
                        stage=SimpleNamespace(value="NORMALIZE"),
                        status=SimpleNamespace(value="FAILED"),
                        redacted_diagnostic_code=secret,
                    )
                ],
            )
        return SimpleNamespace(status=RunStatus.SUCCEEDED)

    _install(monkeypatch, claim, run)
    result = polling.run_production_daily()
    by_id = {row["source_id"]: row for row in result["sources"]}
    assert by_id["cdc-mmwr"]["error_code"] == "MALFORMED_FEED"
    assert by_id["cdc-mmwr"]["failed_stage"] == "PARSE"
    assert by_id["cdc-outbreaks"]["error_code"] == "UNCLASSIFIED_EXCEPTION"
    assert by_id["cdc-outbreaks"]["failed_stage"] == "NORMALIZE"
    assert secret not in json.dumps(result)
    assert secret not in "\n".join(_lines(capsys))


@pytest.mark.parametrize(
    ("code", "open_stage", "failed_stage"),
    [
        ("MALFORMED_FEED", "ACQUIRE", "PARSE"),
        ("FEED_TIMEOUT", "ACQUIRE", "FETCH"),
        ("INTELLIGENCE_RAW_RETENTION_REQUIRED", "ACQUIRE", "RETENTION"),
    ],
)
def test_feed_failure_codes_keep_their_operator_stage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    code: str,
    open_stage: str,
    failed_stage: str,
) -> None:
    _settings(monkeypatch)

    def claim(source_id: str, budget: Any, *args: Any) -> bool:
        return True

    def run(source_id: str, budget: Any, *args: Any, **kwargs: Any) -> Any:
        budget.observe_stages([_checkpoint(open_stage, "RUNNING")])
        raise PermissionError(code)

    _install(monkeypatch, claim, run)
    result = polling.run_production_daily()
    for row in result["sources"]:
        assert row["status"] == "FAILED"
        assert row["error_code"] == code
        assert row["failed_stage"] == failed_stage
    assert {row["error_code"] for row in _payloads(_lines(capsys))} == {code}
