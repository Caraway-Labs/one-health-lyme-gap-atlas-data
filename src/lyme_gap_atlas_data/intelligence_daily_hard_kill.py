"""Mark one daily source FAILED before its process watchdog hard-kills it.

The worker connection may be wedged inside a stage, so the ledger write always
opens a new session. The write is bounded: if it fails or does not finish, the
process still exits. Log lines carry only an allowlisted stage, memory totals,
a ledger outcome and the run id.
"""

from __future__ import annotations

import os
import re
import resource
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from .ingestion.intelligence_runtime import (
    DEADLINE_GRACE_SECONDS,
    PROD_SOURCE_DEFINITIONS,
    prod_daily_config_sha256_allowed,
)
from .ingestion.types import FailureCategory, Stage
from .settings import PipelineSettings
from .sql_sessions import connect

DAILY_CODE_VERSION = "intelligence-daily-v1"
ERROR_CLASS = "INTELLIGENCE_DAILY_HARD_KILL"
DIAGNOSTIC = "PROCESS_HARD_KILL"
HARD_KILL_EXIT_CODE = 124
# Second grace window: fresh-session ledger attempt, then exit anyway.
LEDGER_TIMEOUT_SECONDS = DEADLINE_GRACE_SECONDS
STATEMENT_TIMEOUT_SECONDS = 15
PROCESS_JOIN_BUFFER_SECONDS = 30
_STAGE_NAMES = frozenset(stage.value for stage in Stage)
_LEDGER_OUTCOMES = frozenset({"pending", "recorded", "failed", "timed_out", "skipped"})
_KIB = re.compile(r"(\d+)")


def source_process_timeout(watchdog_seconds: int) -> float:
    """Parent wait: child watchdog, ledger bound, then a small join buffer."""
    return float(watchdog_seconds + LEDGER_TIMEOUT_SECONDS + PROCESS_JOIN_BUFFER_SECONDS)


def sanitize_stage(stage: str | None) -> str:
    """Return a stage token. Anything else becomes UNKNOWN."""
    if isinstance(stage, str) and stage in _STAGE_NAMES:
        return stage
    return "UNKNOWN"


def valid_run_id(value: object) -> str | None:
    if isinstance(value, str) and value.strip() == value and len(value) == 36:
        return value
    return None


@dataclass
class HardKillState:
    """In-memory stage and run id the watchdog can read without the worker session."""

    run_id: str | None = None
    stage: str = "UNKNOWN"
    budget: Any = None

    def current_stage(self) -> str:
        noted = sanitize_stage(self.stage)
        if noted != "UNKNOWN":
            return noted
        open_stages = getattr(self.budget, "_open_stages", None)
        if isinstance(open_stages, dict) and open_stages:
            latest = next(reversed(open_stages))
            if isinstance(latest, str):
                return sanitize_stage(latest)
        return "UNKNOWN"


def remember_running_stage(state: HardKillState, run: Any) -> None:
    """Record the RUNNING stage before a checkpoint write that may wedge."""
    running: list[str] = []
    for checkpoint in getattr(run, "stages", ()):
        status = getattr(getattr(checkpoint, "status", None), "value", None)
        if status is None:
            status = getattr(checkpoint, "status", None)
        if status != "RUNNING":
            continue
        stage = getattr(getattr(checkpoint, "stage", None), "value", None)
        if not isinstance(stage, str):
            stage = getattr(checkpoint, "stage", None)
        if isinstance(stage, str):
            running.append(stage)
    if running:
        state.stage = sanitize_stage(running[-1])
    run_id = valid_run_id(getattr(run, "ingestion_run_id", None))
    if run_id is not None:
        state.run_id = run_id


def install_stage_memory(store: Any, state: HardKillState) -> None:
    """Wrap checkpoint save so the kill path knows the stage if the write hangs."""
    original = getattr(store, "save", None)
    if not callable(original):
        return

    def save(run: Any) -> Any:
        remember_running_stage(state, run)
        return original(run)

    store.save = save


def read_process_memory_kib(
    status_text: str | None = None,
) -> tuple[int | None, int | None]:
    """RSS and peak RSS in kibibytes. No other process fields."""
    if status_text is None:
        try:
            status_text = Path("/proc/self/status").read_text(encoding="utf-8")
        except OSError:
            status_text = ""
    rss: int | None = None
    peak: int | None = None
    for line in status_text.splitlines():
        if line.startswith("VmRSS:"):
            rss = _kib(line)
        elif line.startswith("VmHWM:"):
            peak = _kib(line)
    if peak is None:
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if isinstance(usage, int) and usage > 0:
                peak = usage
        except (OSError, ValueError, AttributeError):
            peak = None
    return rss, peak


