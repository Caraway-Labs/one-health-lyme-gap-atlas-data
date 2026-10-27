"""Prepare a frozen daily source selection for the existing ingestion runner.

No scheduler deployment, source approval, policy creation or warehouse writes.
"""

from __future__ import annotations

import ctypes
import gc
import json
import multiprocessing
import os
import re
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty
from typing import Any, cast

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from . import settings as pipeline_settings
from .ingestion import intelligence_runtime
from .ingestion.intelligence_checkpoints import IntelligenceSnowflakeCheckpoints
from .ingestion.intelligence_daily_run_ids import MAX_DAILY_ATTEMPTS, daily_run_id
from .ingestion.intelligence_entrez import (
    PUBMED_PIPELINE_STEPS,
    RECEIPT_PATH,
    SOURCE_ORDER,
    current_pubmed_step,
    execute_registered_entrez_daily,
    live_entrez_get,
    registered_entrez_sources,
)
from .ingestion.intelligence_runtime import (
    DAILY_OPERATOR_STAGE_NAMES,
    DAILY_SOURCE_BUDGET_SECONDS,
    DAILY_SOURCE_INACTIVITY_SECONDS,
    DAILY_SOURCE_RUN_ORDER,
    DAILY_SOURCE_WATCHDOG_SECONDS,
    ORCHESTRATOR_STAGE_TO_DAILY,
    PROD_SOURCE_DEFINITIONS,
    DailyStageClock,
    reviewed_prod_source_sha256,
)
from .ingestion.source_definition import load_source_definition
from .ingestion.step_deadline import (
    bind_step_deadline,
    note_step_deadline,
    reset_step_deadline,
)
from .ingestion.types import (
    AdapterKind,
    FailureCategory,
    RunState,
    RunStatus,
    SourceDefinition,
    Stage,
    StageCheckpoint,
    StageStatus,
    Tier,
)
from .intelligence_daily_deadline import terminalize_daily_pilot_deadline
from .intelligence_daily_hard_kill import (
    HARD_KILL_EXIT_CODE,
    HardKillState,
    daily_hard_kill_watchdog,
    install_stage_memory,
    log_parent_watchdog,
    log_source_process_exit,
    record_parent_hard_kill,
    sanitize_stage,
    source_process_timeout,
    valid_run_id,
)
from .intelligence_daily_job_timeout import DAILY_JOB_DEADLINE_SECONDS
from .intelligence_daily_telemetry import (
    HEARTBEAT_SECONDS,
    StageHeartbeat,
    activate_observation,
    bind_context,
    carrier_from_current,
    emit,
    emit_run_summary,
    emit_source_summary,
    job_span,
    observation_active,
    prepare_worker,
    process_memory_fields,
    reset_observation,
    shutdown_daily_logs,
    source_span,
    spawn_observed,
    stage_scope,
    step_span,
    transferred_bytes,
)
from .intelligence_items import canonical_url, identity_hash, validate_record
from .intelligence_metadata import NativeMetadataPolicy
from .intelligence_raw_runtime import FeedRawRetention, SnowflakeRawLedger
from .intelligence_storage import IntelligenceStore
from .sql_sessions import connect

DAILY_POLL_SECONDS = 86_400
DAILY_OUTCOME_LOG_PREFIX = "ATLAS_INTEL_DAILY_OUTCOME "
_ITEM_COUNT_FIELDS = ("items_seen", "items_new", "items_changed", "items_unchanged")
_MAX_ITEM_COUNT = 5000
_MAX_OUTCOME_LOG_BYTES = 4096
# Exception text is emitted only when the whole message is one of these codes.
_ALLOWLISTED_ERROR_CODE = re.compile(
    r"^(?:INTELLIGENCE_[A-Z0-9_]{3,80}|FEED_[A-Z0-9_]{1,80}|MALFORMED_FEED|"
    r"UNSUPPORTED_FEED_ENVELOPE|AMBIGUOUS_FEED_FIELD|XML_[A-Z0-9_]{3,80})$"
)
_EXCEPTION_CLASS_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,80}$")
# Recorded on an unclassified PubMed failure. Digits are allowed; the cap is 80.
_BOUNDED_EXCEPTION_CLASS = re.compile(r"^[A-Za-z0-9_]{1,80}$")
_SQLSTATE = re.compile(r"^[0-9A-Z]{5}$")
_MAX_DBAPI_ERRNO = 9_999_999
_PARSE_FAILURE_CODES = frozenset(
    {
        "MALFORMED_FEED",
        "UNSUPPORTED_FEED_ENVELOPE",
        "AMBIGUOUS_FEED_FIELD",
        "XML_COMPLEXITY_LIMIT",
        "XML_DTD_FORBIDDEN",
        "XML_BASE_INVALID",
        "FEED_TOPIC_LIMIT",
    }
)
_STATUS_FOR_OUTCOME = {
    "SUCCEEDED": "COMPLETED",
    "FAILED": "FAILED",
    "ALREADY_CLAIMED": "ALREADY_CLAIMED",
    "SCHEDULE_SUPPRESSED": "SCHEDULE_SUPPRESSED",
    "READY": "READY",
    "PREFLIGHT_OR_RUNTIME_FAILED": "FAILED",
    "SKIPPED_NOT_SELECTED": "SKIPPED_NOT_SELECTED",
}
# One reopen names one source. Five is the whole approved daily set.
MAX_DAILY_SOURCE_SELECTION = 5
# Five Entrez requests at the 30 second cap, plus pacing. Independent of the RSS budget.
PUBMED_WALK_DEADLINE_SECONDS = 180
# Fresh FAILED save after the walk process is killed. It must not run unbounded.
PUBMED_FAIL_SAVE_SECONDS = 30
# Checkpoint code when the failure has no allowlisted code of its own.
PUBMED_DAILY_FAILED = "PUBMED_DAILY_FAILED"
_REOPEN_PRIOR_NOT_FAILED = "INTELLIGENCE_DAILY_REOPEN_PRIOR_TERMINAL_FAILED"
# The scheduled job's one automatic re-run. Manual attempts 2 and 3 stay explicit.
SCHEDULED_RETRY_ATTEMPT = 2
# Parent join after a killed PubMed walk, then the bounded FAILED save.
# 180 + 5 + 30. The isolated walk uses these same bounds.
PUBMED_KILL_JOIN_SECONDS = 5
PUBMED_RETRY_CAP_SECONDS = (
    PUBMED_WALK_DEADLINE_SECONDS + PUBMED_KILL_JOIN_SECONDS + PUBMED_FAIL_SAVE_SECONDS
)
# RSS parent wait: watchdog, ledger bound, and join buffer (1020s).
RSS_RETRY_CAP_SECONDS = int(source_process_timeout(DAILY_SOURCE_WATCHDOG_SECONDS))
# One deadline for retry admission. The default is the standing job's 1h30m
# DigitalOcean timeout (5400s), the same value as DAILY_JOB_TIMEOUT. Override
# it with INTELLIGENCE_DAILY_JOB_DEADLINE_SECONDS when that timeout changes.
# A first pass that already exceeds the deadline is left intact and does not retry.
DAILY_JOB_DEADLINE_ENV = "INTELLIGENCE_DAILY_JOB_DEADLINE_SECONDS"
DAILY_JOB_DEADLINE_MARGIN_SECONDS = 60
SCHEDULED_RETRY_SKIPPED = "INTELLIGENCE_DAILY_SCHEDULED_RETRY_SKIPPED"
RETRY_SKIPPED_LOG_PREFIX = "ATLAS_INTEL_DAILY_RETRY_SKIPPED "
# These denials are not a consumed provider failure, so the scheduled job does not
# spend another attempt on them.
_NO_SAME_DAY_RETRY = frozenset(
    {
        "INTELLIGENCE_DAILY_REOPEN_PRIOR_TERMINAL_FAILED",
        "INTELLIGENCE_DAILY_REOPEN_REQUIRED",
        "INTELLIGENCE_DAILY_REOPEN_SOURCE_REQUIRED",
        "INTELLIGENCE_DAILY_ATTEMPT_CAP",
        "INTELLIGENCE_DAILY_CLAIM_SCOPE_REQUIRED",
        "INTELLIGENCE_DAILY_SOURCE_SELECTION_INVALID",
        "INTELLIGENCE_DAILY_ACTIVE_SOURCE_REQUIRED",
        "INTELLIGENCE_DAILY_SCHEDULED_RETRY_INVALID",
        "INTELLIGENCE_DAILY_PROD_REQUIRED",
    }
)
# Production walks in a child so a swallowed SIGALRM cannot keep the parent going.
PUBMED_WALK_ISOLATE = True
_LOG_STATUSES = frozenset(_STATUS_FOR_OUTCOME.values())
_LOG_OUTCOMES = frozenset(_STATUS_FOR_OUTCOME)


def _terminalize_claimed_daily_run(run_id: str, source_id: str) -> None:
    from .intelligence_daily_run_recovery import terminalize_stuck_daily_run

    try:
        terminalize_stuck_daily_run(run_id, source_id=source_id)
    except Exception:
        return


def _stage_timings(budget: Any) -> list[dict[str, Any]]:
    """Redacted per-stage seconds and query counts: no payloads, URLs or error text."""
    report = getattr(budget, "timing_report", None)
    return report() if callable(report) else []


def allowlisted_error_code(error: BaseException) -> str:
    """Return a code safe to print. Free-text exception messages are never returned."""
    message = str(error)
    if _ALLOWLISTED_ERROR_CODE.fullmatch(message):
        return message
    code = getattr(error, "code", None)
    if isinstance(code, str) and _ALLOWLISTED_ERROR_CODE.fullmatch(code):
        return code
    name = type(error).__name__
    if _EXCEPTION_CLASS_NAME.fullmatch(name):
        return f"UNCLASSIFIED_{name}"
    return "UNCLASSIFIED_EXCEPTION"


