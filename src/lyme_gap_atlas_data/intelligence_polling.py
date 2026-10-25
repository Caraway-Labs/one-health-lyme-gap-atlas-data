"""Prepare a frozen daily source selection for the existing ingestion runner.

No scheduler deployment, source approval, policy creation or warehouse writes.
"""

from __future__ import annotations

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
from .ingestion.intelligence_daily_run_ids import daily_run_id
from .ingestion.intelligence_entrez import (
    RECEIPT_PATH,
    SOURCE_ORDER,
    execute_registered_entrez_daily,
    live_entrez_get,
    registered_entrez_sources,
)
from .ingestion.intelligence_runtime import (
    DAILY_OPERATOR_STAGE_NAMES,
    DAILY_SOURCE_BUDGET_SECONDS,
    DAILY_SOURCE_WATCHDOG_SECONDS,
    ORCHESTRATOR_STAGE_TO_DAILY,
    PROD_DAILY_SOURCE_SHA256,
    PROD_SOURCE_DEFINITIONS,
    DailyStageClock,
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
    log_source_process_exit,
    source_process_timeout,
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


def _daily_source_child(spec: dict[str, Any], result_queue: Any) -> None:
    """Child entry. A hard kill in this process leaves the parent and siblings alive."""
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
) -> dict[str, Any]:
    """Run ``target`` in a spawned process so ``os._exit`` cannot stop later sources."""
    source_value = spec.get("source_id")
    source_id = source_value if isinstance(source_value, str) else "unknown"
    ctx = multiprocessing.get_context("spawn")
    result_queue: Any = ctx.Queue()
    process = ctx.Process(target=target, args=(spec, result_queue), daemon=False)
    process.start()
    try:
        process.join(timeout)
        if process.is_alive():
            process.kill()
            process.join(5)
            log_source_process_exit(source_id, process.exitcode)
            code = process.exitcode if isinstance(process.exitcode, int) else HARD_KILL_EXIT_CODE
            return _source_outcome(
                source_id,
                "FAILED",
                error_code="INTELLIGENCE_DAILY_HARD_KILL",
                stage_timings_ms={},
                exit_code=code,
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
        if process.is_alive():
            process.kill()
            process.join(5)
        result_queue.close()
        result_queue.cancel_join_thread()
        process.close()


def execute_daily_source(
    source_id: str,
    path: str,
    *,
    preflight_only: bool,
    reopen_attempt: int,
    day: str,
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
) -> dict[str, Any]:
    """Run one daily source in the current process. Tests use this seam."""
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
            if (
                source["registry_version"] != 2
                or source["cadence"]["poll_seconds"] != DAILY_POLL_SECONDS
                or identity_hash(source) != PROD_DAILY_SOURCE_SHA256[source_id]
            ):
                raise PermissionError("INTELLIGENCE_DAILY_ACTIVE_SOURCE_REQUIRED")
            if preflight_only:
                return _source_outcome(source_id, "READY")
            run_id = daily_run_id(source_id, day, reopen_attempt=reopen_attempt)
            # Set before claim so a hang after the RUNNING insert can still be recorded.
            kill_state.run_id = run_id
            claim_clock.begin("CLAIM")
            try:
                claimed = cast(
                    IntelligenceSnowflakeCheckpoints, orchestrator.store
                ).claim_daily_run(run_id, source_id, PROD_DAILY_SOURCE_SHA256[source_id])
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
    MERGE path the RSS load stage uses. The raw-artifact lease still accepts only
    RSS parser versions, so this opener does not bind Entrez response bytes there.
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
        self._thread = threading.Thread(
            target=self._enforce, name="pubmed-walk-deadline", daemon=True
        )
        self._thread.start()

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

    worker = threading.Thread(target=attempt, name="pubmed-bounded-step", daemon=True)
    worker.start()
    finished.wait(seconds)


def _save_claimed_pubmed_failures(checkpoints: Any, claimed: list[tuple[str, str]]) -> None:
    for run_id, source_id in claimed:
        with suppress(Exception):
            fail_claimed_pubmed_run(checkpoints, run_id, source_id)


def fail_claimed_pubmed_run(checkpoints: Any, run_id: str, source_id: str) -> None:
    """Save FAILED for one claimed PubMed run. RSS recovery does not accept these ids."""
    if source_id not in SOURCE_ORDER:
        raise PermissionError("INTELLIGENCE_DAILY_SOURCE_SELECTION_INVALID")
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
                    redacted_diagnostic_code="PUBMED_DAILY_FAILED",
                )
            ],
        )
    )


def _pubmed_error_class(error: BaseException) -> str:
    name = type(error).__name__
    if _EXCEPTION_CLASS_NAME.fullmatch(name):
        return name
    return "Exception"


