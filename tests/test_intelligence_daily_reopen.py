"""Governed same-day reopen guards, deadline terminalization wiring and stage timing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from lyme_gap_atlas_data import intelligence_polling as polling
from lyme_gap_atlas_data.cli import app
from lyme_gap_atlas_data.ingestion import intelligence_runtime as runtime
from lyme_gap_atlas_data.ingestion.intelligence_checkpoints import (
    IntelligenceSnowflakeCheckpoints,
)
from lyme_gap_atlas_data.ingestion.intelligence_daily_run_ids import (
    daily_run_id,
    prior_daily_run_id,
    reopen_attempt_for_run_id,
)
from lyme_gap_atlas_data.ingestion.types import RunStatus
from lyme_gap_atlas_data.settings import PipelineSettings

ROOT = Path(__file__).parents[1]


@pytest.fixture(autouse=True)
def _rss_daily_does_not_open_pubmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(polling, "_isolate_pubmed_walk", lambda *args, **kwargs: [])


SID = "cdc-eid-expedited"
SHA = runtime.PROD_DAILY_SOURCE_SHA256[SID]
TODAY = datetime.now(UTC).date()
CODE = "intelligence-daily-v1"


def test_run_ids_are_stable_distinct_and_chain_to_prior_attempt() -> None:
    base = daily_run_id(SID, TODAY)
    two = daily_run_id(SID, TODAY, reopen_attempt=2)
    three = daily_run_id(SID, TODAY, reopen_attempt=3)
    assert len({base, two, three}) == 3
    assert prior_daily_run_id(SID, TODAY, 2) == base
    assert prior_daily_run_id(SID, TODAY, 3) == two
    assert reopen_attempt_for_run_id(SID, TODAY, two) == 2
    assert reopen_attempt_for_run_id(SID, TODAY, "x" * 36) is None
    with pytest.raises(ValueError):
        daily_run_id(SID, TODAY, reopen_attempt=0)


class _Cursor:
    def __init__(self, ledger: dict[str, tuple], events: list[Any]) -> None:
        self.ledger, self.events, self.rowcount, self._rows = ledger, events, 1, []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.events.append(sql.split()[0])
        if sql.startswith("SELECT status"):
            row = self.ledger.get(params[0])
            self._rows = [row] if row else []
        elif sql.startswith("SELECT ingestion_run_id"):
            self._rows = [("x",)] if params[0] in self.ledger else []

    def fetchone(self) -> tuple | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple]:
        return self._rows


class _Connection:
    def __init__(self, ledger: dict[str, tuple], events: list[Any]) -> None:
        self.ledger, self.events = ledger, events

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def cursor(self) -> _Cursor:
        return _Cursor(self.ledger, self.events)

    def autocommit(self, value: bool) -> None:
        return None

    def commit(self) -> None:
        self.events.append("COMMIT")

    def rollback(self) -> None:
        self.events.append("ROLLBACK")


def _store(ledger: dict[str, tuple], events: list[Any]) -> IntelligenceSnowflakeCheckpoints:
    store = object.__new__(IntelligenceSnowflakeCheckpoints)
    store.feed_retention = SimpleNamespace(environment="PROD")
    store._connection_factory = lambda: _Connection(ledger, events)
    return store


def _prior(status: str, sha: str = SHA, source: str = SID) -> tuple:
    return (status, source, CODE, sha)


def test_reopen_allowed_only_after_prior_attempt_failed(monkeypatch) -> None:
    monkeypatch.setenv("INTELLIGENCE_DAILY_REOPEN", "true")
    base, two = daily_run_id(SID, TODAY), daily_run_id(SID, TODAY, reopen_attempt=2)
    events: list[Any] = []
    assert _store({base: _prior("FAILED")}, events).claim_daily_run(two, SID, SHA) is True
    assert "INSERT" in events and events[-1] == "COMMIT"


@pytest.mark.parametrize(
    "ledger_prior",
    [
        _prior("RUNNING"),
        _prior("SUCCEEDED"),
        _prior("COMPLETED"),
        _prior("FAILED", sha="0" * 64),
        _prior("FAILED", source="cdc-outbreaks"),
        None,
    ],
)
def test_reopen_denied_unless_prior_is_terminal_failed_for_same_source(
    monkeypatch, ledger_prior
) -> None:
    monkeypatch.setenv("INTELLIGENCE_DAILY_REOPEN", "true")
    base, two = daily_run_id(SID, TODAY), daily_run_id(SID, TODAY, reopen_attempt=2)
    ledger = {} if ledger_prior is None else {base: ledger_prior}
    events: list[Any] = []
    with pytest.raises(PermissionError, match="REOPEN_PRIOR_TERMINAL_FAILED"):
        _store(ledger, events).claim_daily_run(two, SID, SHA)
    assert "INSERT" not in events and "COMMIT" not in events
    assert events[-1] == "ROLLBACK"
    assert ledger == ({} if ledger_prior is None else {base: ledger_prior})  # never rewritten


def test_reopen_denied_without_manual_job_env_before_any_sql(monkeypatch) -> None:
    monkeypatch.delenv("INTELLIGENCE_DAILY_REOPEN", raising=False)
    store = _store({}, [])
    store._connection_factory = lambda: pytest.fail("no SQL before the env guard")
    with pytest.raises(PermissionError, match="REOPEN_REQUIRED"):
        store.claim_daily_run(daily_run_id(SID, TODAY, reopen_attempt=2), SID, SHA)


def test_existing_attempt_row_is_not_claimed_twice(monkeypatch) -> None:
    monkeypatch.setenv("INTELLIGENCE_DAILY_REOPEN", "true")
    base, two = daily_run_id(SID, TODAY), daily_run_id(SID, TODAY, reopen_attempt=2)
    events: list[Any] = []
    ledger = {base: _prior("FAILED"), two: _prior("RUNNING")}
    assert _store(ledger, events).claim_daily_run(two, SID, SHA) is False
    assert "INSERT" not in events


def test_scheduled_base_claim_never_needs_or_reads_reopen_env(monkeypatch) -> None:
    monkeypatch.setenv("INTELLIGENCE_DAILY_REOPEN", "true")
    base = daily_run_id(SID, TODAY)
    events: list[Any] = []
    # Even with the env set, the base id is a plain claim: an existing FAILED row blocks it.
    assert _store({base: _prior("FAILED")}, events).claim_daily_run(base, SID, SHA) is False
    assert "INSERT" not in events


def test_claim_rejects_wrong_day_attempt_and_wrong_sha(monkeypatch) -> None:
    monkeypatch.setenv("INTELLIGENCE_DAILY_REOPEN", "true")
    store = _store({}, [])
    store._connection_factory = lambda: pytest.fail("no SQL on scope failure")
    stale = daily_run_id(SID, "2000-01-01", reopen_attempt=2)
    with pytest.raises(PermissionError, match="CLAIM_SCOPE"):
        store.claim_daily_run(stale, SID, SHA)
    with pytest.raises(PermissionError, match="CLAIM_SCOPE"):
        store.claim_daily_run(daily_run_id(SID, TODAY, reopen_attempt=2), SID, "0" * 64)


def _settings(monkeypatch) -> None:
    value = PipelineSettings(
        topx_env="prod",
        enable_production_execution=True,
        snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        intelligence_daily_enabled=True,
    )
    monkeypatch.setattr("lyme_gap_atlas_data.settings.PipelineSettings", lambda: value)


def test_cli_reopen_flag_requires_manual_job_env(monkeypatch) -> None:
    _settings(monkeypatch)
    monkeypatch.delenv("INTELLIGENCE_DAILY_REOPEN", raising=False)
    monkeypatch.setattr(runtime, "canonical_pilot", lambda *a, **k: pytest.fail("no compose"))
    with pytest.raises(PermissionError, match="REOPEN_REQUIRED"):
        polling.run_production_daily(reopen_attempt=2, source_ids=("cdc-mmwr",))


def _compose_recording(monkeypatch, run_ids: list[str], failing: Any = None):
    def compose(definition, *, budget_seconds=300):
        sid = definition.source_id
        source = json.loads((ROOT / f"config/intelligence/{sid}-source-v2.json").read_text())

        def run(_definition, *, tier, run_id):
            run_ids.append(run_id)
            if sid == failing:
                raise PermissionError("INTELLIGENCE_PILOT_DEADLINE")
            return SimpleNamespace(status=RunStatus.SUCCEEDED)

        orchestrator = SimpleNamespace(
            store=SimpleNamespace(claim_daily_run=lambda *args: True),
            run=run,
            pilot_budget=runtime.PilotBudget(seconds=budget_seconds),
        )
        return orchestrator, SimpleNamespace(source_id=sid, extra={"intelligence_registry": source})

    monkeypatch.setattr(runtime, "canonical_pilot", compose)


def test_reopen_attempt_uses_suffixed_run_id_with_env(monkeypatch) -> None:
    _settings(monkeypatch)
    monkeypatch.setenv("INTELLIGENCE_DAILY_REOPEN", "true")
    seen: list[str] = []
    _compose_recording(monkeypatch, seen)
    result = polling.run_production_daily(
        reopen_attempt=2,
        source_ids=tuple(runtime.PROD_SOURCE_DEFINITIONS),
    )
    assert result["reopen_attempt"] == 2 and result["status"] == "SUCCEEDED"
    assert seen == [
        daily_run_id(source, TODAY, reopen_attempt=2) for source in runtime.PROD_SOURCE_DEFINITIONS
    ]


def test_default_invocation_uses_base_run_id_and_ignores_reopen_env(monkeypatch) -> None:
    _settings(monkeypatch)
    monkeypatch.setenv("INTELLIGENCE_DAILY_REOPEN", "true")
    seen: list[str] = []
    _compose_recording(monkeypatch, seen)
    polling.run_production_daily()
    assert seen == [daily_run_id(source, TODAY) for source in runtime.PROD_SOURCE_DEFINITIONS]


def test_deadline_terminalizes_run_failed_and_reports_stage_timings(monkeypatch) -> None:
    _settings(monkeypatch)
    terminalized: list[str] = []
    monkeypatch.setattr(polling, "terminalize_daily_pilot_deadline", terminalized.append)
    seen: list[str] = []
    _compose_recording(monkeypatch, seen, failing="cdc-eid-ahead-of-print")
    result = polling.run_production_daily()
    assert [row["outcome"] for row in result["sources"]] == [
        "FAILED" if source_id == "cdc-eid-ahead-of-print" else "SUCCEEDED"
        for source_id in runtime.PROD_SOURCE_DEFINITIONS
    ]
    assert result["status"] == "FAILED"
    assert terminalized == [daily_run_id("cdc-eid-ahead-of-print", TODAY)]
    assert all("stage_timings" in row for row in result["sources"])


def test_budget_records_redacted_stage_timing_including_unfinished() -> None:
    clock = [0.0]
    budget = runtime.PilotBudget(clock=lambda: clock[0], seconds=900)

    def stages(*pairs: tuple[str, str]) -> list[Any]:
        return [
            SimpleNamespace(stage=SimpleNamespace(value=n), status=SimpleNamespace(value=s))
            for n, s in pairs
        ]

    budget.observe_stages(stages(("ACQUIRE", "RUNNING")))
    clock[0], budget.queries = 12.5, 7
    budget.observe_stages(stages(("ACQUIRE", "COMPLETED"), ("LOAD", "RUNNING")))
    clock[0], budget.queries = 20.0, 11
    assert budget.timing_report() == [
        {"stage": "ACQUIRE", "status": "COMPLETED", "seconds": 12.5, "queries": 7},
        {"stage": "LOAD", "status": "UNFINISHED", "seconds": 7.5, "queries": 4},
    ]


def test_scheduled_spec_has_no_reopen_and_workflow_exposes_reopen_input() -> None:
    deploy = (ROOT / "scripts/deploy_intelligence_daily.py").read_text()
    assert "INTELLIGENCE_DAILY_REOPEN" not in deploy
    assert "reopen-attempt" not in deploy
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/run-prod-intelligence-daily-once.yml").read_text()
    )
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    assert "reopen_attempt" in inputs
    assert "source_id" in inputs
    build = next(
        step["run"]
        for step in workflow["jobs"]["run"]["steps"]
        if step.get("name") == "Capture baseline and build one-shot spec"
    )
    assert "INTELLIGENCE_DAILY_REOPEN_SOURCE_REQUIRED" in build
    assert '"all"' in build
    scheduled = (ROOT / ".github/workflows/promote-prod.yml").read_text()
    assert "INTELLIGENCE_DAILY_REOPEN" not in scheduled


def _registry(source_id: str) -> dict[str, Any]:
    return json.loads((ROOT / f"config/intelligence/{source_id}-source-v2.json").read_text())


def test_reopen_without_source_exits_before_snowflake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        polling, "execute_daily_source", lambda *_args, **_kwargs: pytest.fail("executed")
    )
    monkeypatch.setattr(
        "lyme_gap_atlas_data.sql_sessions.connect",
        lambda *_args, **_kwargs: pytest.fail("snowflake"),
    )
    monkeypatch.setattr(
        "lyme_gap_atlas_data.settings.PipelineSettings",
        lambda: pytest.fail("settings"),
    )
    result = CliRunner().invoke(
        app,
        ["pipeline", "run-intelligence-daily", "--reopen-attempt", "2"],
    )
    assert result.exit_code == 2
    assert result.stdout.strip() == "INTELLIGENCE_DAILY_REOPEN_SOURCE_REQUIRED"


def test_reopen_rejects_unknown_all_and_duplicates_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTELLIGENCE_DAILY_REOPEN", "true")
    monkeypatch.setattr(
        polling, "execute_daily_source", lambda *_args, **_kwargs: pytest.fail("executed")
    )
    for source_ids in (("all",), ("cdc-mmwr", "not-a-source"), ("cdc-mmwr", "cdc-mmwr")):
        with pytest.raises(PermissionError, match="SOURCE_SELECTION_INVALID"):
            polling.run_production_daily(reopen_attempt=2, source_ids=source_ids)


def test_reopen_one_source_claims_only_that_source_and_skips_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings(monkeypatch)
    monkeypatch.setenv("INTELLIGENCE_DAILY_REOPEN", "true")
    claimed: list[str] = []

    def compose(definition: Any, *, budget_seconds: int = 300) -> tuple[Any, Any]:
        source_id = definition.source_id

        def claim(run_id: str, claimed_source: str, sha: str) -> bool:
            assert claimed_source == source_id
            assert sha == runtime.PROD_DAILY_SOURCE_SHA256[source_id]
            assert run_id == daily_run_id(source_id, TODAY, reopen_attempt=2)
            claimed.append(source_id)
            return True

        def run(_definition: Any, *, tier: Any, run_id: str) -> Any:
            assert run_id == daily_run_id(source_id, TODAY, reopen_attempt=2)
            return SimpleNamespace(status=RunStatus.SUCCEEDED)

        orchestrator = SimpleNamespace(
            store=SimpleNamespace(claim_daily_run=claim),
            run=run,
            pilot_budget=runtime.PilotBudget(seconds=budget_seconds),
        )
        return orchestrator, SimpleNamespace(extra={"intelligence_registry": _registry(source_id)})

    monkeypatch.setattr(runtime, "canonical_pilot", compose)
    result = CliRunner().invoke(
        app,
        [
            "pipeline",
            "run-intelligence-daily",
            "--reopen-attempt",
            "2",
            "--source",
            "cdc-mmwr",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["status"] == "SUCCEEDED"
    by_id = {row["source_id"]: row for row in payload["sources"]}
    assert claimed == ["cdc-mmwr"]
    assert by_id["cdc-mmwr"]["outcome"] == "SUCCEEDED"
    assert by_id["cdc-mmwr"]["status"] == "COMPLETED"
    skipped = [
        source_id for source_id in runtime.PROD_SOURCE_DEFINITIONS if source_id != "cdc-mmwr"
    ]
    assert skipped
    assert all(by_id[source_id]["outcome"] == "SKIPPED_NOT_SELECTED" for source_id in skipped)


def test_same_reopen_second_time_fails_on_existing_claim_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings(monkeypatch)
    monkeypatch.setenv("INTELLIGENCE_DAILY_REOPEN", "true")
    seen: list[str] = []
    runs: list[str] = []

    def compose(definition: Any, *, budget_seconds: int = 300) -> tuple[Any, Any]:
        source_id = definition.source_id

        def claim(run_id: str, _source_id: str, _sha: str) -> bool:
            if run_id in seen:
                return False
            seen.append(run_id)
            return True

        def run(_definition: Any, *, tier: Any, run_id: str) -> Any:
            runs.append(run_id)
            return SimpleNamespace(status=RunStatus.SUCCEEDED)

        orchestrator = SimpleNamespace(
            store=SimpleNamespace(claim_daily_run=claim),
            run=run,
            pilot_budget=runtime.PilotBudget(seconds=budget_seconds),
        )
        return orchestrator, SimpleNamespace(extra={"intelligence_registry": _registry(source_id)})

    monkeypatch.setattr(runtime, "canonical_pilot", compose)
    arguments = [
        "pipeline",
        "run-intelligence-daily",
        "--reopen-attempt",
        "2",
        "--source",
        "cdc-mmwr",
    ]
    first = CliRunner().invoke(app, arguments)
    second = CliRunner().invoke(app, arguments)
    assert first.exit_code == 0
    assert len(runs) == 1
    assert second.exit_code == 1
    payload = json.loads(second.stdout.strip().splitlines()[-1])
    assert payload["status"] == "FAILED"
    mmwr = next(row for row in payload["sources"] if row["source_id"] == "cdc-mmwr")
    assert mmwr["outcome"] == "ALREADY_CLAIMED"
    assert len(runs) == 1
    others = [row for row in payload["sources"] if row["source_id"] != "cdc-mmwr"]
    assert others
    assert all(row["outcome"] == "SKIPPED_NOT_SELECTED" for row in others)