def _kib(line: str) -> int | None:
    match = _KIB.search(line)
    if match is None:
        return None
    return int(match.group(1))


def format_hard_kill_log(
    *,
    stage: str | None,
    rss: int | None,
    peak: int | None,
    ledger: str,
    run_id: str | None,
) -> str:
    """One allowlisted log line. Callers cannot add free text."""
    safe_stage = sanitize_stage(stage)
    safe_ledger = ledger if ledger in _LEDGER_OUTCOMES else "failed"
    rss_text = str(rss) if isinstance(rss, int) and rss >= 0 else "unknown"
    peak_text = str(peak) if isinstance(peak, int) and peak >= 0 else "unknown"
    run_text = valid_run_id(run_id) or "none"
    return (
        "intelligence_daily_hard_kill "
        f"stage={safe_stage} rss_kib={rss_text} peak_rss_kib={peak_text} "
        f"ledger={safe_ledger} run_id={run_text}"
    )


def log_source_process_exit(source_id: str, exit_code: int | None) -> None:
    """Parent log when a source process ends without returning a result."""
    safe_source = source_id if source_id in PROD_SOURCE_DEFINITIONS else "unknown"
    code = exit_code if isinstance(exit_code, int) else HARD_KILL_EXIT_CODE
    _write_stderr(
        f"intelligence_daily_source_process_exit source_id={safe_source} exit_code={code}"
    )


def _write_stderr(line: str) -> None:
    sys.stderr.write(line + "\n")
    try:
        sys.stderr.flush()
    except Exception:
        return


def _safe_emit(writer: Callable[[str], None], line: str) -> None:
    try:
        writer(line)
    except Exception:
        return


