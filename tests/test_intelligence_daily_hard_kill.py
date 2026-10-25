"""Hard-kill ledger write, stage/memory log, and per-source process isolation."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lyme_gap_atlas_data import intelligence_daily_hard_kill as hard_kill
from lyme_gap_atlas_data import intelligence_polling as polling
from lyme_gap_atlas_data.ingestion.intelligence_daily_run_ids import daily_run_id
from lyme_gap_atlas_data.ingestion.intelligence_runtime import (
    PROD_DAILY_SOURCE_SHA256,
    PROD_SOURCE_DEFINITIONS,
)
from lyme_gap_atlas_data.settings import PipelineSettings

ROOT = Path(__file__).parents[1]
RUN_ID = "76e241c4-815f-5c27-b97f-882be9c53903"
SOURCE = "cdc-mmwr"
_PRODUCTION_EXECUTE = polling.execute_daily_source


def _prod_settings() -> PipelineSettings:
    return PipelineSettings(
        topx_env="prod",
        enable_production_execution=True,
        snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
    )


class _Cursor:
    def __init__(self, *, checkpoints: list[tuple[str, str]] | None = None) -> None:
        self.executed: list[tuple[str, tuple | None]] = []
        self._queue: list[list[tuple]] = []
        self.rowcount = 0
        self._checkpoints = checkpoints if checkpoints is not None else [("NORMALIZE", "RUNNING")]

    def execute(self, sql: str, params: tuple | None = None) -> None:
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
                        hard_kill.DAILY_CODE_VERSION,
                        PROD_DAILY_SOURCE_SHA256[SOURCE],
                    )
                ]
            )
        elif "INGESTION_RUN_CHECKPOINTS" in sql and "SELECT" in sql:
            self._queue.append(list(self._checkpoints))
        elif ("INGESTION_RUN_CHECKPOINTS" in sql or "INGESTION_RUNS" in sql) and "UPDATE" in sql:
            self.rowcount = 1

    def fetchall(self) -> list[tuple]:
        return self._queue.pop(0)

    def fetchone(self) -> tuple | None:
        rows = self.fetchall()
        return rows[0] if rows else None

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _Connection:
    def __init__(self, cursor: _Cursor | None = None) -> None:
        self.cursor_obj = cursor or _Cursor()
        self.committed = False
        self.worker_marker = False

    def cursor(self) -> _Cursor:
        return self.cursor_obj

    def autocommit(self, value: bool) -> None:
        return None

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        return None

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _patch_prod(monkeypatch: pytest.MonkeyPatch, connection: _Connection) -> None:
    monkeypatch.setattr(hard_kill, "PipelineSettings", lambda: _prod_settings())
    monkeypatch.setattr(hard_kill, "connect", lambda _settings: connection)


def test_terminalize_uses_fresh_connection_and_records_failed_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _Connection()
    worker.worker_marker = True
    fresh = _Connection()
    seen: list[object] = []

    def connect(_settings: object) -> _Connection:
        seen.append(_settings)
        assert _settings is not worker
        return fresh

    monkeypatch.setattr(hard_kill, "PipelineSettings", lambda: _prod_settings())
    monkeypatch.setattr(hard_kill, "connect", connect)
    result = hard_kill.terminalize_hard_killed_run(RUN_ID, "NORMALIZE")
    assert result["status"] == "SUCCEEDED"
    assert result["stage"] == "NORMALIZE"
    assert result["terminalized_stages"] == ["NORMALIZE"]
    assert fresh.committed is True
    assert worker.committed is False
    assert len(seen) == 1
    statements = [sql for sql, _params in fresh.cursor_obj.executed]
    assert any("STATEMENT_TIMEOUT_IN_SECONDS" in sql for sql in statements)
    assert any("STATEMENT_QUEUED_TIMEOUT_IN_SECONDS" in sql for sql in statements)
    run_update = [
        params
        for sql, params in fresh.cursor_obj.executed
        if "UPDATE GOVERNANCE.INGESTION_RUNS" in sql
    ]
    assert run_update == [
        (
            hard_kill.ERROR_CLASS,
            "Daily source hard-killed during NORMALIZE.",
            RUN_ID,
        )
    ]
    checkpoint_update = [
        params
        for sql, params in fresh.cursor_obj.executed
        if "UPDATE GOVERNANCE.INGESTION_RUN_CHECKPOINTS" in sql
    ]
    assert checkpoint_update == [("PROCESS", hard_kill.DIAGNOSTIC, RUN_ID)]


def test_terminalize_rejects_free_text_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    fresh = _Connection()
    _patch_prod(monkeypatch, fresh)
    hard_kill.terminalize_hard_killed_run(RUN_ID, "NORMALIZE; password=secret")
    run_update = [
        params
        for sql, params in fresh.cursor_obj.executed
        if "UPDATE GOVERNANCE.INGESTION_RUNS" in sql
    ]
    assert run_update[0][1] == "Daily source hard-killed during UNKNOWN."
    assert "password" not in str(fresh.cursor_obj.executed)


def test_stage_is_remembered_before_a_wedged_checkpoint_write() -> None:
    state = hard_kill.HardKillState()

    class Store:
        def save(self, run: object) -> None:
            raise TimeoutError("wedged checkpoint write")

    store = Store()
    hard_kill.install_stage_memory(store, state)
    run = SimpleNamespace(
        ingestion_run_id=RUN_ID,
        stages=[
            SimpleNamespace(
                stage=SimpleNamespace(value="NORMALIZE"),
                status=SimpleNamespace(value="RUNNING"),
            )
        ],
    )
    with pytest.raises(TimeoutError, match="wedged"):
        store.save(run)
    assert state.current_stage() == "NORMALIZE"
    assert state.run_id == RUN_ID


def test_hard_kill_log_keeps_only_allowlisted_fields() -> None:
    line = hard_kill.format_hard_kill_log(
        stage="LOAD\nrss_kib=1 token=abc",
        rss=-1,
        peak=2048,
        ledger="recorded",
        run_id=RUN_ID,
    )
    assert line == (
        "intelligence_daily_hard_kill "
        f"stage=UNKNOWN rss_kib=unknown peak_rss_kib=2048 ledger=recorded run_id={RUN_ID}"
    )
    assert "token" not in line


def test_memory_parser_reads_rss_and_peak() -> None:
    text = "Name:\tpython\nVmRSS:\t   12345 kB\nVmHWM:\t   23456 kB\n"
    assert hard_kill.read_process_memory_kib(text) == (12345, 23456)


def _finish(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stage: str,
    terminalize: Any,
    ledger_timeout: float = 1,
) -> tuple[list[int], list[str]]:
    monkeypatch.setattr(hard_kill, "terminalize_hard_killed_run", terminalize)
    exits: list[int] = []
    lines: list[str] = []
    state = hard_kill.HardKillState()
    state.run_id = RUN_ID
    state.stage = stage
    hard_kill.finish_hard_kill(
        state,
        ledger_timeout=ledger_timeout,
        exit_fn=exits.append,
        memory_fn=lambda: (111, 222),
        writer=lines.append,
    )
    return exits, lines


def test_timer_path_records_failed_then_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def terminalize(run_id: str, stage: str) -> dict[str, str]:
        calls.append((run_id, stage))
        return {"status": "SUCCEEDED"}

    exits, lines = _finish(monkeypatch, stage="NORMALIZE", terminalize=terminalize)
    assert calls == [(RUN_ID, "NORMALIZE")]
    assert exits == [124]
    assert any(
        "stage=NORMALIZE" in line and "rss_kib=111" in line and "peak_rss_kib=222" in line
        for line in lines
    )
    assert any("ledger=recorded" in line for line in lines)


def test_failed_ledger_write_still_exits_and_hides_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def terminalize(run_id: str, stage: str) -> None:
        raise RuntimeError("password=hunter2 token=abc sql=SELECT SECRET")

    exits, lines = _finish(monkeypatch, stage="LOAD", terminalize=terminalize)
    assert exits == [124]
    blob = "\n".join(lines)
    assert "ledger=failed" in blob
    assert "stage=LOAD" in blob
    assert "rss_kib=111" in blob
    for secret in ("hunter2", "password", "token", "SELECT", "SECRET"):
        assert secret not in blob


def test_ledger_timeout_still_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    def terminalize(run_id: str, stage: str) -> None:
        time.sleep(5)

    started = time.monotonic()
    exits, lines = _finish(
        monkeypatch, stage="ACQUIRE", terminalize=terminalize, ledger_timeout=0.2
    )
    assert time.monotonic() - started < 1.5
    assert exits == [124]
    assert any("ledger=timed_out" in line and "stage=ACQUIRE" in line for line in lines)
    assert any("rss_kib=111" in line and "peak_rss_kib=222" in line for line in lines)


def test_watchdog_cancels_when_the_source_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[str] = []

    class Timer:
        def __init__(self, seconds: int, callback: Any) -> None:
            assert seconds == 960
            assert callable(callback)
            self.daemon = False

        def start(self) -> None:
            assert self.daemon
            observed.append("start")

        def cancel(self) -> None:
            observed.append("cancel")

    monkeypatch.setattr(hard_kill.threading, "Timer", Timer)
    state = hard_kill.HardKillState()
    with hard_kill.daily_hard_kill_watchdog(state, seconds=960):
        observed.append("inside")
    assert observed == ["start", "inside", "cancel"]


def test_watchdog_process_records_failure_and_exits_nonzero() -> None:
    script = textwrap.dedent(
        f"""
        import threading
        import time
        from lyme_gap_atlas_data import intelligence_daily_hard_kill as hard_kill
        from lyme_gap_atlas_data.settings import PipelineSettings

        worker = object()

        class Cursor:
            def __init__(self):
                self.rowcount = 1
                self._queue = []
                self.executed = []
            def execute(self, sql, params=None):
                self.executed.append(sql)
                if "CURRENT_USER()" in sql:
                    self._queue.append([(
                        "OH_LYME_PROD_PIPELINE_SVC",
                        "OH_LYME_PROD_RUNTIME",
                        "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
                        "OH_LYME_PROD_INGEST_XS_WH",
                    )])
                elif "FROM GOVERNANCE.INGESTION_RUNS" in sql:
                    self._queue.append([(
                        "cdc-mmwr",
                        "RUNNING",
                        hard_kill.DAILY_CODE_VERSION,
                        "{PROD_DAILY_SOURCE_SHA256[SOURCE]}",
                    )])
                elif "INGESTION_RUN_CHECKPOINTS" in sql and "SELECT" in sql:
                    self._queue.append([("NORMALIZE", "RUNNING")])
            def fetchall(self):
                return self._queue.pop(0)
            def fetchone(self):
                rows = self.fetchall()
                return rows[0] if rows else None
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return None

        class Connection:
            def __init__(self):
                self.cursor_obj = Cursor()
                self.committed = False
            def cursor(self):
                return self.cursor_obj
            def autocommit(self, value):
                return None
            def commit(self):
                self.committed = True
            def rollback(self):
                return None
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return None

        fresh = Connection()

        def connect(settings):
            assert settings is not worker
            return fresh

        hard_kill.PipelineSettings = lambda: PipelineSettings(
            topx_env="prod",
            enable_production_execution=True,
            snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        )
        hard_kill.connect = connect
        state = hard_kill.HardKillState()
        state.run_id = "{RUN_ID}"
        state.stage = "NORMALIZE"
        real_timer = threading.Timer
        threading.Timer = lambda seconds, callback: real_timer(0.05, callback)
        with hard_kill.daily_hard_kill_watchdog(state, seconds=30, memory_fn=lambda: (111, 222)):
            time.sleep(5)
        raise SystemExit("watchdog did not exit")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 124
    assert "stage=NORMALIZE" in result.stderr
    assert "rss_kib=111" in result.stderr
    assert "peak_rss_kib=222" in result.stderr
    assert "ledger=recorded" in result.stderr
    assert "password" not in result.stderr
    assert "watchdog did not exit" not in result.stdout