def published_error_code(code: object) -> str | None:
    """Keep an error code that is allowlisted or an UNCLASSIFIED class token."""
    if not isinstance(code, str):
        return None
    if _ALLOWLISTED_ERROR_CODE.fullmatch(code):
        return code
    prefix = "UNCLASSIFIED_"
    class_name = code.removeprefix(prefix)
    if code.startswith(prefix) and _EXCEPTION_CLASS_NAME.fullmatch(class_name):
        return code
    return None


def _diagnostic_error_code(code: object) -> str:
    published = published_error_code(code)
    if published is not None:
        return published
    if isinstance(code, str) and _EXCEPTION_CLASS_NAME.fullmatch(code):
        return f"UNCLASSIFIED_{code}"
    return "UNCLASSIFIED_EXCEPTION"


def _retention_failure(code: str | None) -> bool:
    if code is None:
        return False
    return (
        code.startswith("INTELLIGENCE_RAW_")
        or code.startswith("INTELLIGENCE_ARTIFACT_RETENTION")
        or code == "INTELLIGENCE_RETENTION_NOT_APPROVED"
    )


def daily_failed_stage(
    *,
    explicit: str | None,
    orchestrator_stage: str | None,
    code: str | None,
) -> str | None:
    """Map a failure onto one operator stage. An explicit CLAIM stays CLAIM."""
    if explicit == "CLAIM":
        return "CLAIM"
    if code in _PARSE_FAILURE_CODES or (code is not None and code.startswith("XML_")):
        return "PARSE"
    mapped = ORCHESTRATOR_STAGE_TO_DAILY.get(orchestrator_stage or "")
    stage = explicit if explicit in DAILY_OPERATOR_STAGE_NAMES else mapped
    if _retention_failure(code) and stage in {None, "FETCH", "WRITE", "PARSE"}:
        return "RETENTION"
    if stage in DAILY_OPERATOR_STAGE_NAMES:
        return stage
    if code is not None and code.startswith("FEED_"):
        return "FETCH"
    return None