def terminalize_hard_killed_run(ingestion_run_id: str, stage: str) -> dict[str, Any]:
    """Mark a RUNNING daily admission FAILED on a new connection.

    This function never accepts a connection. ``connect`` opens a session that
    is not the worker's possibly wedged one. Statement and queue timeouts bound
    the SQL; the caller also bounds the whole attempt.
    """
    safe_stage = sanitize_stage(stage)
    settings = PipelineSettings()
    if (
        settings.topx_env != "prod"
        or not settings.enable_production_execution
        or settings.snowflake_database != "ONE_HEALTH_LYME_GAP_ATLAS_PROD"
    ):
        raise PermissionError("INTELLIGENCE_DAILY_HARD_KILL_PROD_REQUIRED")
    run_id = valid_run_id(ingestion_run_id)
    if run_id is None:
        raise ValueError("INTELLIGENCE_DAILY_HARD_KILL_RUN_ID_REQUIRED")
    snowflake = SnowflakeSettings()
    with connect(snowflake) as connection, connection.cursor() as cursor:
        cursor.execute(
            "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=%s, "
            "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS=%s, ABORT_DETACHED_QUERY=TRUE",
            (STATEMENT_TIMEOUT_SECONDS, STATEMENT_TIMEOUT_SECONDS),
        )
        cursor.execute(
            "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()"
        )
        if cursor.fetchall() != [
            (
                "OH_LYME_PROD_PIPELINE_SVC",
                "OH_LYME_PROD_RUNTIME",
                "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
                "OH_LYME_PROD_INGEST_XS_WH",
            )
        ]:
            raise PermissionError("INTELLIGENCE_DAILY_HARD_KILL_RUNTIME_CONTEXT_REQUIRED")
        cursor.execute(
            """SELECT resource_key, status, code_version, config_sha256
            FROM GOVERNANCE.INGESTION_RUNS WHERE ingestion_run_id=%s""",
            (run_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise PermissionError("INTELLIGENCE_DAILY_HARD_KILL_RUN_NOT_FOUND")
        resource_key, status, code_version, config_sha256 = row
        if (
            status != "RUNNING"
            or code_version != DAILY_CODE_VERSION
            or resource_key not in PROD_SOURCE_DEFINITIONS
            or not prod_daily_config_sha256_allowed(resource_key, config_sha256)
        ):
            raise PermissionError("INTELLIGENCE_DAILY_HARD_KILL_SCOPE_REQUIRED")
        cursor.execute(
            """SELECT stage, status FROM GOVERNANCE.INGESTION_RUN_CHECKPOINTS
            WHERE ingestion_run_id=%s ORDER BY updated_at""",
            (run_id,),
        )
        checkpoints = cursor.fetchall()
        running_stages = [name for name, stage_status in checkpoints if stage_status == "RUNNING"]
        connection.autocommit(False)
        try:
            if running_stages:
                cursor.execute(
                    """UPDATE GOVERNANCE.INGESTION_RUN_CHECKPOINTS
                    SET status='FAILED', failure_category=%s,
                        redacted_diagnostic_code=%s, updated_at=CURRENT_TIMESTAMP(),
                        completed_at=CURRENT_TIMESTAMP()
                    WHERE ingestion_run_id=%s AND status='RUNNING'""",
                    (FailureCategory.PROCESS.value, DIAGNOSTIC, run_id),
                )
                if cursor.rowcount != len(running_stages):
                    raise PermissionError("INTELLIGENCE_DAILY_HARD_KILL_CHECKPOINT_MISMATCH")
            cursor.execute(
                """UPDATE GOVERNANCE.INGESTION_RUNS
                SET status='FAILED', completed_at=CURRENT_TIMESTAMP(),
                    error_classification=%s,
                    redacted_error=%s
                WHERE ingestion_run_id=%s AND status='RUNNING'""",
                (
                    ERROR_CLASS,
                    f"Daily source hard-killed during {safe_stage}.",
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise PermissionError("INTELLIGENCE_DAILY_HARD_KILL_RUN_UPDATE_REQUIRED")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    return {
        "status": "SUCCEEDED",
        "ingestion_run_id": run_id,
        "resource_key": resource_key,
        "terminalized_stages": running_stages,
        "stage": safe_stage,
    }


def _ledger_with_timeout(run_id: str, stage: str, timeout: float) -> str:
    outcome = {"value": "timed_out"}
    finished = threading.Event()

    def attempt() -> None:
        try:
            terminalize_hard_killed_run(run_id, stage)
            outcome["value"] = "recorded"
        except Exception:
            outcome["value"] = "failed"
        finally:
            finished.set()

    worker = threading.Thread(
        target=attempt,
        name="intelligence-daily-hard-kill-ledger",
        daemon=True,
    )
    worker.start()
    if not finished.wait(timeout):
        return "timed_out"
    return outcome["value"]


def finish_hard_kill(
    state: HardKillState,
    *,
    ledger_timeout: float = LEDGER_TIMEOUT_SECONDS,
    exit_fn: Callable[[int], None] = os._exit,
    memory_fn: Callable[[], tuple[int | None, int | None]] | None = None,
    writer: Callable[[str], None] | None = None,
) -> None:
    """Log stage and memory, try the fresh-session FAILED write, then exit."""
    emit = writer or _write_stderr
    try:
        try:
            stage = state.current_stage()
        except Exception:
            stage = "UNKNOWN"
        try:
            rss, peak = (memory_fn or read_process_memory_kib)()
        except Exception:
            rss, peak = None, None
        run_id = valid_run_id(state.run_id)
        _safe_emit(
            emit,
            format_hard_kill_log(stage=stage, rss=rss, peak=peak, ledger="pending", run_id=run_id),
        )
        ledger = "skipped"
        if run_id is not None:
            ledger = _ledger_with_timeout(run_id, stage, ledger_timeout)
        _safe_emit(
            emit,
            format_hard_kill_log(stage=stage, rss=rss, peak=peak, ledger=ledger, run_id=run_id),
        )
    finally:
        exit_fn(HARD_KILL_EXIT_CODE)


@contextmanager
def daily_hard_kill_watchdog(
    state: HardKillState,
    *,
    seconds: int,
    ledger_timeout: float = LEDGER_TIMEOUT_SECONDS,
    exit_fn: Callable[[int], None] = os._exit,
    memory_fn: Callable[[], tuple[int | None, int | None]] | None = None,
    writer: Callable[[str], None] | None = None,
) -> Iterator[None]:
    """Hard-kill one source process at ``seconds``.

    The ledger attempt cannot delay the exit past its bound.
    """
    if seconds < 1:
        raise ValueError("daily hard-kill seconds must be positive")

    def fire() -> None:
        finish_hard_kill(
            state,
            ledger_timeout=ledger_timeout,
            exit_fn=exit_fn,
            memory_fn=memory_fn,
            writer=writer,
        )

    timer = threading.Timer(seconds, fire)
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel()