def _log_pubmed_failure(source_id: str, error_class: str) -> None:
    """One line: source id, FAILED, and the exception class. No message text."""
    safe_source = source_id if source_id in SOURCE_ORDER else "unknown"
    safe_class = error_class if _EXCEPTION_CLASS_NAME.fullmatch(error_class) else "Exception"
    line = DAILY_OUTCOME_LOG_PREFIX + json.dumps(
        {"error_class": safe_class, "source_id": safe_source, "status": "FAILED"},
        separators=(",", ":"),
        sort_keys=True,
    )
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _walk_registered_entrez_daily(
    settings: Any,
    day: str,
    *,
    preflight_only: bool,
    reopen_attempt: int = 1,
) -> list[dict[str, str]]:
    """Run PubMed when both sources are active and pinned. Drafts do not fetch or write.

    Each source gets its own daily_run_id and claim_daily_run, with the same attempt
    rules as the RSS sources. A PubMed error is saved FAILED and does not escape, so
    the RSS payload already built by the caller is unchanged.
    """
    claimed: list[tuple[str, str]] = []
    checkpoints: Any = None
    try:
        with _pubmed_walk_deadline(PUBMED_WALK_DEADLINE_SECONDS):
            pins = intelligence_runtime.PROD_DAILY_SOURCE_SHA256
            sources = registered_entrez_sources(pins)
            if not sources or preflight_only:
                return []
            store, checkpoints, budget = open_entrez_daily_io(settings)
            run_ids: dict[str, str] = {}
            for source in sources:
                source_id = source["source_id"]
                run_id = daily_run_id(source_id, day, reopen_attempt=reopen_attempt)
                if not checkpoints.claim_daily_run(run_id, source_id, identity_hash(source)):
                    continue
                claimed.append((run_id, source_id))
                run_ids[source_id] = run_id
            if not run_ids:
                return []
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
            )
            return []
    except Exception as error:
        error_class = _pubmed_error_class(error)
        if checkpoints is not None and claimed:
            _wait_bounded(
                _save_claimed_pubmed_failures,
                checkpoints,
                claimed,
                seconds=PUBMED_FAIL_SAVE_SECONDS,
            )
        source_ids = [source_id for _run_id, source_id in claimed] or list(SOURCE_ORDER)
        rows = [
            {"source_id": source_id, "status": "FAILED", "error_class": error_class}
            for source_id in source_ids
        ]
        for row in rows:
            _log_pubmed_failure(row["source_id"], row["error_class"])
        return rows


def _pubmed_walk_process(spec: dict[str, Any], queue: Any) -> None:
    """Child entry. A test hang ignores SIGALRM so only the parent kill stops it."""
    if os.environ.get("ATLAS_PUBMED_WALK_HANG") == "swallow-alarm":
        alarm = getattr(signal, "SIGALRM", None)
        if alarm is not None:
            signal.signal(alarm, signal.SIG_IGN)
        time.sleep(3600)
        return
    try:
        rows = _walk_registered_entrez_daily(
            pipeline_settings.PipelineSettings(),
            str(spec["day"]),
            preflight_only=bool(spec["preflight_only"]),
            reopen_attempt=int(spec["reopen_attempt"]),
        )
        queue.put({"ok": True, "rows": rows})
    except Exception as error:
        queue.put({"ok": False, "error_class": _pubmed_error_class(error)})


def _record_isolated_pubmed_failure(day: str, reopen_attempt: int) -> None:
    """FAILED save on a new session after the walk process is killed."""
    settings = pipeline_settings.PipelineSettings()
    _store, checkpoints, _budget = open_entrez_daily_io(settings)
    claimed = [
        (daily_run_id(source_id, day, reopen_attempt=reopen_attempt), source_id)
        for source_id in SOURCE_ORDER
    ]
    _save_claimed_pubmed_failures(checkpoints, claimed)


def _pubmed_timeout_rows(day: str, reopen_attempt: int) -> list[dict[str, str]]:
    _wait_bounded(
        _record_isolated_pubmed_failure,
        day,
        reopen_attempt,
        seconds=PUBMED_FAIL_SAVE_SECONDS,
    )
    rows = [
        {"source_id": source_id, "status": "FAILED", "error_class": "TimeoutError"}
        for source_id in SOURCE_ORDER
    ]
    for row in rows:
        _log_pubmed_failure(row["source_id"], row["error_class"])
    return rows