def test_watchdog_process_exits_when_ledger_write_hangs() -> None:
    script = textwrap.dedent(
        f"""
        import time
        from lyme_gap_atlas_data import intelligence_daily_hard_kill as hard_kill

        def hang(run_id, stage):
            time.sleep(30)
            raise RuntimeError("password=should-not-log")

        hard_kill.terminalize_hard_killed_run = hang
        state = hard_kill.HardKillState()
        state.run_id = "{RUN_ID}"
        state.stage = "LOAD"
        hard_kill.finish_hard_kill(
            state,
            ledger_timeout=0.2,
            memory_fn=lambda: (9, 10),
        )
        raise SystemExit("hang escaped")
        """
    )
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert time.monotonic() - started < 5
    assert result.returncode == 124
    assert "stage=LOAD" in result.stderr
    assert "rss_kib=9" in result.stderr
    assert "peak_rss_kib=10" in result.stderr
    assert "ledger=timed_out" in result.stderr
    assert "password" not in result.stderr
    assert "should-not-log" not in result.stderr


def _probe_exit(spec: dict[str, Any], queue: object) -> None:
    os._exit(int(spec["code"]))


def _probe_ok(spec: dict[str, Any], queue: Any) -> None:
    queue.put({"source_id": spec["source_id"], "outcome": "SUCCEEDED", "run_id": RUN_ID})


