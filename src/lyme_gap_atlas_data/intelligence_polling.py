"""Prepare a frozen daily source selection for the existing ingestion runner.

No scheduler deployment, source approval, policy creation or warehouse writes.
"""

from __future__ import annotations

import json
import multiprocessing
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty
from typing import Any, cast

from . import settings as pipeline_settings
from .ingestion import intelligence_runtime
from .ingestion.intelligence_checkpoints import IntelligenceSnowflakeCheckpoints
from .ingestion.intelligence_daily_run_ids import daily_run_id
from .ingestion.intelligence_runtime import (
    DAILY_SOURCE_BUDGET_SECONDS,
    DAILY_SOURCE_WATCHDOG_SECONDS,
    PROD_DAILY_SOURCE_SHA256,
    PROD_SOURCE_DEFINITIONS,
)
from .ingestion.source_definition import load_source_definition
from .ingestion.types import AdapterKind, RunStatus, SourceDefinition, Tier
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

DAILY_POLL_SECONDS = 86_400


def _terminalize_claimed_daily_run(run_id: str) -> None:
    from .intelligence_daily_run_recovery import terminalize_stuck_daily_run

    try:
        terminalize_stuck_daily_run(run_id)
    except Exception:
        return


def _stage_timings(budget: Any) -> list[dict[str, Any]]:
    """Redacted per-stage seconds and query counts: no payloads, URLs or error text."""
    report = getattr(budget, "timing_report", None)
    return report() if callable(report) else []


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
    except Exception:
        result_queue.put({"source_id": safe_source, "outcome": "PREFLIGHT_OR_RUNTIME_FAILED"})


def _accept_child_result(source_id: str, payload: Any) -> dict[str, Any]:
    """Keep the child summary. Drop free-text fields the parent must not republish."""
    if not isinstance(payload, dict):
        return {"source_id": source_id, "outcome": "PREFLIGHT_OR_RUNTIME_FAILED"}
    outcome = payload.get("outcome")
    result: dict[str, Any] = {
        "source_id": source_id,
        "outcome": outcome if outcome in _CHILD_OUTCOMES else "PREFLIGHT_OR_RUNTIME_FAILED",
    }
    run_id = payload.get("run_id")
    if isinstance(run_id, str) and len(run_id) == 36 and run_id.strip() == run_id:
        result["run_id"] = run_id
    timings = payload.get("stage_timings")
    if isinstance(timings, list):
        result["stage_timings"] = timings
    exit_code = payload.get("exit_code")
    if isinstance(exit_code, int):
        result["exit_code"] = exit_code
    return result


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
            return {"source_id": source_id, "outcome": "FAILED", "exit_code": code}
        exit_code = process.exitcode
        if exit_code == 0:
            try:
                payload = result_queue.get(timeout=5)
            except Empty:
                return {
                    "source_id": source_id,
                    "outcome": "PREFLIGHT_OR_RUNTIME_FAILED",
                    "exit_code": 0,
                }
            return _accept_child_result(source_id, payload)
        log_source_process_exit(source_id, exit_code)
        code = exit_code if isinstance(exit_code, int) else HARD_KILL_EXIT_CODE
        return {"source_id": source_id, "outcome": "FAILED", "exit_code": code}
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
    try:
        with daily_hard_kill_watchdog(kill_state, seconds=DAILY_SOURCE_WATCHDOG_SECONDS):
            orchestrator, definition = intelligence_runtime.canonical_pilot(
                load_source_definition(Path(path)),
                budget_seconds=DAILY_SOURCE_BUDGET_SECONDS,
            )
            install_stage_memory(orchestrator.store, kill_state)
            kill_state.budget = getattr(orchestrator, "pilot_budget", None)
            source = definition.extra["intelligence_registry"]
            if source["state"] != "active":
                return {"source_id": source_id, "outcome": "SCHEDULE_SUPPRESSED"}
            if (
                source["registry_version"] != 2
                or source["cadence"]["poll_seconds"] != DAILY_POLL_SECONDS
                or identity_hash(source) != PROD_DAILY_SOURCE_SHA256[source_id]
            ):
                raise PermissionError("INTELLIGENCE_DAILY_ACTIVE_SOURCE_REQUIRED")
            if preflight_only:
                return {"source_id": source_id, "outcome": "READY"}
            run_id = daily_run_id(source_id, day, reopen_attempt=reopen_attempt)
            # Set before claim so a hang after the RUNNING insert can still be recorded.
            kill_state.run_id = run_id
            if not cast(IntelligenceSnowflakeCheckpoints, orchestrator.store).claim_daily_run(
                run_id, source_id, PROD_DAILY_SOURCE_SHA256[source_id]
            ):
                kill_state.run_id = None
                return {"source_id": source_id, "outcome": "ALREADY_CLAIMED"}
            budget = getattr(orchestrator, "pilot_budget", None)
            try:
                state = orchestrator.run(definition, tier=Tier.C, run_id=run_id)
            except PermissionError as error:
                if str(error) == "INTELLIGENCE_PILOT_DEADLINE":
                    # Budget expiry blocks the run's own writes; record FAILED on a
                    # fresh short connection so the claim is never left RUNNING.
                    terminalize_daily_pilot_deadline(run_id)
                else:
                    _terminalize_claimed_daily_run(run_id)
                return {
                    "source_id": source_id,
                    "run_id": run_id,
                    "outcome": "FAILED",
                    "stage_timings": _stage_timings(budget),
                }
            except Exception:
                _terminalize_claimed_daily_run(run_id)
                return {
                    "source_id": source_id,
                    "run_id": run_id,
                    "outcome": "FAILED",
                    "stage_timings": _stage_timings(budget),
                }
            return {
                "source_id": source_id,
                "run_id": run_id,
                "outcome": "SUCCEEDED" if state.status is RunStatus.SUCCEEDED else "FAILED",
                "stage_timings": _stage_timings(budget),
            }
    except Exception:
        # Actual stage codes remain in the existing canonical checkpoint.
        # Never emit raw SDK/credential/provider exceptions in job output.
        return {"source_id": source_id, "outcome": "PREFLIGHT_OR_RUNTIME_FAILED"}


