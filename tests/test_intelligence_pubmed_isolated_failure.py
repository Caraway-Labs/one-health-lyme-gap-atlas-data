"""The parent FAILED save after a killed PubMed walk touches only RUNNING runs."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from lyme_gap_atlas_data import intelligence_polling as polling
from lyme_gap_atlas_data.ingestion.intelligence_checkpoints import (
    IntelligenceSnowflakeCheckpoints,
)
from lyme_gap_atlas_data.ingestion.intelligence_daily_run_ids import daily_run_id
from lyme_gap_atlas_data.ingestion.intelligence_entrez import SOURCE_ORDER

DAY = datetime.now(UTC).date().isoformat()
TICK, LYME = SOURCE_ORDER


class _Tables:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.checkpoints: dict[str, dict[str, Any]] = {}
        self.statements: list[str] = []


class _Cursor:
    def __init__(self, tables: _Tables) -> None:
        self.tables, self.rowcount = tables, 0

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        verb = sql.split()[0]
        self.tables.statements.append(verb)
        if verb == "UPDATE":
            assert "status='RUNNING'" in sql and "INSERT" not in sql
            row = self.tables.runs.get(params[0])
            self.rowcount = 0
            if row is not None and row["status"] == "RUNNING":
                row.update(status="FAILED", error_classification="PROCESS")
                self.rowcount = 1
        elif verb == "MERGE":
            checkpoint_id, run_id, code, _insert_code = params
            run = self.tables.runs.get(run_id)
            if run is None or run["status"] != "FAILED":
                return
            existing = self.tables.checkpoints.get(checkpoint_id)
            if existing is not None:
                existing.update(status="FAILED", failure_category="PROCESS", code=code)
            else:
                self.tables.checkpoints[checkpoint_id] = {
                    "status": "FAILED",
                    "failure_category": "PROCESS",
                    "code": code,
                    "detail": {},
                }
        else:
            raise AssertionError(f"unexpected statement {verb}")


class _Connection:
    def __init__(self, tables: _Tables) -> None:
        self.tables = tables

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def cursor(self) -> _Cursor:
        return _Cursor(self.tables)

    def autocommit(self, value: bool) -> None:
        return None

    def commit(self) -> None:
        self.tables.statements.append("COMMIT")

    def rollback(self) -> None:
        self.tables.statements.append("ROLLBACK")


@pytest.fixture
def tables(monkeypatch: pytest.MonkeyPatch) -> _Tables:
    tables = _Tables()
    store = object.__new__(IntelligenceSnowflakeCheckpoints)
    store.feed_retention = SimpleNamespace(environment="PROD")
    store._connection_factory = lambda: _Connection(tables)
    monkeypatch.setattr(polling, "open_entrez_daily_io", lambda settings: (None, store, None))
    monkeypatch.setattr(polling.pipeline_settings, "PipelineSettings", lambda: None)
    return tables


def _run(source_id: str) -> str:
    return daily_run_id(source_id, DAY, reopen_attempt=1)


def test_completed_run_keeps_status_and_load_checkpoint(tables: _Tables) -> None:
    detail = {"last_entry_date": {TICK: "2026-10-24"}, "sequence": 3}
    for source_id in SOURCE_ORDER:
        tables.runs[_run(source_id)] = {"status": "COMPLETED", "resource_key": source_id}
        tables.checkpoints[f"{_run(source_id)}:LOAD"] = {"status": "COMPLETED", "detail": detail}

    polling._record_isolated_pubmed_failure(DAY, 1)

    assert {row["status"] for row in tables.runs.values()} == {"COMPLETED"}
    for source_id in SOURCE_ORDER:
        assert tables.checkpoints[f"{_run(source_id)}:LOAD"] == {
            "status": "COMPLETED",
            "detail": detail,
        }
    assert "COMMIT" not in tables.statements and "MERGE" not in tables.statements


def test_unclaimed_runs_get_no_rows(tables: _Tables) -> None:
    polling._record_isolated_pubmed_failure(DAY, 1)

    assert tables.runs == {}
    assert tables.checkpoints == {}
    assert tables.statements == ["UPDATE", "ROLLBACK"] * len(SOURCE_ORDER)


def test_running_claimed_run_becomes_failed(tables: _Tables) -> None:
    tables.runs[_run(TICK)] = {"status": "RUNNING", "resource_key": TICK}

    polling._record_isolated_pubmed_failure(DAY, 1)

    assert tables.runs[_run(TICK)]["status"] == "FAILED"
    assert tables.checkpoints[f"{_run(TICK)}:LOAD"]["code"] == "PUBMED_DAILY_FAILED"
    assert _run(LYME) not in tables.runs
    assert f"{_run(LYME)}:LOAD" not in tables.checkpoints