def _probe_sleep(spec: dict[str, Any], queue: object) -> None:
    time.sleep(30)


def test_isolated_process_hard_exit_is_failed_and_logs_exit_code(
    capfd: pytest.CaptureFixture[str],
) -> None:
    result = polling._run_isolated(_probe_exit, {"source_id": SOURCE, "code": 124}, timeout=30)
    assert result["source_id"] == SOURCE
    assert result["outcome"] == "FAILED"
    assert result["status"] == "FAILED"
    assert result["exit_code"] == 124
    assert result["error_code"] == "INTELLIGENCE_DAILY_HARD_KILL"
    assert result["failed_stage"] is None
    assert result["stage_timings_ms"] == {}
    captured = capfd.readouterr()
    expected = f"intelligence_daily_source_process_exit source_id={SOURCE} exit_code=124"
    assert expected in captured.err


def test_isolated_process_returns_child_result() -> None:
    result = polling._run_isolated(_probe_ok, {"source_id": SOURCE}, timeout=30)
    assert result["outcome"] == "SUCCEEDED"
    assert result["run_id"] == RUN_ID
    assert result["source_id"] == SOURCE


def test_isolated_process_parent_timeout_does_not_raise() -> None:
    started = time.monotonic()
    result = polling._run_isolated(_probe_sleep, {"source_id": SOURCE}, timeout=0.4)
    assert time.monotonic() - started < 5
    assert result["source_id"] == SOURCE
    assert result["outcome"] == "FAILED"
    assert isinstance(result["exit_code"], int)
    assert result["exit_code"] != 0


