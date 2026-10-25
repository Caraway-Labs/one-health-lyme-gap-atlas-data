"""Recovery of one RUNNING intelligence-daily admission."""

from __future__ import annotations

import pytest

from lyme_gap_atlas_data import intelligence_daily_run_recovery as recovery
from lyme_gap_atlas_data.ingestion.intelligence_runtime import PROD_DAILY_SOURCE_SHA256
from lyme_gap_atlas_data.settings import PipelineSettings

RUN_ID = "76e241c4-815f-5c27-b97f-882be9c53903"
SOURCE = "cdc-eid-expedited"


class _Cursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple | None]] = []
        self._queue: list[list[tuple]] = []
        self.rowcount = 0

    def execute(self, sql: str, params=None) -> None:
        self.executed.append((sql, params))
        if "CURRENT_USER()" in sql:
            self._queue.append(
                [
                    (
                        "OH_LYME_PROD_PIPELINE_SVC",
                        "OH_LYME_PROD_RUNTIME",
                        "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
                        "OH_LYME_PROD_INGEST_XS_WH",
                    )
                ]
            )
        elif "FROM GOVERNANCE.INGESTION_RUNS" in sql:
            self._queue.append(
                [
                    (
                        SOURCE,
                        "RUNNING",
                        recovery.DAILY_CODE_VERSION,
                        PROD_DAILY_SOURCE_SHA256[SOURCE],
                    )
                ]
            )
        elif "INGESTION_RUN_CHECKPOINTS" in sql and "SELECT" in sql:
            self._queue.append([("NORMALIZE", "RUNNING")])
        elif ("INGESTION_RUN_CHECKPOINTS" in sql or "INGESTION_RUNS" in sql) and "UPDATE" in sql:
            self.rowcount = 1

    def fetchall(self) -> list[tuple]:
        return self._queue.pop(0)

    def fetchone(self) -> tuple | None:
        rows = self.fetchall()
        return rows[0] if rows else None

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args) -> None:
        return None


class _Connection:
    def __init__(self) -> None:
        self.autocommit_mode = True

    def cursor(self) -> _Cursor:
        return _Cursor()

    def autocommit(self, value: bool) -> None:
        self.autocommit_mode = value

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *args) -> None:
        return None


def test_terminalize_stuck_daily_run(monkeypatch) -> None:
    monkeypatch.setattr(
        "lyme_gap_atlas_data.intelligence_daily_run_recovery.PipelineSettings",
        lambda: PipelineSettings(
            topx_env="prod",
            enable_production_execution=True,
            snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        ),
    )
    monkeypatch.setattr(recovery, "connect", lambda _settings: _Connection())
    result = recovery.terminalize_stuck_daily_run(RUN_ID, source_id=SOURCE)
    assert result["status"] == "SUCCEEDED"
    assert result["resource_key"] == SOURCE
    assert result["terminalized_stages"] == ["NORMALIZE"]


def test_terminalize_rejects_non_running(monkeypatch) -> None:
    monkeypatch.setattr(
        "lyme_gap_atlas_data.intelligence_daily_run_recovery.PipelineSettings",
        lambda: PipelineSettings(
            topx_env="prod",
            enable_production_execution=True,
            snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        ),
    )

    class _BadCursor(_Cursor):
        def execute(self, sql: str, params=None) -> None:
            super().execute(sql, params)
            if "FROM GOVERNANCE.INGESTION_RUNS" in sql and "SELECT" in sql:
                self._queue[-1] = [(SOURCE, "FAILED", recovery.DAILY_CODE_VERSION, "sha")]

    class _BadConnection(_Connection):
        def cursor(self) -> _BadCursor:
            return _BadCursor()

    monkeypatch.setattr(recovery, "connect", lambda _settings: _BadConnection())
    with pytest.raises(PermissionError, match="RECOVERY_SCOPE"):
        recovery.terminalize_stuck_daily_run(RUN_ID, source_id=SOURCE)


def test_terminalize_run_without_running_checkpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        "lyme_gap_atlas_data.intelligence_daily_run_recovery.PipelineSettings",
        lambda: PipelineSettings(
            topx_env="prod",
            enable_production_execution=True,
            snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        ),
    )

    class _NoRunningCursor(_Cursor):
        def execute(self, sql: str, params=None) -> None:
            super().execute(sql, params)
            if "INGESTION_RUN_CHECKPOINTS" in sql and "SELECT" in sql:
                self._queue[-1] = [("NORMALIZE", "COMPLETED"), ("LOAD", "PENDING")]

    class _NoRunningConnection(_Connection):
        def cursor(self) -> _NoRunningCursor:
            return _NoRunningCursor()

    monkeypatch.setattr(recovery, "connect", lambda _settings: _NoRunningConnection())
    result = recovery.terminalize_stuck_daily_run(RUN_ID, source_id=SOURCE)
    assert result["status"] == "SUCCEEDED"
    assert result["terminalized_stages"] == []


def test_terminalize_rejects_unknown_source_before_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recovery, "connect", lambda *_args, **_kwargs: pytest.fail("snowflake"))
    with pytest.raises(PermissionError, match="SOURCE_SELECTION_INVALID"):
        recovery.terminalize_stuck_daily_run(RUN_ID, source_id="all")


def test_terminalize_rejects_resource_key_mismatch_before_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "lyme_gap_atlas_data.intelligence_daily_run_recovery.PipelineSettings",
        lambda: PipelineSettings(
            topx_env="prod",
            enable_production_execution=True,
            snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        ),
    )
    statements: list[str] = []

    class _MismatchCursor(_Cursor):
        def execute(self, sql: str, params=None) -> None:
            statements.append(sql)
            super().execute(sql, params)
            if "FROM GOVERNANCE.INGESTION_RUNS" in sql and "SELECT" in sql:
                self._queue[-1] = [
                    (
                        "cdc-mmwr",
                        "RUNNING",
                        recovery.DAILY_CODE_VERSION,
                        PROD_DAILY_SOURCE_SHA256["cdc-mmwr"],
                    )
                ]

    class _MismatchConnection(_Connection):
        def cursor(self) -> _MismatchCursor:
            return _MismatchCursor()

    monkeypatch.setattr(recovery, "connect", lambda _settings: _MismatchConnection())
    with pytest.raises(PermissionError, match="RECOVERY_SOURCE_MISMATCH"):
        recovery.terminalize_stuck_daily_run(RUN_ID, source_id=SOURCE)
    assert statements
    assert not any("UPDATE" in sql for sql in statements)