def run_production_daily(
    *, preflight_only: bool = False, reopen_attempt: int = 1
) -> dict[str, Any]:
    """Run each exact accepted active source once per UTC day, without retries.

    This is a bounded entry point for the existing DigitalOcean job platform,
    not a scheduler. Disabled execution performs no warehouse/provider I/O.
    Each source runs in its own process so one hard kill stops only that source.
    """
    if reopen_attempt >= 2 and os.environ.get("INTELLIGENCE_DAILY_REOPEN") != "true":
        raise PermissionError("INTELLIGENCE_DAILY_REOPEN_REQUIRED")
    if reopen_attempt < 1:
        raise ValueError("reopen_attempt must be at least 1")
    settings = pipeline_settings.PipelineSettings()
    if not settings.intelligence_daily_enabled:
        return {"status": "DISABLED", "sources": [], "provider_requests": 0}
    if settings.topx_env != "prod":
        raise PermissionError("INTELLIGENCE_DAILY_PROD_REQUIRED")
    day = datetime.now(UTC).date().isoformat()
    results = [
        execute_daily_source(
            source_id,
            path,
            preflight_only=preflight_only,
            reopen_attempt=reopen_attempt,
            day=day,
        )
        for source_id, path in PROD_SOURCE_DEFINITIONS.items()
    ]
    failed = any(row["outcome"] in {"FAILED", "PREFLIGHT_OR_RUNTIME_FAILED"} for row in results)
    if preflight_only and any(row["outcome"] != "READY" for row in results):
        failed = True
    payload: dict[str, Any] = {
        "status": "FAILED" if failed else "SUCCEEDED",
        "day": day,
        "preflight_only": preflight_only,
        "reopen_attempt": reopen_attempt,
        "sources": results,
    }
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