def _bounded_timings(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    clean: dict[str, int] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or key not in DAILY_OPERATOR_STAGE_NAMES:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if value < 0 or value > 10**12:
            continue
        clean[key] = value
    return clean


def _budget_daily_stage(budget: Any) -> str | None:
    opener = getattr(budget, "open_daily_stage", None)
    if not callable(opener):
        return None
    stage = opener()
    if isinstance(stage, str) and stage in DAILY_OPERATOR_STAGE_NAMES:
        return stage
    return None


def _budget_timings_ms(budget: Any) -> dict[str, int]:
    reporter = getattr(budget, "operator_timings_ms", None)
    if not callable(reporter):
        return {}
    return _bounded_timings(reporter())


def _merged_timings(clock: DailyStageClock, budget: Any) -> dict[str, int]:
    merged = dict(clock.snapshot_ms())
    for stage, milliseconds in _budget_timings_ms(budget).items():
        merged[stage] = merged.get(stage, 0) + milliseconds
    return _bounded_timings(merged)


def _log_token(value: object, *, allowed: frozenset[str]) -> str | None:
    if isinstance(value, str) and value in allowed:
        return value
    return None


def _nonnegative_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > _MAX_ITEM_COUNT:
        return None
    return value


def _validated_item_counts(payload: dict[str, Any]) -> dict[str, int]:
    """Allowlisted per-source change counts. Any non-integer drops the whole set."""
    counts: dict[str, int] = {}
    for field in _ITEM_COUNT_FIELDS:
        if field not in payload:
            return {}
        parsed = _nonnegative_count(payload.get(field))
        if parsed is None:
            return {}
        counts[field] = parsed
    total = counts["items_new"] + counts["items_changed"] + counts["items_unchanged"]
    if total != counts["items_seen"]:
        return {}
    return counts


def _item_counts_from_state(state: Any) -> dict[str, int]:
    checkpoint = getattr(state, "checkpoint", None)
    if not callable(checkpoint):
        return {}
    load = checkpoint(Stage.LOAD)
    detail = getattr(load, "detail", None)
    if not isinstance(detail, dict):
        return {}
    return _validated_item_counts(detail)


def _log_daily_outcome(result: dict[str, Any]) -> None:
    """One grep-able line. Fields are allowlisted so exception text cannot land here."""
    source_id = result.get("source_id")
    safe_source = (
        source_id
        if isinstance(source_id, str)
        and source_id.isascii()
        and 1 <= len(source_id) <= 80
        and all(char.isalnum() or char in "-_" for char in source_id)
        else "unknown"
    )
    safe: dict[str, Any] = {
        "failed_stage": result.get("failed_stage")
        if result.get("failed_stage") in DAILY_OPERATOR_STAGE_NAMES
        else None,
        "outcome": _log_token(result.get("outcome"), allowed=_LOG_OUTCOMES),
        "source_id": safe_source,
        "stage_timings_ms": _bounded_timings(result.get("stage_timings_ms")),
        "status": _log_token(result.get("status"), allowed=_LOG_STATUSES),
    }
    error_code = published_error_code(result.get("error_code"))
    if error_code is not None:
        safe["error_code"] = error_code
    run_id = result.get("run_id")
    if isinstance(run_id, str) and len(run_id) == 36 and run_id.strip() == run_id:
        safe["run_id"] = run_id
    exit_code = result.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        safe["exit_code"] = exit_code
    daily_attempt = result.get("daily_attempt")
    if (
        isinstance(daily_attempt, int)
        and not isinstance(daily_attempt, bool)
        and 2 <= daily_attempt <= MAX_DAILY_ATTEMPTS
    ):
        safe["daily_attempt"] = daily_attempt
    raw_timings = result.get("stage_timings_ms", {})
    if raw_timings is None:
        safe.pop("stage_timings_ms", None)
    safe.update(_validated_item_counts(result))
    line = DAILY_OUTCOME_LOG_PREFIX + json.dumps(safe, separators=(",", ":"), sort_keys=True)
    if len(line.encode("utf-8")) > _MAX_OUTCOME_LOG_BYTES:
        safe["stage_timings_ms"] = {}
        line = DAILY_OUTCOME_LOG_PREFIX + json.dumps(safe, separators=(",", ":"), sort_keys=True)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _source_outcome(
    source_id: str,
    outcome: str,
    *,
    run_id: str | None = None,
    error_code: str | None = None,
    failed_stage: str | None = None,
    stage_timings_ms: dict[str, int] | None = None,
    stage_timings: list[dict[str, Any]] | None = None,
    exit_code: int | None = None,
    item_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    published = published_error_code(error_code)
    if error_code is not None and published is None:
        published = "UNCLASSIFIED_EXCEPTION"
    result: dict[str, Any] = {
        "source_id": source_id,
        "outcome": outcome,
        "status": _STATUS_FOR_OUTCOME.get(outcome, "FAILED"),
        "failed_stage": failed_stage if failed_stage in DAILY_OPERATOR_STAGE_NAMES else None,
        "stage_timings_ms": _bounded_timings(stage_timings_ms or {}),
    }
    if published is not None:
        result["error_code"] = published
    if run_id is not None:
        result["run_id"] = run_id
    if stage_timings is not None:
        result["stage_timings"] = stage_timings
    if exit_code is not None:
        result["exit_code"] = exit_code
    if item_counts:
        result.update(item_counts)
    return result


def _failure_from_state(state: Any, budget: Any) -> tuple[str, str | None]:
    failed_checkpoint = None
    stages = getattr(state, "stages", None)
    if isinstance(stages, list):
        for checkpoint in stages:
            status = getattr(checkpoint, "status", None)
            value = getattr(status, "value", status)
            if value == "FAILED":
                failed_checkpoint = checkpoint
    explicit = _budget_daily_stage(budget)
    if failed_checkpoint is None:
        return (
            "UNCLASSIFIED_EXCEPTION",
            daily_failed_stage(explicit=explicit, orchestrator_stage=None, code=None),
        )
    raw_code = getattr(failed_checkpoint, "redacted_diagnostic_code", None)
    code = raw_code if isinstance(raw_code, str) else None
    stage_obj = getattr(failed_checkpoint, "stage", None)
    stage_value = getattr(stage_obj, "value", stage_obj)
    orchestrator_stage = stage_value if isinstance(stage_value, str) else None
    return (
        _diagnostic_error_code(code),
        daily_failed_stage(
            explicit=None if orchestrator_stage else explicit,
            orchestrator_stage=orchestrator_stage,
            code=code,
        ),
    )


def _failed_from_exception(
    source_id: str,
    error: BaseException,
    *,
    run_id: str | None,
    budget: Any,
    claim_clock: DailyStageClock,
    explicit_stage: str | None,
) -> dict[str, Any]:
    code = allowlisted_error_code(error)
    stage_code = None if explicit_stage == "CLAIM" else code
    return _source_outcome(
        source_id,
        "FAILED",
        run_id=run_id,
        error_code=code,
        failed_stage=daily_failed_stage(
            explicit=explicit_stage,
            orchestrator_stage=None,
            code=stage_code,
        ),
        stage_timings_ms=_merged_timings(claim_clock, budget),
        stage_timings=_stage_timings(budget) if budget is not None else None,
    )


_CHILD_OUTCOMES = frozenset(
    {
        "SUCCEEDED",
        "FAILED",
        "ALREADY_CLAIMED",
        "SCHEDULE_SUPPRESSED",
        "READY",
        "PREFLIGHT_OR_RUNTIME_FAILED",
    }
)


def _retry_clock() -> float:
    return time.monotonic()


def daily_job_deadline_seconds() -> int:
    """Return the job deadline a scheduled retry must finish inside.

    Unset or blank uses ``DAILY_JOB_DEADLINE_SECONDS``. A positive integer in
    ``INTELLIGENCE_DAILY_JOB_DEADLINE_SECONDS`` overrides it, up to 24 hours.
    Any other value keeps the named default so a bad override cannot drop the bound.
    """
    raw = os.environ.get(DAILY_JOB_DEADLINE_ENV)
    if raw is None or raw.strip() == "":
        return DAILY_JOB_DEADLINE_SECONDS
    token = raw.strip()
    if token.isdigit():
        value = int(token)
        if 0 < value <= 24 * 60 * 60:
            return value
    return DAILY_JOB_DEADLINE_SECONDS


def _retry_within_job_deadline(job_started: float, cap_seconds: int) -> bool:
    """True when this retry's cap still finishes under the deadline minus margin.

    ``job_started`` is the monotonic clock captured at the start of
    ``run_production_daily``. The first pass does not consult this predicate.
    """
    limit = daily_job_deadline_seconds() - DAILY_JOB_DEADLINE_MARGIN_SECONDS
    if cap_seconds <= 0 or limit <= 0:
        return False
    elapsed = _retry_clock() - job_started
    return elapsed + cap_seconds < limit


def _retriable_same_day_failure(error_code: object) -> bool:
    return not (isinstance(error_code, str) and error_code in _NO_SAME_DAY_RETRY)


def _daily_source_child(spec: dict[str, Any], result_queue: Any) -> None:
    """Child entry. A hard kill in this process leaves the parent and siblings alive."""
    prepare_worker(spec)
    source_id = spec.get("source_id")
    safe_source = source_id if isinstance(source_id, str) else "unknown"
    try:
        result_queue.put(
            execute_daily_source_in_process(
                safe_source,
                str(spec["path"]),
                preflight_only=bool(spec["preflight_only"]),
                reopen_attempt=int(spec["reopen_attempt"]),
                day=str(spec["day"]),
                scheduled_retry=bool(spec.get("scheduled_retry")),
            )
        )
    except Exception as error:
        result_queue.put(
            _failed_from_exception(
                safe_source,
                error,
                run_id=None,
                budget=None,
                claim_clock=DailyStageClock(),
                explicit_stage="CLAIM",
            )
        )
    finally:
        shutdown_daily_logs()


def _accept_child_result(source_id: str, payload: Any) -> dict[str, Any]:
    """Keep the child summary. Drop free-text fields the parent must not republish."""
    if not isinstance(payload, dict):
        return _source_outcome(
            source_id,
            "FAILED",
            error_code="UNCLASSIFIED_EXCEPTION",
            stage_timings_ms={},
        )
    outcome = payload.get("outcome")
    if outcome not in _CHILD_OUTCOMES:
        outcome = "FAILED"
    run_id = payload.get("run_id")
    safe_run_id = (
        run_id
        if isinstance(run_id, str) and len(run_id) == 36 and run_id.strip() == run_id
        else None
    )
    timings = payload.get("stage_timings")
    exit_code = payload.get("exit_code")
    safe_exit = (
        exit_code if isinstance(exit_code, int) and not isinstance(exit_code, bool) else None
    )
    failed_stage = payload.get("failed_stage")
    error_code = published_error_code(payload.get("error_code"))
    if outcome == "FAILED" and error_code is None:
        error_code = "UNCLASSIFIED_EXCEPTION"
    if outcome == "PREFLIGHT_OR_RUNTIME_FAILED" and error_code is None:
        error_code = "UNCLASSIFIED_EXCEPTION"
    return _source_outcome(
        source_id,
        outcome,
        run_id=safe_run_id,
        error_code=error_code,
        failed_stage=failed_stage if isinstance(failed_stage, str) else None,
        stage_timings_ms=_bounded_timings(payload.get("stage_timings_ms")),
        stage_timings=timings if isinstance(timings, list) else None,
        exit_code=safe_exit,
        item_counts=_validated_item_counts(payload),
    )


def _run_isolated(
    target: Callable[[dict[str, Any], Any], None],
    spec: dict[str, Any],
    *,
    timeout: float,
    inactivity_seconds: float | None = None,
    ledger_fn: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """Run ``target`` in a spawned process so ``os._exit`` cannot stop later sources.

    The parent watchdog does not run inside the child. If the child stops
    sending progress, the parent kills it, writes the FAILED row, and returns
    so the next source can start.
    """
    source_value = spec.get("source_id")
    source_id = source_value if isinstance(source_value, str) else "unknown"
    if inactivity_seconds is None:
        inactivity_seconds = float(DAILY_SOURCE_INACTIVITY_SECONDS)
    if inactivity_seconds <= 0:
        raise ValueError("inactivity_seconds must be positive")
    ctx = multiprocessing.get_context("spawn")
    result_queue: Any = ctx.Queue()
    child_spec = dict(spec)
    stage_queue: Any = None
    with suppress(Exception):
        child_spec["_trace"] = carrier_from_current()
        stage_queue = ctx.Queue(maxsize=32)
        child_spec["_stage_queue"] = stage_queue
    process = ctx.Process(target=target, args=(child_spec, result_queue), daemon=False)
    process.start()
    heartbeat_stop = threading.Event()
    stall_lock = threading.Lock()
    stall: dict[str, str | None] = {"reason": None, "stage": None}

    def on_inactive(stage: str | None) -> None:
        with stall_lock:
            if stall["reason"] is not None:
                return
            stall["reason"] = "inactivity"
            if isinstance(stage, str) and stage:
                stall["stage"] = stage
            reason = "inactivity"
            noted = stall["stage"]
        log_parent_watchdog(
            source_id=source_id,
            stage=noted,
            ledger="pending",
            run_id=_spec_run_id(spec),
            reason=reason,
        )
        if process.is_alive():
            process.kill()

    heartbeat_thread = start_parent_stage_heartbeat(
        process,
        stage_queue,
        source_id,
        heartbeat_stop,
        name="intelligence-daily-parent-heartbeat",
        inactivity_seconds=inactivity_seconds,
        on_inactive=on_inactive,
        stage_holder=stall,
        stage_lock=stall_lock,
    )
    try:
        process.join(timeout)
        with stall_lock:
            reason = stall["reason"]
            stage = stall["stage"]
            if reason is None and process.is_alive():
                stall["reason"] = "timeout"
                reason = "timeout"
        if reason == "timeout":
            log_parent_watchdog(
                source_id=source_id,
                stage=stage,
                ledger="pending",
                run_id=_spec_run_id(spec),
                reason="timeout",
            )
            if process.is_alive():
                process.kill()
                process.join(5)
            with stall_lock:
                stage = stall["stage"]
        if reason is not None:
            return _parent_hard_kill_outcome(
                source_id,
                spec,
                process.exitcode,
                stage,
                reason,
                ledger_fn,
            )
        exit_code = process.exitcode
        if exit_code == 0:
            try:
                payload = result_queue.get(timeout=5)
            except Empty:
                return _source_outcome(
                    source_id,
                    "FAILED",
                    error_code="UNCLASSIFIED_EXCEPTION",
                    stage_timings_ms={},
                    exit_code=0,
                )
            return _accept_child_result(source_id, payload)
        log_source_process_exit(source_id, exit_code)
        code = exit_code if isinstance(exit_code, int) else HARD_KILL_EXIT_CODE
        error_code = (
            "INTELLIGENCE_DAILY_HARD_KILL"
            if code == HARD_KILL_EXIT_CODE
            else "INTELLIGENCE_DAILY_SOURCE_PROCESS_FAILED"
        )
        return _source_outcome(
            source_id,
            "FAILED",
            error_code=error_code,
            stage_timings_ms={},
            exit_code=code,
        )
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(1)
        if process.is_alive():
            process.kill()
            process.join(5)
        result_queue.close()
        result_queue.cancel_join_thread()
        if stage_queue is not None:
            with suppress(Exception):
                stage_queue.close()
        process.close()


def _spec_run_id(spec: dict[str, Any]) -> str | None:
    return valid_run_id(spec.get("run_id"))


def _operator_failed_stage(stage: str | None) -> str | None:
    safe = sanitize_stage(stage) if isinstance(stage, str) else None
    if safe in DAILY_OPERATOR_STAGE_NAMES:
        return safe
    if isinstance(stage, str) and stage in ORCHESTRATOR_STAGE_TO_DAILY:
        return ORCHESTRATOR_STAGE_TO_DAILY[stage]
    return None


def _parent_hard_kill_outcome(
    source_id: str,
    spec: dict[str, Any],
    exit_code: int | None,
    stage: str | None,
    reason: str,
    ledger_fn: Callable[[str, str], str] | None,
) -> dict[str, Any]:
    """Record FAILED on the parent, then return the source outcome."""
    run_id = _spec_run_id(spec)
    safe_stage = sanitize_stage(stage)
    writer = ledger_fn or record_parent_hard_kill
    try:
        ledger = writer(run_id or "", safe_stage)
    except Exception:
        ledger = "failed"
    if ledger not in {"pending", "recorded", "failed", "timed_out", "skipped"}:
        ledger = "failed"
    log_parent_watchdog(
        source_id=source_id,
        stage=safe_stage,
        ledger=ledger,
        run_id=run_id,
        reason=reason,
    )
    log_source_process_exit(source_id, exit_code)
    code = exit_code if isinstance(exit_code, int) else HARD_KILL_EXIT_CODE
    return _source_outcome(
        source_id,
        "FAILED",
        run_id=run_id,
        error_code="INTELLIGENCE_DAILY_HARD_KILL",
        failed_stage=_operator_failed_stage(stage),
        stage_timings_ms={},
        exit_code=code,
    )


def _drain_stage(stage_queue: Any, last: str | None) -> tuple[str | None, bool]:
    """Return the latest stage and whether the child sent any progress token."""
    if stage_queue is None:
        return last, False
    progressed = False
    while True:
        try:
            item = stage_queue.get_nowait()
        except Empty:
            return last, progressed
        progressed = True
        if item == "LIVE":
            continue
        if isinstance(item, str) and item:
            last = item
        elif item == "":
            last = None


def start_parent_stage_heartbeat(
    process: Any,
    stage_queue: Any,
    source_id: str,
    stop: threading.Event,
    *,
    name: str,
    interval: float = HEARTBEAT_SECONDS,
    inactivity_seconds: float | None = None,
    on_inactive: Callable[[str | None], None] | None = None,
    stage_holder: dict[str, str | None] | None = None,
    stage_lock: threading.Lock | None = None,
) -> threading.Thread:
    """Parent heartbeat thread. Context is copied so observation stays active."""
    return spawn_observed(
        _parent_stage_heartbeat,
        (
            process,
            stage_queue,
            source_id,
            stop,
            interval,
            inactivity_seconds,
            on_inactive,
            stage_holder,
            stage_lock,
        ),
        name=name,
    )


def _parent_stage_heartbeat(
    process: Any,
    stage_queue: Any,
    source_id: str,
    stop: threading.Event,
    interval: float = HEARTBEAT_SECONDS,
    inactivity_seconds: float | None = None,
    on_inactive: Callable[[str | None], None] | None = None,
    stage_holder: dict[str, str | None] | None = None,
    stage_lock: threading.Lock | None = None,
) -> None:
    """Heartbeat and stall detection in the parent, independent of the child."""
    last: str | None = None
    last_progress = time.monotonic()
    last_emit = time.monotonic()
    wait = min(interval, 1.0)
    while not stop.wait(wait):
        last, progressed = _drain_stage(stage_queue, last)
        now = time.monotonic()
        if progressed:
            last_progress = now
        if stage_holder is not None and last:
            if stage_lock is None:
                stage_holder["stage"] = last
            else:
                with stage_lock:
                    stage_holder["stage"] = last
        if not process.is_alive():
            return
        if (
            inactivity_seconds is not None
            and on_inactive is not None
            and now - last_progress >= inactivity_seconds
        ):
            with suppress(Exception):
                on_inactive(last)
            return
        if last is None or now - last_emit < interval:
            continue
        last_emit = now
        bind_context(source_id=source_id, stage=last)
        with suppress(Exception):
            memory = process_memory_fields()
            emit(
                "stage.heartbeat",
                step="heartbeat",
                stage=last,
                rss_kib=memory["rss_kib"],
                peak_rss_kib=memory["peak_rss_kib"],
            )


def execute_daily_source(
    source_id: str,
    path: str,
    *,
    preflight_only: bool,
    reopen_attempt: int,
    day: str,
    scheduled_retry: bool = False,
) -> dict[str, Any]:
    """Run one source in a child process so a hard kill stops only that source."""
    return _run_isolated(
        _daily_source_child,
        {
            "source_id": source_id,
            "path": path,
            "preflight_only": preflight_only,
            "reopen_attempt": reopen_attempt,
            "day": day,
            "scheduled_retry": scheduled_retry,
            "run_id": daily_run_id(source_id, day, reopen_attempt=reopen_attempt),
        },
        timeout=source_process_timeout(DAILY_SOURCE_WATCHDOG_SECONDS),
    )


def execute_daily_source_in_process(
    source_id: str,
    path: str,
    *,
    preflight_only: bool,
    reopen_attempt: int,
    day: str,
    scheduled_retry: bool = False,
) -> dict[str, Any]:
    """Run one daily source in the current process. Tests use this seam."""
    already = observation_active()
    token = None if already else activate_observation()
    bind_context(source_id=source_id, attempt=reopen_attempt)
    started = time.monotonic()
    # Pulse even when the parent emits the visible heartbeat. A frozen child
    # stops pulsing, which is what the parent inactivity cap measures.
    heartbeat = StageHeartbeat()
    heartbeat.start()
    try:
        with source_span(source_id):
            result = _execute_daily_source_observed(
                source_id,
                path,
                preflight_only=preflight_only,
                reopen_attempt=reopen_attempt,
                day=day,
                scheduled_retry=scheduled_retry,
            )
        _summarize_source(result, started)
        return result
    finally:
        heartbeat.stop()
        if token is not None:
            reset_observation(token)


def _summarize_source(result: dict[str, Any], started: float) -> None:
    timings = result.get("stage_timings_ms")
    seconds = 0.0
    if isinstance(timings, dict):
        seconds = sum(value for value in timings.values() if type(value) is int) / 1000
    if seconds <= 0:
        seconds = time.monotonic() - started
    items = 0
    for key, value in result.items():
        if key.endswith("_count") and type(value) is int and value > 0:
            items += value
    failure = result.get("error_code")
    emit_source_summary(
        status=str(result.get("status") or result.get("outcome") or "FAILED"),
        seconds=seconds,
        items=items,
        nbytes=transferred_bytes(),
        failure_code=failure if isinstance(failure, str) else None,
    )


def _execute_daily_source_observed(
    source_id: str,
    path: str,
    *,
    preflight_only: bool,
    reopen_attempt: int,
    day: str,
    scheduled_retry: bool = False,
) -> dict[str, Any]:
    kill_state = HardKillState()
    claim_clock = DailyStageClock()
    budget: Any = None
    run_id: str | None = None
    try:
        with daily_hard_kill_watchdog(kill_state, seconds=DAILY_SOURCE_WATCHDOG_SECONDS):
            orchestrator, definition = intelligence_runtime.canonical_pilot(
                load_source_definition(Path(path)),
                budget_seconds=DAILY_SOURCE_BUDGET_SECONDS,
            )
            install_stage_memory(orchestrator.store, kill_state)
            budget = getattr(orchestrator, "pilot_budget", None)
            kill_state.budget = budget
            source = definition.extra["intelligence_registry"]
            if source["state"] != "active":
                return _source_outcome(source_id, "SCHEDULE_SUPPRESSED")
            version = source["registry_version"]
            if (
                version not in {2, 3}
                or source["cadence"]["poll_seconds"] != DAILY_POLL_SECONDS
                or identity_hash(source) != reviewed_prod_source_sha256(source_id, version)
            ):
                raise PermissionError("INTELLIGENCE_DAILY_ACTIVE_SOURCE_REQUIRED")
            if preflight_only:
                return _source_outcome(source_id, "READY")
            if scheduled_retry and reopen_attempt != SCHEDULED_RETRY_ATTEMPT:
                raise PermissionError("INTELLIGENCE_DAILY_SCHEDULED_RETRY_INVALID")
            run_id = daily_run_id(source_id, day, reopen_attempt=reopen_attempt)
            # Set before claim so a hang after the RUNNING insert can still be recorded.
            kill_state.run_id = run_id
            bind_context(source_id=source_id, run_id=run_id, attempt=reopen_attempt)
            claim_clock.begin("CLAIM")
            try:
                with stage_scope("CLAIM"):
                    claimed = cast(
                        IntelligenceSnowflakeCheckpoints, orchestrator.store
                    ).claim_daily_run(
                        run_id,
                        source_id,
                        reviewed_prod_source_sha256(source_id, version),
                        reopen=reopen_attempt >= 2,
                    )
            finally:
                claim_clock.end("CLAIM")
            timings_ms = _merged_timings(claim_clock, budget)
            if not claimed:
                kill_state.run_id = None
                return _source_outcome(
                    source_id,
                    "ALREADY_CLAIMED",
                    stage_timings_ms=timings_ms,
                )
            try:
                state = orchestrator.run(definition, tier=Tier.C, run_id=run_id)
            except Exception as error:
                if (
                    isinstance(error, PermissionError)
                    and str(error) == "INTELLIGENCE_PILOT_DEADLINE"
                ):
                    # Budget expiry blocks the run's own writes; record FAILED on a
                    # fresh short connection so the claim is never left RUNNING.
                    terminalize_daily_pilot_deadline(run_id)
                else:
                    _terminalize_claimed_daily_run(run_id, source_id)
                return _failed_from_exception(
                    source_id,
                    error,
                    run_id=run_id,
                    budget=budget,
                    claim_clock=claim_clock,
                    explicit_stage=_budget_daily_stage(budget),
                )
            timings_ms = _merged_timings(claim_clock, budget)
            stage_rows = _stage_timings(budget)
            if state.status is RunStatus.SUCCEEDED:
                return _source_outcome(
                    source_id,
                    "SUCCEEDED",
                    run_id=run_id,
                    stage_timings_ms=timings_ms,
                    stage_timings=stage_rows,
                    item_counts=_item_counts_from_state(state),
                )
            error_code, failed_stage = _failure_from_state(state, budget)
            return _source_outcome(
                source_id,
                "FAILED",
                run_id=run_id,
                error_code=error_code,
                failed_stage=failed_stage,
                stage_timings_ms=timings_ms,
                stage_timings=stage_rows,
            )
    except Exception as error:
        # Codes stay allowlisted. Never copy free-text exception messages into the outcome.
        return _failed_from_exception(
            source_id,
            error,
            run_id=run_id,
            budget=budget,
            claim_clock=claim_clock,
            explicit_stage="CLAIM",
        )


def open_entrez_daily_io(settings: Any) -> tuple[Any, Any, Any]:
    """PROD store and Snowflake checkpoint ledger for a registered Entrez daily run.

    Draft sources never reach this function. The store's write method is the same
    MERGE path the RSS load stage uses. Entrez may bind the raw lease for an
    ``entrez-efetch-v1`` capture, but that lease commits and releases
    ``INTELLIGENCE_WRITE_GUARD`` before the request and artifact inserts. Response
    bytes are not written while the lease guard is held.
    """
    if settings.topx_env != "prod" or not settings.intelligence_daily_enabled:
        raise PermissionError("INTELLIGENCE_DAILY_PROD_REQUIRED")
    budget = intelligence_runtime.PilotBudget(
        seconds=PUBMED_WALK_DEADLINE_SECONDS,
        request_limit=5,
    )

    @contextmanager
    def factory() -> Iterator[Any]:
        note_step_deadline()
        budget.remaining()
        with connect(SnowflakeSettings()) as raw:
            try:
                yield intelligence_runtime._Connection(raw, budget)
            finally:
                note_step_deadline()

    document = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    policies: dict[str, NativeMetadataPolicy] = {}
    for receipt in document["receipts"]:
        native = receipt["native_policy"]
        policies[receipt["source_id"]] = NativeMetadataPolicy(
            policy_ref=native["policy_ref"],
            source_sha256=native["source_sha256"],
            inventory=frozenset(native["inventory"]),
            permitted_paths=frozenset(native["permitted_paths"]),
            required_paths=frozenset(native["required_paths"]),
            published_path=native["published_path"],
            published_format=native["published_format"],
            updated_path=native.get("updated_path"),
            updated_format=native.get("updated_format", "iso8601"),
        )
    store = IntelligenceStore(
        connection_factory=factory,
        retention_allowed=lambda ref: str(ref).endswith("metadata-raw-30d-v1"),
        native_policy_lookup=lambda sid, version: policies[sid],
        settings=settings,
    )
    retention = FeedRawRetention(
        SnowflakeRawLedger(factory, "PROD"),
        environment="PROD",
        source_lookup=store.lookup_source,
        policy_lookup=lambda source: source["access_use"]["content_retention_policy_ref"],
    )
    checkpoints = IntelligenceSnowflakeCheckpoints(retention, connection_factory=factory)
    return store, checkpoints, budget


def _pubmed_alarm(_signum: int, _frame: object) -> None:
    raise TimeoutError


class _PubMedDeadline:
    """Wall clock for one PubMed walk.

    The one-shot alarm is re-armed from the main thread around each step. A
    helper thread arms it again after the deadline so a connector that cleared
    the timer cannot leave the next blocking call unbounded. A handler the
    connector replaces for the duration of one query is not restored from this
    thread; the parent process kill is that bound.
    """

    def __init__(self, seconds: float) -> None:
        self.deadline = time.monotonic() + seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start only after the caller has installed the SIGALRM handler."""
        self._thread = spawn_observed(self._enforce, name="pubmed-walk-deadline")

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def checkpoint(self) -> None:
        if self.remaining() <= 0:
            raise TimeoutError
        alarm = getattr(signal, "setitimer", None)
        if alarm is None:
            return
        signal.signal(signal.SIGALRM, _pubmed_alarm)
        signal.setitimer(signal.ITIMER_REAL, max(self.remaining(), 0.001))

    def _enforce(self) -> None:
        if self._stop.wait(max(0.0, self.remaining())):
            return
        while not self._stop.is_set():
            if hasattr(signal, "setitimer"):
                try:
                    signal.setitimer(signal.ITIMER_REAL, 0.01)
                except Exception:
                    return
            if self._stop.wait(0.05):
                return

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(0.2)
        if hasattr(signal, "setitimer"):
            signal.setitimer(signal.ITIMER_REAL, 0)


@contextmanager
def _pubmed_walk_deadline(seconds: float) -> Iterator[None]:
    """Interrupt a hung PubMed walk so the daily job can return the RSS payload."""
    deadline = _PubMedDeadline(seconds)
    token = bind_step_deadline(deadline)
    alarm = getattr(signal, "SIGALRM", None)
    previous = signal.signal(alarm, _pubmed_alarm) if alarm is not None else None
    deadline.start()
    try:
        deadline.checkpoint()
        yield
    finally:
        reset_step_deadline(token)
        deadline.close()
        if alarm is not None and previous is not None:
            signal.signal(alarm, previous)


def _wait_bounded(fn: Callable[..., None], *args: Any, seconds: float) -> None:
    """Run ``fn`` and return when it finishes or ``seconds`` elapses."""
    finished = threading.Event()

    def attempt() -> None:
        try:
            fn(*args)
        finally:
            finished.set()

    spawn_observed(attempt, name="pubmed-bounded-step")
    finished.wait(seconds)


def _pubmed_http_status_value(status: object) -> int | None:
    if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
        return None
    return status


def _pubmed_http_status(error: BaseException) -> int | None:
    return _pubmed_http_status_value(getattr(error, "http_status", None))


def _pubmed_diagnostic_code(error: BaseException) -> str:
    """Allowlisted code, or PUBMED_DAILY_FAILED when the error has none.

    TimeoutError is the walk alarm. Its message is never copied.
    """
    if isinstance(error, TimeoutError):
        return "FEED_TIMEOUT"
    code = allowlisted_error_code(error)
    if code.startswith("UNCLASSIFIED_"):
        return PUBMED_DAILY_FAILED
    return code


def _dbapi_diagnostic(error: BaseException) -> dict[str, int | str]:
    """Integer errno and 5-character sqlstate, and only when both are present."""
    number = getattr(error, "errno", None)
    state = getattr(error, "sqlstate", None)
    if isinstance(number, bool) or not isinstance(number, int):
        return {}
    if number < 0 or number > _MAX_DBAPI_ERRNO:
        return {}
    if not isinstance(state, str) or _SQLSTATE.fullmatch(state) is None:
        return {}
    return {"errno": number, "sqlstate": state}


def _bounded_exception_class(error: BaseException) -> str:
    name = type(error).__name__
    if _BOUNDED_EXCEPTION_CLASS.fullmatch(name):
        return name
    return "Exception"


def _pubmed_failure_detail(error: BaseException, http_status: int | None) -> dict[str, Any]:
    """Checkpoint fields for one PubMed failure. Messages and SQL text stay out."""
    detail: dict[str, Any] = {}
    status = _pubmed_http_status_value(http_status)
    if status is not None:
        detail["http_status"] = status
    if _pubmed_diagnostic_code(error) != PUBMED_DAILY_FAILED:
        return detail
    detail["exception_class"] = _bounded_exception_class(error)
    detail.update(_dbapi_diagnostic(error))
    step = current_pubmed_step()
    if step is not None:
        detail["step"] = step
    return detail


def _bounded_checkpoint_detail(detail: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only the allowlisted diagnostic keys. Drop anything else."""
    if not isinstance(detail, dict):
        return {}
    clean: dict[str, Any] = {}
    exception_class = detail.get("exception_class")
    if isinstance(exception_class, str) and _BOUNDED_EXCEPTION_CLASS.fullmatch(exception_class):
        clean["exception_class"] = exception_class
    number = detail.get("errno")
    state = detail.get("sqlstate")
    if (
        isinstance(number, int)
        and not isinstance(number, bool)
        and 0 <= number <= _MAX_DBAPI_ERRNO
        and isinstance(state, str)
        and _SQLSTATE.fullmatch(state)
    ):
        clean["errno"] = number
        clean["sqlstate"] = state
    step = detail.get("step")
    if isinstance(step, str) and step in PUBMED_PIPELINE_STEPS:
        clean["step"] = step
    status = _pubmed_http_status_value(detail.get("http_status"))
    if status is not None:
        clean["http_status"] = status
    return clean


def _save_claimed_pubmed_failures(
    checkpoints: Any,
    claimed: list[tuple[str, str]],
    error_code: str,
    detail: dict[str, Any],
) -> None:
    for run_id, source_id in claimed:
        with suppress(Exception):
            fail_claimed_pubmed_run(
                checkpoints,
                run_id,
                source_id,
                code=error_code,
                detail=detail,
            )


def fail_claimed_pubmed_run(
    checkpoints: Any,
    run_id: str,
    source_id: str,
    *,
    code: str = PUBMED_DAILY_FAILED,
    http_status: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Save FAILED for one claimed PubMed run. RSS recovery does not accept these ids."""
    if source_id not in SOURCE_ORDER:
        raise PermissionError("INTELLIGENCE_DAILY_SOURCE_SELECTION_INVALID")
    if code == PUBMED_DAILY_FAILED or _ALLOWLISTED_ERROR_CODE.fullmatch(code):
        diagnostic = code
    else:
        diagnostic = PUBMED_DAILY_FAILED
    stored = _bounded_checkpoint_detail(detail)
    if "http_status" not in stored:
        status = _pubmed_http_status_value(http_status)
        if status is not None:
            stored["http_status"] = status
    checkpoints.save(
        RunState(
            ingestion_run_id=run_id,
            resource_key=source_id,
            source_definition_version=1,
            tier=Tier.C,
            status=RunStatus.FAILED,
            stages=[
                StageCheckpoint(
                    stage=Stage.LOAD,
                    status=StageStatus.FAILED,
                    failure_category=FailureCategory.PROCESS,
                    redacted_diagnostic_code=diagnostic,
                    detail=stored,
                )
            ],
        )
    )


def _pubmed_error_class(error: BaseException) -> str:
    return _bounded_exception_class(error)


def _log_pubmed_failure(
    source_id: str,
    error_class: str,
    *,
    error_code: str | None = None,
    http_status: int | None = None,
    daily_attempt: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """One line: source id, FAILED, class, and the redacted code. No message text."""
    safe_source = source_id if source_id in SOURCE_ORDER else "unknown"
    safe_class = error_class if _BOUNDED_EXCEPTION_CLASS.fullmatch(error_class) else "Exception"
    payload: dict[str, Any] = {
        "error_class": safe_class,
        "source_id": safe_source,
        "status": "FAILED",
    }
    if (
        isinstance(daily_attempt, int)
        and not isinstance(daily_attempt, bool)
        and 2 <= daily_attempt <= MAX_DAILY_ATTEMPTS
    ):
        payload["daily_attempt"] = daily_attempt
    if error_code == PUBMED_DAILY_FAILED or (
        isinstance(error_code, str) and _ALLOWLISTED_ERROR_CODE.fullmatch(error_code)
    ):
        payload["error_code"] = error_code
    status = _pubmed_http_status_value(http_status)
    if status is not None:
        payload["http_status"] = status
    if error_code == PUBMED_DAILY_FAILED:
        diagnostic = _bounded_checkpoint_detail(detail)
        diagnostic.pop("http_status", None)
        payload.update(diagnostic)
    line = DAILY_OUTCOME_LOG_PREFIX + json.dumps(payload, separators=(",", ":"), sort_keys=True)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _walk_registered_entrez_daily(
    settings: Any,
    day: str,
    *,
    preflight_only: bool,
    reopen_attempt: int = 1,
    only_source_id: str | None = None,
    scheduled_retry: bool = False,
) -> list[dict[str, Any]]:
    """Run PubMed when both sources are active and pinned. Drafts do not fetch or write.

    Each source gets its own daily_run_id and claim_daily_run, with the same attempt
    rules as the RSS sources. A PubMed error is saved FAILED and does not escape, so
    the RSS payload already built by the caller is unchanged. ``only_source_id``
    claims and walks that one PubMed source.
    """
    claimed: list[tuple[str, str]] = []
    checkpoints: Any = None
    tracked = (only_source_id,) if only_source_id in SOURCE_ORDER else SOURCE_ORDER
    logged_attempt = reopen_attempt if reopen_attempt >= 2 else None
    try:
        if scheduled_retry and reopen_attempt != SCHEDULED_RETRY_ATTEMPT:
            raise PermissionError("INTELLIGENCE_DAILY_SCHEDULED_RETRY_INVALID")
        with _pubmed_walk_deadline(PUBMED_WALK_DEADLINE_SECONDS):
            pins = intelligence_runtime.PROD_DAILY_SOURCE_SHA256
            if only_source_id is None:
                sources = registered_entrez_sources(pins)
            else:
                sources = registered_entrez_sources(pins, only_source_id=only_source_id)
            if not sources or preflight_only:
                return []
            store, checkpoints, budget = open_entrez_daily_io(settings)
            run_ids: dict[str, str] = {}
            for source in sources:
                source_id = source["source_id"]
                run_id = daily_run_id(source_id, day, reopen_attempt=reopen_attempt)
                bind_context(source_id=source_id, run_id=run_id, attempt=reopen_attempt)
                if not checkpoints.claim_daily_run(
                    run_id,
                    source_id,
                    identity_hash(source),
                    reopen=reopen_attempt >= 2,
                ):
                    continue
                claimed.append((run_id, source_id))
                run_ids[source_id] = run_id
            if not run_ids:
                if only_source_id in SOURCE_ORDER:
                    return [
                        {
                            "source_id": only_source_id,
                            "status": "ALREADY_CLAIMED",
                            "error_class": "PermissionError",
                        }
                    ]
                return []
            walk_clock = DailyStageClock()
            with stage_scope("PUBMED"), step_span("pubmed.walk"):
                walk_clock.begin("FETCH")
                try:
                    execute_registered_entrez_daily(
                        pinned=pins,
                        sender=live_entrez_get,
                        settings=settings,
                        budget=budget,
                        checkpoints=checkpoints,
                        store=store,
                        today=datetime.fromisoformat(day).date(),
                        run_id=next(iter(run_ids.values())),
                        fetched_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        clock=time.monotonic,
                        sleep=time.sleep,
                        sources=sources,
                        run_ids=run_ids,
                        only_source_id=only_source_id,
                    )
                finally:
                    walk_clock.end("FETCH")
            if not scheduled_retry:
                return []
            timings = walk_clock.snapshot_ms()
            return [
                {
                    "source_id": source_id,
                    "status": "SUCCEEDED",
                    "stage_timings_ms": timings,
                }
                for source_id in run_ids
            ]
    except Exception as error:
        if isinstance(error, PermissionError) and str(error) == _REOPEN_PRIOR_NOT_FAILED:
            raise
        error_class = _pubmed_error_class(error)
        error_code = _pubmed_diagnostic_code(error)
        http_status = _pubmed_http_status(error)
        detail = _pubmed_failure_detail(error, http_status)
        if checkpoints is not None and claimed:
            _wait_bounded(
                _save_claimed_pubmed_failures,
                checkpoints,
                claimed,
                error_code,
                detail,
                seconds=PUBMED_FAIL_SAVE_SECONDS,
            )
        source_ids = [source_id for _run_id, source_id in claimed] or list(tracked)
        rows: list[dict[str, Any]] = []
        for source_id in source_ids:
            row: dict[str, Any] = {
                "source_id": source_id,
                "status": "FAILED",
                "error_class": error_class,
                "error_code": error_code,
            }
            if http_status is not None:
                row["http_status"] = http_status
            if error_code == PUBMED_DAILY_FAILED:
                for key in ("exception_class", "errno", "sqlstate", "step"):
                    if key in detail:
                        row[key] = detail[key]
            rows.append(row)
            _log_pubmed_failure(
                source_id,
                error_class,
                error_code=error_code,
                http_status=http_status,
                daily_attempt=logged_attempt,
                detail=detail,
            )
        return rows


def _pubmed_walk_process(spec: dict[str, Any], queue: Any) -> None:
    """Child entry. A test hang ignores SIGALRM so only the parent kill stops it."""
    prepare_worker(spec)
    try:
        if os.environ.get("ATLAS_PUBMED_WALK_HANG") == "swallow-alarm":
            alarm = getattr(signal, "SIGALRM", None)
            if alarm is not None:
                signal.signal(alarm, signal.SIG_IGN)
            time.sleep(3600)
            return
        named = spec.get("only_source_id")
        rows = _walk_registered_entrez_daily(
            pipeline_settings.PipelineSettings(),
            str(spec["day"]),
            preflight_only=bool(spec["preflight_only"]),
            reopen_attempt=int(spec["reopen_attempt"]),
            only_source_id=named if isinstance(named, str) else None,
            scheduled_retry=bool(spec.get("scheduled_retry")),
        )
        queue.put({"ok": True, "rows": rows})
    except PermissionError as error:
        if str(error) == _REOPEN_PRIOR_NOT_FAILED:
            queue.put({"ok": False, "rejected": _REOPEN_PRIOR_NOT_FAILED})
            return
        queue.put({"ok": False, "error_class": _pubmed_error_class(error)})
    except Exception as error:
        queue.put({"ok": False, "error_class": _pubmed_error_class(error)})
    finally:
        shutdown_daily_logs()


def _record_isolated_pubmed_failure(
    day: str,
    reopen_attempt: int,
    source_ids: tuple[str, ...] = SOURCE_ORDER,
) -> None:
    """FAILED save on a new session after the walk process is killed.

    The parent does not know which runs the child claimed or finished, so it
    fails only rows still RUNNING and never inserts one.
    """
    settings = pipeline_settings.PipelineSettings()
    _store, checkpoints, _budget = open_entrez_daily_io(settings)
    for source_id in source_ids:
        if source_id not in SOURCE_ORDER:
            continue
        run_id = daily_run_id(source_id, day, reopen_attempt=reopen_attempt)
        with suppress(Exception):
            checkpoints.fail_running_daily_run(run_id, PUBMED_DAILY_FAILED)


def _pubmed_timeout_rows(
    day: str,
    reopen_attempt: int,
    source_ids: tuple[str, ...] = SOURCE_ORDER,
) -> list[dict[str, str]]:
    _wait_bounded(
        _record_isolated_pubmed_failure,
        day,
        reopen_attempt,
        source_ids,
        seconds=PUBMED_FAIL_SAVE_SECONDS,
    )
    logged_attempt = reopen_attempt if reopen_attempt >= 2 else None
    rows = [
        {"source_id": source_id, "status": "FAILED", "error_class": "TimeoutError"}
        for source_id in source_ids
        if source_id in SOURCE_ORDER
    ]
    for row in rows:
        _log_pubmed_failure(row["source_id"], row["error_class"], daily_attempt=logged_attempt)
    return rows


def _isolate_pubmed_walk(
    settings: Any,
    day: str,
    *,
    preflight_only: bool,
    reopen_attempt: int = 1,
    only_source_id: str | None = None,
    scheduled_retry: bool = False,
) -> list[dict[str, Any]]:
    """Run the PubMed walk in a child. Kill it when the wall clock expires.

    ``settings`` is unused in the child; the child loads process settings. The
    argument keeps the same signature as the in-process walk.
    """
    del settings
    pins = intelligence_runtime.PROD_DAILY_SOURCE_SHA256
    if only_source_id is None:
        sources = registered_entrez_sources(pins)
    else:
        sources = registered_entrez_sources(pins, only_source_id=only_source_id)
    if not sources or preflight_only:
        return []
    tracked = (only_source_id,) if only_source_id in SOURCE_ORDER else SOURCE_ORDER
    ctx = multiprocessing.get_context("spawn")
    result_queue: Any = ctx.Queue()
    stage_queue: Any = None
    child_spec: dict[str, Any] = {
        "day": day,
        "preflight_only": preflight_only,
        "reopen_attempt": reopen_attempt,
        "only_source_id": only_source_id,
        "scheduled_retry": scheduled_retry,
    }
    with suppress(Exception):
        child_spec["_trace"] = carrier_from_current()
        stage_queue = ctx.Queue(maxsize=32)
        child_spec["_stage_queue"] = stage_queue
    process = ctx.Process(
        target=_pubmed_walk_process,
        args=(child_spec, result_queue),
        daemon=False,
    )
    process.start()
    heartbeat_stop = threading.Event()
    heartbeat_thread = start_parent_stage_heartbeat(
        process,
        stage_queue,
        only_source_id or "pubmed",
        heartbeat_stop,
        name="intelligence-daily-pubmed-heartbeat",
    )
    try:
        process.join(PUBMED_WALK_DEADLINE_SECONDS)
        if process.is_alive():
            process.kill()
            process.join(PUBMED_KILL_JOIN_SECONDS)
            return _pubmed_timeout_rows(day, reopen_attempt, tracked)
        if process.exitcode != 0:
            return _pubmed_timeout_rows(day, reopen_attempt, tracked)
        try:
            payload = result_queue.get(timeout=5)
        except Empty:
            return _pubmed_timeout_rows(day, reopen_attempt, tracked)
        if isinstance(payload, dict) and payload.get("rejected") == _REOPEN_PRIOR_NOT_FAILED:
            raise PermissionError(_REOPEN_PRIOR_NOT_FAILED)
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            error_class = "TimeoutError"
            if isinstance(payload, dict):
                reported = payload.get("error_class")
                if isinstance(reported, str):
                    error_class = reported
            logged_attempt = reopen_attempt if reopen_attempt >= 2 else None
            rows = [
                {"source_id": source_id, "status": "FAILED", "error_class": error_class}
                for source_id in tracked
            ]
            for row in rows:
                _log_pubmed_failure(
                    row["source_id"], row["error_class"], daily_attempt=logged_attempt
                )
            return rows
        found = payload.get("rows")
        if isinstance(found, list):
            return found
        return []
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(1)
        if process.is_alive():
            process.kill()
            process.join(PUBMED_KILL_JOIN_SECONDS)
        result_queue.close()
        result_queue.cancel_join_thread()
        if stage_queue is not None:
            with suppress(Exception):
                stage_queue.close()
        process.close()


def daily_source_selection(
    source_ids: tuple[str, ...] | list[str] | None,
    *,
    reopen_attempt: int,
) -> frozenset[str] | None:
    """Return approved sources to run, or None when every approved source runs.

    A re-run (attempt >= 2) must name 1 to 5 approved daily sources before any
    warehouse connection. ``all`` and unknown ids are rejected. Omitted sources
    are not claimed. A PubMed id is accepted only for one source on attempt 2
    or 3. Attempt 4 and higher is refused.
    """
    if reopen_attempt < 1:
        raise ValueError("reopen_attempt must be at least 1")
    if reopen_attempt > MAX_DAILY_ATTEMPTS:
        raise PermissionError("INTELLIGENCE_DAILY_ATTEMPT_CAP")
    selected = tuple(source_ids or ())
    if not selected:
        if reopen_attempt >= 2:
            raise PermissionError("INTELLIGENCE_DAILY_REOPEN_SOURCE_REQUIRED")
        return None
    pubmed = [source_id for source_id in selected if source_id in SOURCE_ORDER]
    if (
        len(selected) > MAX_DAILY_SOURCE_SELECTION
        or len(set(selected)) != len(selected)
        or any(
            source_id not in PROD_SOURCE_DEFINITIONS and source_id not in SOURCE_ORDER
            for source_id in selected
        )
        or (pubmed and (reopen_attempt < 2 or len(selected) != 1))
    ):
        raise PermissionError("INTELLIGENCE_DAILY_SOURCE_SELECTION_INVALID")
    return frozenset(selected)


def _retry_failed_rss_once(
    results: list[dict[str, Any]], *, day: str, job_started: float
) -> list[dict[str, Any]]:
    updated = list(results)
    for index, row in enumerate(updated):
        if row.get("outcome") != "FAILED" or not _retriable_same_day_failure(row.get("error_code")):
            continue
        source_id = row.get("source_id")
        if not isinstance(source_id, str):
            continue
        path = PROD_SOURCE_DEFINITIONS.get(source_id)
        if path is None:
            continue
        if not _retry_within_job_deadline(job_started, RSS_RETRY_CAP_SECONDS):
            continue
        replacement = execute_daily_source(
            source_id,
            path,
            preflight_only=False,
            reopen_attempt=SCHEDULED_RETRY_ATTEMPT,
            day=day,
            scheduled_retry=True,
        )
        replacement = {**replacement, "daily_attempt": SCHEDULED_RETRY_ATTEMPT}
        _log_daily_outcome(replacement)
        updated[index] = replacement
    return updated


def _log_pubmed_retry_success(source_id: str, stage_timings_ms: dict[str, int]) -> None:
    """Record a PubMed retry that returned no failure row, with the walk timings."""
    timings = _bounded_timings(stage_timings_ms)
    _log_daily_outcome(
        {
            "source_id": source_id,
            "outcome": "SUCCEEDED",
            "status": "COMPLETED",
            "failed_stage": None,
            "stage_timings_ms": timings if timings else None,
            "daily_attempt": SCHEDULED_RETRY_ATTEMPT,
        }
    )


def _log_scheduled_retry_skipped(source_id: str, permission_code: str) -> None:
    """One structured warning. The permission text is kept only when it is a code."""
    safe_source = (
        source_id
        if source_id in SOURCE_ORDER or source_id in PROD_SOURCE_DEFINITIONS
        else "unknown"
    )
    payload: dict[str, Any] = {
        "code": SCHEDULED_RETRY_SKIPPED,
        "daily_attempt": SCHEDULED_RETRY_ATTEMPT,
        "source_id": safe_source,
    }
    if _ALLOWLISTED_ERROR_CODE.fullmatch(permission_code):
        payload["permission_code"] = permission_code
    sys.stdout.write(
        RETRY_SKIPPED_LOG_PREFIX + json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"
    )
    sys.stdout.flush()


def _retry_failed_pubmed_once(
    rows: list[dict[str, Any]],
    walker: Callable[..., list[dict[str, Any]]],
    settings: Any,
    day: str,
    *,
    job_started: float,
) -> list[dict[str, Any]]:
    """Retry each failed PubMed source alone so a success is not an empty walk."""
    failed_ids = [
        row["source_id"]
        for row in rows
        if row.get("status") == "FAILED"
        and row.get("source_id") in SOURCE_ORDER
        and _retriable_same_day_failure(row.get("error_code"))
    ]
    by_id = {row.get("source_id"): row for row in rows}
    ordered = [source_id for source_id in SOURCE_ORDER if source_id in failed_ids]
    recorded: list[dict[str, Any]] = []
    for source_id in ordered:
        if not _retry_within_job_deadline(job_started, PUBMED_RETRY_CAP_SECONDS):
            original = by_id.get(source_id)
            if isinstance(original, dict):
                recorded.append(original)
            continue
        try:
            retried = walker(
                settings,
                day,
                preflight_only=False,
                reopen_attempt=SCHEDULED_RETRY_ATTEMPT,
                only_source_id=source_id,
                scheduled_retry=True,
            )
        except PermissionError as error:
            if str(error) != _REOPEN_PRIOR_NOT_FAILED:
                _log_scheduled_retry_skipped(source_id, str(error))
                original = by_id.get(source_id)
                if isinstance(original, dict):
                    recorded.append(original)
                continue
            retried = [
                {
                    "source_id": source_id,
                    "status": "FAILED",
                    "error_class": "PermissionError",
                    "error_code": _REOPEN_PRIOR_NOT_FAILED,
                }
            ]
            _log_pubmed_failure(
                source_id,
                "PermissionError",
                error_code=_REOPEN_PRIOR_NOT_FAILED,
                daily_attempt=SCHEDULED_RETRY_ATTEMPT,
            )
        if not retried or all(row.get("status") == "SUCCEEDED" for row in retried):
            timings: dict[str, int] = {}
            for row in retried:
                found = row.get("stage_timings_ms")
                if isinstance(found, dict):
                    timings = _bounded_timings(found)
            _log_pubmed_retry_success(source_id, timings)
            continue
        recorded.extend({**row, "daily_attempt": SCHEDULED_RETRY_ATTEMPT} for row in retried)
    return recorded


def run_production_daily(
    *,
    preflight_only: bool = False,
    reopen_attempt: int = 1,
    source_ids: tuple[str, ...] | list[str] | None = None,
    scheduled_retry: bool = False,
) -> dict[str, Any]:
    """Run each accepted active source for this UTC day.

    This is a bounded entry point for the existing DigitalOcean job platform,
    not a scheduler. Disabled execution performs no warehouse/provider I/O.
    Each source runs in its own process so one hard kill stops only that source.
    A source selector skips the rest with SKIPPED_NOT_SELECTED and does not
    claim them. Re-run attempts require that selector. A PubMed re-run names one
    PubMed source and does not run the RSS sources. Only the scheduled full run
    (``scheduled_retry``) retries each FAILED source once, as attempt 2, after
    the other sources finish, and only when that retry's cap still fits under
    the job deadline measured from this function's start. The first pass is
    not shortened to make a retry fit.
    """
    # Selector checks precede settings and any Snowflake connection.
    selection = daily_source_selection(source_ids, reopen_attempt=reopen_attempt)
    pubmed_only = None
    if selection is not None and selection <= frozenset(SOURCE_ORDER) and len(selection) == 1:
        pubmed_only = next(iter(selection))
    if scheduled_retry and (reopen_attempt != 1 or selection is not None or preflight_only):
        raise PermissionError("INTELLIGENCE_DAILY_SCHEDULED_RETRY_INVALID")
    settings = pipeline_settings.PipelineSettings()
    if not settings.intelligence_daily_enabled:
        return {"status": "DISABLED", "sources": [], "provider_requests": 0}
    if settings.topx_env != "prod":
        raise PermissionError("INTELLIGENCE_DAILY_PROD_REQUIRED")
    already = observation_active()
    token = None if already else activate_observation()
    started = _retry_clock()
    try:
        with job_span():
            return _run_production_daily_observed(
                settings,
                preflight_only=preflight_only,
                reopen_attempt=reopen_attempt,
                selection=selection,
                pubmed_only=pubmed_only,
                started=started,
                scheduled_retry=scheduled_retry,
            )
    finally:
        if token is not None:
            reset_observation(token)


def _failed_source_count(
    results: list[dict[str, Any]],
    pubmed: list[dict[str, Any]],
    *,
    preflight_only: bool,
    reopen_attempt: int,
    pubmed_only: str | None,
) -> int:
    """Count sources that failed. PubMed rows are included when their status failed."""
    count = 0
    for row in results:
        outcome = row.get("outcome")
        failed_outcome = outcome in {"FAILED", "PREFLIGHT_OR_RUNTIME_FAILED"}
        preflight_miss = preflight_only and outcome not in {"READY", "SKIPPED_NOT_SELECTED"}
        claimed_again = reopen_attempt >= 2 and outcome == "ALREADY_CLAIMED"
        if failed_outcome or preflight_miss or claimed_again:
            count += 1
    for row in pubmed:
        pubmed_status = row.get("status")
        if pubmed_status == "FAILED" or (
            pubmed_only is not None and pubmed_status == "ALREADY_CLAIMED"
        ):
            count += 1
    return count


def release_source_memory() -> None:
    """Drop parent allocations between source processes.

    Each source already runs in its own process. ``malloc_trim`` asks glibc to
    return freed arenas to the OS so the next child does not start on top of
    the parent's high-water mark.
    """
    gc.collect()
    if sys.platform != "linux":
        return
    with suppress(OSError, AttributeError):
        ctypes.CDLL("libc.so.6").malloc_trim(0)


def _run_production_daily_observed(
    settings: Any,
    *,
    preflight_only: bool,
    reopen_attempt: int,
    selection: frozenset[str] | None,
    pubmed_only: str | None,
    started: float,
    scheduled_retry: bool = False,
) -> dict[str, Any]:
    day = datetime.now(UTC).date().isoformat()
    results: list[dict[str, Any]] = []
    pubmed: list[dict[str, Any]] = []
    status = "FAILED"
    failure_class: str | None = None
    try:
        for source_id in DAILY_SOURCE_RUN_ORDER:
            path = PROD_SOURCE_DEFINITIONS[source_id]
            if selection is not None and source_id not in selection:
                results.append(_source_outcome(source_id, "SKIPPED_NOT_SELECTED"))
                release_source_memory()
                continue
            results.append(
                execute_daily_source(
                    source_id,
                    path,
                    preflight_only=preflight_only,
                    reopen_attempt=reopen_attempt,
                    day=day,
                )
            )
            release_source_memory()
        for row in results:
            _log_daily_outcome(row)
        walker: Callable[..., list[dict[str, Any]]] | None = None
        if selection is None or pubmed_only is not None:
            walker = _isolate_pubmed_walk if PUBMED_WALK_ISOLATE else _walk_registered_entrez_daily
            pubmed = walker(
                settings,
                day,
                preflight_only=preflight_only,
                reopen_attempt=reopen_attempt,
                only_source_id=pubmed_only,
            )
        if scheduled_retry:
            results = _retry_failed_rss_once(results, day=day, job_started=started)
            if pubmed and walker is not None:
                pubmed = _retry_failed_pubmed_once(
                    pubmed, walker, settings, day, job_started=started
                )
        failed = any(row["outcome"] in {"FAILED", "PREFLIGHT_OR_RUNTIME_FAILED"} for row in results)
        if pubmed_only is not None and any(
            row.get("status") in {"FAILED", "ALREADY_CLAIMED"} for row in pubmed
        ):
            failed = True
        if preflight_only and any(
            row["outcome"] not in {"READY", "SKIPPED_NOT_SELECTED"} for row in results
        ):
            failed = True
        # A second reopen finds the attempt row and must not look like a new success.
        if reopen_attempt >= 2 and any(row["outcome"] == "ALREADY_CLAIMED" for row in results):
            failed = True
        status = "FAILED" if failed else "SUCCEEDED"
        payload: dict[str, Any] = {
            "status": status,
            "day": day,
            "preflight_only": preflight_only,
            "reopen_attempt": reopen_attempt,
            "sources": results,
        }
        if pubmed:
            payload["pubmed"] = pubmed
        return payload
    except BaseException as exc:
        failure_class = type(exc).__name__
        status = "FAILED"
        raise
    finally:
        emit_run_summary(
            status=status,
            seconds=_retry_clock() - started,
            sources=len(results) + len(pubmed),
            failed=_failed_source_count(
                results,
                pubmed,
                preflight_only=preflight_only,
                reopen_attempt=reopen_attempt,
                pubmed_only=pubmed_only,
            ),
            failure_class=failure_class,
        )


@dataclass(frozen=True)
class PollPreparation:
    source_id: str
    outcome: str
    definition: SourceDefinition | None = None


def prepare_daily_sources(
    selection: dict[str, Any],
    *,
    expected_selection_sha256: str,
    registry_versions: dict[str, int],
    registry_lookup: Callable[[str, int], dict[str, Any]],
    retention_allowed: Callable[[str], bool],
    artifact_policy: str,
) -> list[PollPreparation]:
    """Prepare each eligible source independently, preserving explicit deferrals.

    The trusted caller supplies the reviewed selection digest, authoritative
    registry lookup and actual retention policy. Selection is not activation.
    Policy failures on one source do not prevent preparation of another source.
    """
    if (
        identity_hash(selection) != expected_selection_sha256
        or selection.get("contract_version") != "intelligence-selection-v1"
        or selection.get("poll_seconds") != DAILY_POLL_SECONDS
        or not artifact_policy
    ):
        raise ValueError("INTELLIGENCE_SELECTION_INVALID")
    entries = selection.get("sources")
    if not isinstance(entries, list) or not entries:
        raise ValueError("INTELLIGENCE_SELECTION_INVALID")
    ids = [entry.get("source_id") for entry in entries if isinstance(entry, dict)]
    if (
        len(ids) != len(entries)
        or any(not isinstance(source_id, str) or not source_id for source_id in ids)
        or len(set(ids)) != len(ids)
        or any(entry.get("decision") not in {"approved", "deferred"} for entry in entries)
    ):
        raise ValueError("INTELLIGENCE_SELECTION_INVALID")
    prepared = []
    for entry in entries:
        source_id = entry["source_id"]
        if entry["decision"] == "deferred":
            prepared.append(PollPreparation(source_id, "DEFERRED"))
            continue
        endpoint = entry.get("fetch_location")
        if not endpoint:
            prepared.append(PollPreparation(source_id, "ENDPOINT_UNRESOLVED"))
            continue
        version = registry_versions.get(source_id)
        if type(version) is not int or version < 1:
            prepared.append(PollPreparation(source_id, "REGISTRY_UNRESOLVED"))
            continue
        try:
            source = json.loads(json.dumps(registry_lookup(source_id, version)))
            validate_record("source", source)
            if (
                source["source_id"] != source_id
                or source["registry_version"] != version
                or source["state"] != "active"
                or source["transport"] not in {"rss", "atom"}
                or canonical_url(source["fetch_location"]) != canonical_url(endpoint)
                or source["cadence"]["poll_seconds"] != DAILY_POLL_SECONDS
                or source["approval"]["status"] != "approved"
                or source["trust_review"]["status"] != "approved"
            ):
                prepared.append(PollPreparation(source_id, "REGISTRY_POLICY_MISMATCH"))
                continue
            policy_ref = source["access_use"]["content_retention_policy_ref"]
            if not policy_ref or not retention_allowed(policy_ref):
                prepared.append(PollPreparation(source_id, "RETENTION_UNRESOLVED"))
                continue
        except Exception:
            # External lookup failures must not expose provider or warehouse text.
            prepared.append(PollPreparation(source_id, "REGISTRY_LOOKUP_FAILED"))
            continue
        definition = SourceDefinition(
            resource_key=source_id,
            source_id=source_id,
            dataset_id=source_id,
            definition_version=version,
            adapter_kind=AdapterKind.RSS_ATOM,
            endpoint_template=endpoint,
            deterministic_order_clause="publisher_document_order",
            incremental_strategy="CONTENT_REVISION",
            geography_semantics="Publication; no inferred geography",
            temporal_semantics="Publisher chronology; missing remains unknown",
            artifact_policy=artifact_policy,
            destination="PRESENTATION.INTELLIGENCE_FEED_V",
            expected_refresh_cadence="P1D",
            extra={"intelligence_registry": source},
        )
        prepared.append(PollPreparation(source_id, "READY", definition))
    return prepared