def test_production_executor_spawns_one_process_per_source(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []

    def fake_isolated(target: object, spec: dict[str, Any], *, timeout: float) -> dict[str, str]:
        seen.append({"target": target, "spec": spec, "timeout": timeout})
        return {"source_id": spec["source_id"], "outcome": "SUCCEEDED"}

    monkeypatch.setattr(polling, "_run_isolated", fake_isolated)
    result = _PRODUCTION_EXECUTE(
        SOURCE,
        "config/sources/intelligence_cdc_mmwr.yml",
        preflight_only=False,
        reopen_attempt=1,
        day="2026-10-24",
    )
    assert result["outcome"] == "SUCCEEDED"
    assert seen[0]["target"] is polling._daily_source_child
    assert seen[0]["spec"]["source_id"] == SOURCE
    assert seen[0]["timeout"] == hard_kill.source_process_timeout(
        polling.DAILY_SOURCE_WATCHDOG_SECONDS
    )


def test_one_hard_killed_source_does_not_starve_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    def fake(
        source_id: str,
        path: str,
        *,
        preflight_only: bool,
        reopen_attempt: int,
        day: str,
    ) -> dict[str, Any]:
        order.append(source_id)
        if source_id == "cdc-outbreaks":
            return {"source_id": source_id, "outcome": "FAILED", "exit_code": 124}
        return {
            "source_id": source_id,
            "outcome": "SUCCEEDED",
            "run_id": daily_run_id(source_id, day),
        }

    monkeypatch.setattr(polling, "execute_daily_source", fake)
    monkeypatch.setattr(
        "lyme_gap_atlas_data.settings.PipelineSettings",
        lambda: PipelineSettings(
            topx_env="prod",
            enable_production_execution=True,
            snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
            intelligence_daily_enabled=True,
        ),
    )
    result = polling.run_production_daily()
    assert order == list(PROD_SOURCE_DEFINITIONS)
    assert [row["source_id"] for row in result["sources"]] == order
    killed = next(row for row in result["sources"] if row["source_id"] == "cdc-outbreaks")
    assert killed["exit_code"] == 124
    assert result["status"] == "FAILED"
    assert all(
        row["outcome"] == "SUCCEEDED"
        for row in result["sources"]
        if row["source_id"] != "cdc-outbreaks"
    )
