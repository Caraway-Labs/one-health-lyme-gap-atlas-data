"""Pilot budget seconds and deadline terminalization."""

from __future__ import annotations

import pytest

from lyme_gap_atlas_data import intelligence_daily_deadline as deadline
from lyme_gap_atlas_data.ingestion.intelligence_runtime import PilotBudget


def test_default_budget_raises_at_five_minutes() -> None:
    clock = [0.0]

    def tick() -> float:
        return clock[0]

    budget = PilotBudget(clock=tick, seconds=300)
    clock[0] = 301.0
    with pytest.raises(PermissionError, match="INTELLIGENCE_PILOT_DEADLINE"):
        budget.remaining()


def test_extended_budget_allows_work_past_default_cap() -> None:
    clock = [0.0]

    def tick() -> float:
        return clock[0]

    budget = PilotBudget(clock=tick, seconds=900)
    clock[0] = 301.0
    assert budget.remaining() > 0


def test_terminalize_daily_pilot_deadline_marks_run_failed(monkeypatch) -> None:
    from lyme_gap_atlas_data.ingestion.intelligence_runtime import PROD_DAILY_SOURCE_SHA256
    from lyme_gap_atlas_data.settings import PipelineSettings

    run_id = "76e241c4-815f-5c27-b97f-882be9c53903"
    source = "cdc-eid-expedited"

    class _Cursor:
        rowcount = 1
        executed: list[tuple[str, tuple | None]] = []

        def execute(self, sql: str, params=None) -> None:
            self.executed.append((sql, params))
            if "CURRENT_USER()" in sql:
                self._identity = [
                    (
                        "OH_LYME_PROD_PIPELINE_SVC",
                        "OH_LYME_PROD_RUNTIME",
                        "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
                        "OH_LYME_PROD_INGEST_XS_WH",
                    )
                ]
            elif "FROM GOVERNANCE.INGESTION_RUNS" in sql and "SELECT" in sql:
                self._run = (
                    source,
                    "RUNNING",
                    deadline.DAILY_CODE_VERSION,
                    PROD_DAILY_SOURCE_SHA256[source],
                )
            elif "INGESTION_RUN_CHECKPOINTS" in sql and "SELECT" in sql:
                self._checkpoints = [("LOAD", "RUNNING")]

        def fetchall(self) -> list[tuple]:
            if self.executed and "INGESTION_RUN_CHECKPOINTS" in self.executed[-1][0]:
                return self._checkpoints
            return self._identity

        def fetchone(self) -> tuple | None:
            if self.executed and "INGESTION_RUNS" in self.executed[-1][0]:
                return self._run
            return None

        def __enter__(self) -> _Cursor:
            return self

        def __exit__(self, *args) -> None:
            return None

    class _Connection:
        def cursor(self) -> _Cursor:
            return _Cursor()

        def autocommit(self, value: bool) -> None:
            return None

        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            return None

        def __enter__(self) -> _Connection:
            return self

        def __exit__(self, *args) -> None:
            return None

    monkeypatch.setattr(
        "lyme_gap_atlas_data.intelligence_daily_deadline.PipelineSettings",
        lambda: PipelineSettings(
            topx_env="prod",
            enable_production_execution=True,
            snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        ),
    )
    monkeypatch.setattr(deadline, "connect", lambda _settings: _Connection())
    result = deadline.terminalize_daily_pilot_deadline(run_id)
    assert result["status"] == "SUCCEEDED"
    assert result["terminalized_stages"] == ["LOAD"]