def _isolate_pubmed_walk(
    settings: Any,
    day: str,
    *,
    preflight_only: bool,
    reopen_attempt: int = 1,
) -> list[dict[str, str]]:
    """Run the PubMed walk in a child. Kill it when the wall clock expires.

    ``settings`` is unused in the child; the child loads process settings. The
    argument keeps the same signature as the in-process walk.
    """
    del settings
    sources = registered_entrez_sources(intelligence_runtime.PROD_DAILY_SOURCE_SHA256)
    if not sources or preflight_only:
        return []
    ctx = multiprocessing.get_context("spawn")
    result_queue: Any = ctx.Queue()
    process = ctx.Process(
        target=_pubmed_walk_process,
        args=(
            {
                "day": day,
                "preflight_only": preflight_only,
                "reopen_attempt": reopen_attempt,
            },
            result_queue,
        ),
        daemon=False,
    )
    process.start()
    try:
        process.join(PUBMED_WALK_DEADLINE_SECONDS)
        if process.is_alive():
            process.kill()
            process.join(5)
            return _pubmed_timeout_rows(day, reopen_attempt)
        if process.exitcode != 0:
            return _pubmed_timeout_rows(day, reopen_attempt)
        try:
            payload = result_queue.get(timeout=5)
        except Empty:
            return _pubmed_timeout_rows(day, reopen_attempt)
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            error_class = "TimeoutError"
            if isinstance(payload, dict):
                reported = payload.get("error_class")
                if isinstance(reported, str):
                    error_class = reported
            rows = [
                {"source_id": source_id, "status": "FAILED", "error_class": error_class}
                for source_id in SOURCE_ORDER
            ]
            for row in rows:
                _log_pubmed_failure(row["source_id"], row["error_class"])
            return rows
        found = payload.get("rows")
        if isinstance(found, list):
            return found
        return []
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
        result_queue.close()
        result_queue.cancel_join_thread()
        process.close()


def daily_source_selection(
    source_ids: tuple[str, ...] | list[str] | None,
    *,
    reopen_attempt: int,
) -> frozenset[str] | None:
    """Return approved sources to run, or None when every approved source runs.

    A reopen (attempt >= 2) must name 1 to 5 approved daily sources before any
    warehouse connection. ``all`` and unknown ids are rejected. Omitted sources
    are not claimed.
    """
    if reopen_attempt < 1:
        raise ValueError("reopen_attempt must be at least 1")
    selected = tuple(source_ids or ())
    if not selected:
        if reopen_attempt >= 2:
            raise PermissionError("INTELLIGENCE_DAILY_REOPEN_SOURCE_REQUIRED")
        return None
    if (
        len(selected) > MAX_DAILY_SOURCE_SELECTION
        or len(set(selected)) != len(selected)
        or any(source_id not in PROD_SOURCE_DEFINITIONS for source_id in selected)
    ):
        raise PermissionError("INTELLIGENCE_DAILY_SOURCE_SELECTION_INVALID")
    return frozenset(selected)


def run_production_daily(
    *,
    preflight_only: bool = False,
    reopen_attempt: int = 1,
    source_ids: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """Run each exact accepted active source once per UTC day, without retries.

    This is a bounded entry point for the existing DigitalOcean job platform,
    not a scheduler. Disabled execution performs no warehouse/provider I/O.
    Each source runs in its own process so one hard kill stops only that source.
    A source selector skips the rest with SKIPPED_NOT_SELECTED and does not
    claim them. Reopen attempts require that selector.
    """
    # Selector checks precede settings and any Snowflake connection.
    selection = daily_source_selection(source_ids, reopen_attempt=reopen_attempt)
    if reopen_attempt >= 2 and os.environ.get("INTELLIGENCE_DAILY_REOPEN") != "true":
        raise PermissionError("INTELLIGENCE_DAILY_REOPEN_REQUIRED")
    settings = pipeline_settings.PipelineSettings()
    if not settings.intelligence_daily_enabled:
        return {"status": "DISABLED", "sources": [], "provider_requests": 0}
    if settings.topx_env != "prod":
        raise PermissionError("INTELLIGENCE_DAILY_PROD_REQUIRED")
    day = datetime.now(UTC).date().isoformat()
    results = []
    for source_id, path in PROD_SOURCE_DEFINITIONS.items():
        if selection is not None and source_id not in selection:
            results.append(_source_outcome(source_id, "SKIPPED_NOT_SELECTED"))
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
    for row in results:
        _log_daily_outcome(row)
    pubmed: list[dict[str, str]] = []
    if selection is None:
        walker = _isolate_pubmed_walk if PUBMED_WALK_ISOLATE else _walk_registered_entrez_daily
        pubmed = walker(settings, day, preflight_only=preflight_only, reopen_attempt=reopen_attempt)
    failed = any(row["outcome"] in {"FAILED", "PREFLIGHT_OR_RUNTIME_FAILED"} for row in results)
    if preflight_only and any(
        row["outcome"] not in {"READY", "SKIPPED_NOT_SELECTED"} for row in results
    ):
        failed = True
    # A second reopen finds the attempt row and must not look like a new success.
    if reopen_attempt >= 2 and any(row["outcome"] == "ALREADY_CLAIMED" for row in results):
        failed = True
    payload: dict[str, Any] = {
        "status": "FAILED" if failed else "SUCCEEDED",
        "day": day,
        "preflight_only": preflight_only,
        "reopen_attempt": reopen_attempt,
        "sources": results,
    }
    if pubmed:
        payload["pubmed"] = pubmed
    return payload


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
