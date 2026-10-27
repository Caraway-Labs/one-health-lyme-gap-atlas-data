"""PubMed backfill windows that never take the daily run's slot or watermark.

A reviewed plan file names the slices. Each run searches both approved PubMed
sources once, fetches at most one page of the union, and stores a cursor under
the resource key ``pubmed-backfill``. ``last_entry_date`` is only read.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, NoReturn
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from ..intelligence_metadata import NativeMetadataPolicy
from ..intelligence_raw_runtime import FeedRawRetention, SnowflakeRawLedger
from ..intelligence_storage import IntelligenceStore
from ..settings import PipelineSettings
from ..sql_sessions import connect
from .intelligence_checkpoints import IntelligenceSnowflakeCheckpoints
from .intelligence_entrez import (
    BATCH_SIZE,
    CONFIG_DIR,
    ENTREZ_DAILY_RESOURCE,
    FIRST_WINDOW_DAYS,
    MAX_ITEMS,
    MAX_REQUESTS,
    MAX_RESPONSE_BYTES,
    MIN_INTERVAL_SECONDS,
    RECEIPT_PATH,
    REQUEST_TIMEOUT_SECONDS,
    SOURCE_ORDER,
    EntrezSender,
    EntryDateLedger,
    RequestBudget,
    RevisionLedger,
    RunLedger,
    _build_item,
    _chunks,
    _EntrezSession,
    _load_policies,
    _load_queries,
    _merge_pmids,
    _parse_efetch,
    _require_run_sources,
    entrez_artifact_id,
    entry_dates_from_ledger,
    live_entrez_get,
    load_suppressions,
    note_pubmed_step,
    partition_pubmed_items,
    prepare_entrez_source_capture,
    registered_entrez_sources,
)
from .intelligence_runtime import PROD_DAILY_SOURCE_SHA256, PilotBudget, _Connection
from .step_deadline import note_step_deadline
from .types import RunState, RunStatus, Stage, StageCheckpoint, StageStatus, Tier

BACKFILL_RESOURCE = "pubmed-backfill"
BACKFILL_NAMESPACE = "atlas:intelligence:pubmed-backfill"
BACKFILL_KIND = "pubmed_backfill_cursor"
SOURCE_RUN_KIND = "pubmed_backfill_source_run"
# Matthew, 2026-10-25 ~11:42 AM MDT: 5 requests and about 200 papers per run.
MATTHEW_APPROVED_REQUEST_LIMIT = MAX_REQUESTS
MATTHEW_APPROVED_ITEM_LIMIT = MAX_ITEMS
ESEARCH_RETMAX = 10_000
MAX_SLICE_DAYS = 30
PLAN_ID_MAX = 48
DENVER = ZoneInfo("America/Denver")
BLACKOUT_START_MINUTE = 17 * 60 + 45
BLACKOUT_END_MINUTE = 18 * 60 + 45
BACKFILL_DIR = CONFIG_DIR / "backfill"
OUTCOME_LOG_PREFIX = "ATLAS_PUBMED_BACKFILL_OUTCOME "
WALK_SECONDS = 180

_PLAN_INVALID = "INTELLIGENCE_PUBMED_BACKFILL_PLAN_INVALID"
_UNAPPROVED = "INTELLIGENCE_PUBMED_BACKFILL_PLAN_UNAPPROVED"
_REQUEST_LIMIT = "INTELLIGENCE_PUBMED_BACKFILL_REQUEST_LIMIT"
_TOO_LONG = "INTELLIGENCE_PUBMED_BACKFILL_SLICE_TOO_LONG"
_OVERLAP = "INTELLIGENCE_PUBMED_BACKFILL_SLICE_OVERLAP"
_UNKNOWN_SLICE = "INTELLIGENCE_PUBMED_BACKFILL_SLICE_UNKNOWN"
_WINDOW = "INTELLIGENCE_PUBMED_BACKFILL_WINDOW_NOT_OLDER"
_WATERMARK = "INTELLIGENCE_PUBMED_BACKFILL_WATERMARK_REQUIRED"
_BLACKOUT = "INTELLIGENCE_PUBMED_BACKFILL_BLACKOUT"
_DAILY_RUNNING = "INTELLIGENCE_PUBMED_BACKFILL_DAILY_RUNNING"
_CURSOR = "INTELLIGENCE_PUBMED_BACKFILL_CURSOR_INVALID"
_TRUNCATED = "INTELLIGENCE_PUBMED_BACKFILL_ESEARCH_TRUNCATED"
_UNREGISTERED = "INTELLIGENCE_PUBMED_BACKFILL_SOURCE_UNREGISTERED"

_PLAN_KEYS = frozenset(
    {
        "plan_id",
        "approved_by",
        "approved_at",
        "approved_request_limit",
        "request_limit",
        "item_limit",
        "sources",
        "slices",
        "batch_size",
        "max_response_bytes",
        "timeout_seconds",
        "min_interval_seconds",
    }
)
_SLICE_KEYS = frozenset({"slice_id", "mindate", "maxdate"})


def _refuse(code: str) -> NoReturn:
    raise PermissionError(code)


def _token(value: object) -> str:
    if not isinstance(value, str) or not value.isascii():
        _refuse(_PLAN_INVALID)
    if not 1 <= len(value) <= PLAN_ID_MAX:
        _refuse(_PLAN_INVALID)
    if value[0] not in "abcdefghijklmnopqrstuvwxyz0123456789":
        _refuse(_PLAN_INVALID)
    if any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in value):
        _refuse(_PLAN_INVALID)
    return value


def in_backfill_blackout(moment: datetime) -> bool:
    """True from 5:45 PM through 6:45 PM America/Denver, inclusive of those minutes."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        _refuse(_PLAN_INVALID)
    local = moment.astimezone(DENVER)
    minute = local.hour * 60 + local.minute
    return BLACKOUT_START_MINUTE <= minute <= BLACKOUT_END_MINUTE


def backfill_run_id(plan_id: str, slice_id: str, attempt: int) -> str:
    """Run id outside the daily namespace. Attempt 1 is the first pass of a slice."""
    if attempt < 1:
        raise ValueError("backfill attempt must be at least 1")
    name = f"{BACKFILL_NAMESPACE}:{_token(plan_id)}:{_token(slice_id)}:attempt-{attempt}"
    return str(uuid5(NAMESPACE_URL, name))


def backfill_source_run_id(plan_id: str, slice_id: str, attempt: int, source_id: str) -> str:
    """Per-source row the existing item writer joins. It is not a daily run id."""
    if source_id not in SOURCE_ORDER:
        _refuse(_UNREGISTERED)
    base = backfill_run_id(plan_id, slice_id, attempt)
    return str(uuid5(NAMESPACE_URL, f"{base}:{source_id}"))


def daily_first_window_start(last_entry_date: date) -> date:
    """Oldest EDAT the daily run's first 30-day window still owns.

    The live watermark is the newest entry date the daily run has admitted.
    Its first window started ``FIRST_WINDOW_DAYS`` before that date. A backfill
    ``maxdate`` has to be strictly older than this start.
    """
    return last_entry_date - timedelta(days=FIRST_WINDOW_DAYS)


def _inclusive_days(mindate: date, maxdate: date) -> int:
    return (maxdate - mindate).days + 1


@dataclass(frozen=True)
class BackfillSlice:
    slice_id: str
    mindate: date
    maxdate: date

    def day_count(self) -> int:
        return _inclusive_days(self.mindate, self.maxdate)


@dataclass(frozen=True)
class BackfillPlan:
    plan_id: str
    request_limit: int
    item_limit: int
    batch_size: int
    max_response_bytes: int
    timeout_seconds: float
    min_interval_seconds: float
    approved_by: str
    approved_at: str
    approved_request_limit: int | None
    slices: tuple[BackfillSlice, ...]

    def find(self, slice_id: str) -> BackfillSlice:
        found = [item for item in self.slices if item.slice_id == slice_id]
        if len(found) != 1:
            _refuse(_UNKNOWN_SLICE)
        return found[0]


@dataclass(frozen=True)
class BackfillCursor:
    retstart: int
    last_pmid: str | None
    slice_complete: bool
    remaining: int | None
    processed_pmids: tuple[str, ...]
    sequence: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "retstart": self.retstart,
            "last_pmid": self.last_pmid,
            "slice_complete": self.slice_complete,
            "remaining": self.remaining,
        }


def _blank_cursor() -> BackfillCursor:
    return BackfillCursor(0, None, False, None, (), 0)


def _positive_int(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _refuse(code)
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _positive_int(value, _PLAN_INVALID)


def _date(value: object) -> date:
    if not isinstance(value, str):
        _refuse(_PLAN_INVALID)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _refuse(_PLAN_INVALID)
    if parsed.isoformat() != value:
        _refuse(_PLAN_INVALID)
    return parsed


def _parse_approved_at(value: str) -> None:
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        _refuse(_PLAN_INVALID)
    if parsed.tzinfo is None:
        _refuse(_PLAN_INVALID)


def load_backfill_plan(plan_id: str, *, root: Path | None = None) -> BackfillPlan:
    """Load one reviewed plan. The id is a filename token, never a free-text window."""
    token = _token(plan_id)
    directory = (root or BACKFILL_DIR).resolve()
    path = (directory / f"{token}.json").resolve()
    if path.parent != directory or not path.is_file():
        _refuse(_PLAN_INVALID)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _refuse(_PLAN_INVALID)
    if not isinstance(document, dict):
        _refuse(_PLAN_INVALID)
    loaded = plan_from_document(document)
    if loaded.plan_id != token:
        _refuse(_PLAN_INVALID)
    return loaded


def plan_from_document(document: Mapping[str, Any]) -> BackfillPlan:
    if set(document) - _PLAN_KEYS:
        _refuse(_PLAN_INVALID)
    plan_id = _token(document.get("plan_id"))
    sources = document.get("sources")
    if sources != list(SOURCE_ORDER):
        _refuse(_UNREGISTERED)
    request_limit = _positive_int(document.get("request_limit"), _REQUEST_LIMIT)
    item_limit = _positive_int(document.get("item_limit"), _PLAN_INVALID)
    batch_size = _positive_int(document.get("batch_size", BATCH_SIZE), _PLAN_INVALID)
    max_bytes = _positive_int(document.get("max_response_bytes", MAX_RESPONSE_BYTES), _PLAN_INVALID)
    timeout_value = document.get("timeout_seconds", REQUEST_TIMEOUT_SECONDS)
    interval_value = document.get("min_interval_seconds", MIN_INTERVAL_SECONDS)
    if isinstance(timeout_value, bool) or not isinstance(timeout_value, int | float):
        _refuse(_PLAN_INVALID)
    if isinstance(interval_value, bool) or not isinstance(interval_value, int | float):
        _refuse(_PLAN_INVALID)
    timeout_seconds = float(timeout_value)
    min_interval = float(interval_value)
    if batch_size > BATCH_SIZE or max_bytes > MAX_RESPONSE_BYTES:
        _refuse(_PLAN_INVALID)
    if timeout_seconds > REQUEST_TIMEOUT_SECONDS or timeout_seconds <= 0:
        _refuse(_PLAN_INVALID)
    if min_interval < MIN_INTERVAL_SECONDS:
        _refuse(_PLAN_INVALID)
    approved_by = document.get("approved_by", "")
    approved_at = document.get("approved_at", "")
    if not isinstance(approved_by, str) or not isinstance(approved_at, str):
        _refuse(_PLAN_INVALID)
    if approved_by and (approved_by.strip() != approved_by or len(approved_by) > 80):
        _refuse(_PLAN_INVALID)
    if any(ord(char) < 32 or ord(char) == 127 for char in approved_by):
        _refuse(_PLAN_INVALID)
    if approved_at:
        _parse_approved_at(approved_at)
    slices_raw = document.get("slices")
    if not isinstance(slices_raw, list) or not slices_raw:
        _refuse(_PLAN_INVALID)
    slices: list[BackfillSlice] = []
    seen: set[str] = set()
    for entry in slices_raw:
        if not isinstance(entry, dict) or set(entry) != _SLICE_KEYS:
            _refuse(_PLAN_INVALID)
        slice_id = _token(entry.get("slice_id"))
        if slice_id in seen:
            _refuse(_PLAN_INVALID)
        seen.add(slice_id)
        mindate = _date(entry.get("mindate"))
        maxdate = _date(entry.get("maxdate"))
        if mindate > maxdate:
            _refuse(_PLAN_INVALID)
        slices.append(BackfillSlice(slice_id, mindate, maxdate))
    plan = BackfillPlan(
        plan_id=plan_id,
        request_limit=request_limit,
        item_limit=item_limit,
        batch_size=batch_size,
        max_response_bytes=max_bytes,
        timeout_seconds=timeout_seconds,
        min_interval_seconds=min_interval,
        approved_by=approved_by,
        approved_at=approved_at,
        approved_request_limit=_optional_int(document.get("approved_request_limit")),
        slices=tuple(slices),
    )
    _validate_geometry(plan)
    return plan


def _validate_geometry(plan: BackfillPlan) -> None:
    if plan.request_limit < 3 or plan.request_limit > MATTHEW_APPROVED_REQUEST_LIMIT:
        _refuse(_REQUEST_LIMIT)
    if plan.item_limit > MATTHEW_APPROVED_ITEM_LIMIT:
        _refuse(_PLAN_INVALID)
    if plan.approved_request_limit is not None and (
        plan.approved_request_limit > MATTHEW_APPROVED_REQUEST_LIMIT
        or plan.request_limit > plan.approved_request_limit
    ):
        _refuse(_REQUEST_LIMIT)
    ordered = sorted(plan.slices, key=lambda item: item.mindate)
    previous: date | None = None
    for item in ordered:
        if item.day_count() > MAX_SLICE_DAYS:
            _refuse(_TOO_LONG)
        if previous is not None and item.mindate <= previous:
            _refuse(_OVERLAP)
        previous = item.maxdate


def validate_backfill_approval(plan: BackfillPlan, environment: str) -> None:
    """PROD refuses a plan Matthew has not signed. DEV may rehearse without that signature."""
    if environment not in {"dev", "prod"}:
        _refuse(_PLAN_INVALID)
    _validate_geometry(plan)
    if environment != "prod":
        return
    if not plan.approved_by or not plan.approved_at or plan.approved_request_limit is None:
        _refuse(_UNAPPROVED)


def planned_request_count(
    plan: BackfillPlan, cursor: BackfillCursor, *, pending: int | None = None
) -> int:
    """Requests this run will make, or the plan cap when the id list is still unknown."""
    if cursor.slice_complete:
        return 2
    remaining = cursor.remaining if pending is None else pending
    if remaining is None:
        return plan.request_limit
    if remaining <= 0:
        return 2
    take = min(remaining, plan.item_limit)
    batches = (take + plan.batch_size - 1) // plan.batch_size
    return min(plan.request_limit, 2 + batches)


def _cursor_from_detail(detail: Mapping[str, Any]) -> BackfillCursor:
    processed = detail.get("processed_pmids")
    retstart = detail.get("retstart")
    last_pmid = detail.get("last_pmid")
    complete = detail.get("slice_complete")
    remaining = detail.get("remaining")
    sequence = detail.get("sequence")
    if (
        detail.get("kind") != BACKFILL_KIND
        or not isinstance(processed, list)
        or isinstance(retstart, bool)
        or not isinstance(retstart, int)
        or not isinstance(complete, bool)
        or isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or sequence < 1
    ):
        _refuse(_CURSOR)
    pmids: list[str] = []
    for pmid in processed:
        if not isinstance(pmid, str) or pmid in pmids:
            _refuse(_CURSOR)
        pmids.append(pmid)
    if retstart != len(pmids):
        _refuse(_CURSOR)
    if pmids:
        if last_pmid != pmids[-1]:
            _refuse(_CURSOR)
    elif last_pmid is not None:
        _refuse(_CURSOR)
    if remaining is not None and (isinstance(remaining, bool) or not isinstance(remaining, int)):
        _refuse(_CURSOR)
    if complete and remaining not in {0, None}:
        _refuse(_CURSOR)
    return BackfillCursor(
        retstart,
        last_pmid if isinstance(last_pmid, str) else None,
        complete,
        remaining if isinstance(remaining, int) else None,
        tuple(pmids),
        sequence,
    )


def _latest_cursor(checkpoints: RunLedger, plan_id: str, slice_id: str) -> BackfillCursor | None:
    best: BackfillCursor | None = None
    for state in checkpoints.list_runs_for_resources((BACKFILL_RESOURCE,)):
        if state.status is not RunStatus.SUCCEEDED or state.resource_key != BACKFILL_RESOURCE:
            continue
        load = state.checkpoint(Stage.LOAD)
        detail = load.detail if load is not None else {}
        if detail.get("plan_id") != plan_id or detail.get("slice_id") != slice_id:
            continue
        cursor = _cursor_from_detail(detail)
        if best is None or cursor.sequence > best.sequence:
            best = cursor
    return best


def _daily_running(checkpoints: RunLedger) -> bool:
    resources = (ENTREZ_DAILY_RESOURCE, *SOURCE_ORDER)
    for state in checkpoints.list_runs_for_resources(resources):
        if state.status is RunStatus.RUNNING and state.resource_key in resources:
            return True
    return False


def _require_watermarks(ledger: EntryDateLedger) -> dict[str, date]:
    found: dict[str, date] = {}
    for source_id in SOURCE_ORDER:
        day = ledger.get(source_id)
        if day is None:
            _refuse(_WATERMARK)
        found[source_id] = day
    return found


def _require_window(item: BackfillSlice, watermarks: Mapping[str, date]) -> None:
    for source_id in SOURCE_ORDER:
        start = daily_first_window_start(watermarks[source_id])
        if item.maxdate >= start:
            _refuse(_WINDOW)


def _fetch_slots(plan: BackfillPlan) -> int:
    return plan.request_limit - 2


def _select_pending(
    ordered: list[tuple[str, tuple[str, ...]]], processed: set[str], plan: BackfillPlan
) -> list[tuple[str, tuple[str, ...]]]:
    pending = [item for item in ordered if item[0] not in processed]
    capacity = _fetch_slots(plan) * plan.batch_size
    return pending[: min(plan.item_limit, capacity)]


def _save_cursor(
    checkpoints: RunLedger,
    *,
    run_id: str,
    plan: BackfillPlan,
    item: BackfillSlice,
    cursor: BackfillCursor,
) -> None:
    detail = {
        "kind": BACKFILL_KIND,
        "plan_id": plan.plan_id,
        "slice_id": item.slice_id,
        "mindate": item.mindate.isoformat(),
        "maxdate": item.maxdate.isoformat(),
        "retstart": cursor.retstart,
        "last_pmid": cursor.last_pmid,
        "slice_complete": cursor.slice_complete,
        "remaining": cursor.remaining,
        "processed_pmids": list(cursor.processed_pmids),
        "sequence": cursor.sequence,
    }
    checkpoints.save(
        RunState(
            ingestion_run_id=run_id,
            resource_key=BACKFILL_RESOURCE,
            source_definition_version=1,
            tier=Tier.C,
            status=RunStatus.SUCCEEDED,
            stages=[StageCheckpoint(stage=Stage.LOAD, status=StageStatus.COMPLETED, detail=detail)],
        )
    )


def _save_source_runs(
    checkpoints: RunLedger,
    *,
    plan: BackfillPlan,
    item: BackfillSlice,
    attempt: int,
) -> dict[str, str]:
    """Write-reference rows. They carry no ``last_entry_date``, so the daily watermark stays put."""
    run_ids: dict[str, str] = {}
    for source_id in SOURCE_ORDER:
        run_id = backfill_source_run_id(plan.plan_id, item.slice_id, attempt, source_id)
        run_ids[source_id] = run_id
        checkpoints.save(
            RunState(
                ingestion_run_id=run_id,
                resource_key=source_id,
                source_definition_version=1,
                tier=Tier.C,
                status=RunStatus.SUCCEEDED,
                stages=[
                    StageCheckpoint(
                        stage=Stage.LOAD,
                        status=StageStatus.COMPLETED,
                        detail={
                            "kind": SOURCE_RUN_KIND,
                            "plan_id": plan.plan_id,
                            "slice_id": item.slice_id,
                        },
                    )
                ],
            )
        )
    return run_ids


def _outcome(
    *,
    plan: BackfillPlan,
    item: BackfillSlice,
    cursor: BackfillCursor,
    requests: int,
    items_captured: int,
    revisions_inserted: int,
    run_id: str | None,
    dry_run: bool,
    watermarks: Mapping[str, date],
    planned: int,
    items: list[dict[str, Any]] | None = None,
    writes: int | None = None,
) -> dict[str, Any]:
    payload = {
        "plan_id": plan.plan_id,
        "slice_id": item.slice_id,
        "mindate": item.mindate.isoformat(),
        "maxdate": item.maxdate.isoformat(),
        "planned_request_count": planned,
        "requests": requests,
        "items_captured": items_captured,
        "revisions_inserted": revisions_inserted,
        "remaining": cursor.remaining,
        "slice_complete": cursor.slice_complete,
        "cursor": cursor.as_dict(),
        "run_id": run_id,
        "dry_run": dry_run,
        "writes": 0 if dry_run else (items_captured if writes is None else writes),
        "watermarks": {source_id: day.isoformat() for source_id, day in watermarks.items()},
    }
    if items is not None:
        payload["items"] = items
    return payload


def execute_pubmed_backfill(
    *,
    plan: BackfillPlan,
    slice_id: str,
    sender: EntrezSender,
    settings: PipelineSettings,
    budget: RequestBudget,
    checkpoints: RunLedger,
    today: date,
    fetched_at: str,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    environment: str,
    now: datetime | None = None,
    dry_run: bool = False,
    revisions: RevisionLedger | None = None,
    prior: tuple[tuple[str, str, str], ...] = (),
    store: Any | None = None,
    sources: Mapping[str, dict[str, Any]] | None = None,
    receipt_document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one slice, or print the plan and stop when ``dry_run`` is set.

    ``today`` is accepted so a caller can show the daily window it is protecting.
    The slice dates come from the plan, not from ``today``.
    """
    del today
    moment = now if now is not None else datetime.now(UTC)
    if in_backfill_blackout(moment):
        _refuse(_BLACKOUT)
    if _daily_running(checkpoints):
        _refuse(_DAILY_RUNNING)
    validate_backfill_approval(plan, environment)
    item = plan.find(_token(slice_id))
    watermarks = _require_watermarks(entry_dates_from_ledger(checkpoints))
    _require_window(item, watermarks)
    current = _latest_cursor(checkpoints, plan.plan_id, item.slice_id) or _blank_cursor()
    planned = planned_request_count(plan, current)
    if dry_run:
        return _outcome(
            plan=plan,
            item=item,
            cursor=current,
            requests=0,
            items_captured=0,
            revisions_inserted=0,
            run_id=None,
            dry_run=True,
            watermarks=watermarks,
            planned=planned,
        )
    loaded = _sources(sources)
    queries = _load_queries()
    policies = _load_policies(loaded, receipt_document)
    if revisions is None:
        revisions = RevisionLedger()
    for item_id, revision_id, _source_id in prior:
        revisions.keys.add((item_id, revision_id))
    session = _EntrezSession(
        sender=sender,
        settings=settings,
        budget=budget,
        clock=clock,
        sleep=sleep,
        request_cap=plan.request_limit,
        batch_size=plan.batch_size,
        max_response_bytes=plan.max_response_bytes,
        timeout_seconds=plan.timeout_seconds,
        min_interval_seconds=plan.min_interval_seconds,
    )
    found: dict[str, list[str]] = {}
    for source_id in SOURCE_ORDER:
        pmids, count = session.esearch(
            queries[source_id],
            item.mindate,
            item.maxdate,
            retmax=ESEARCH_RETMAX,
            max_ids=ESEARCH_RETMAX,
        )
        if count > len(pmids):
            _refuse(_TRUNCATED)
        found[source_id] = pmids
    ordered = _merge_pmids(found)
    processed = set(current.processed_pmids)
    pending = [pair for pair in ordered if pair[0] not in processed]
    # A completed slice is checked with the two searches only. New PMIDs stay
    # pending for the next run, so this pass never goes past two requests.
    selected = [] if current.slice_complete else _select_pending(ordered, processed, plan)
    built_records: dict[str, Any] = {}
    by_query = {pmid: matched for pmid, matched in selected}
    for batch in _chunks([pmid for pmid, _matched in selected], plan.batch_size):
        fetched = session.efetch(batch)
        note_pubmed_step("PARSE")
        for record in _parse_efetch(fetched):
            if record.pmid in by_query and record.pmid not in built_records:
                built_records[record.pmid] = record
    file_pmids, file_publishers = load_suppressions()
    attempt = current.sequence + 1
    run_id = backfill_run_id(plan.plan_id, item.slice_id, attempt)
    source_runs = _save_source_runs(checkpoints, plan=plan, item=item, attempt=attempt)
    artifact_sha = _sha(session.bodies)
    items: list[dict[str, Any]] = []
    newly_processed: list[str] = []
    for pmid, matched in selected:
        stored = built_records.get(pmid)
        if stored is None:
            continue
        owner = matched[0]
        items.append(
            _build_item(
                stored,
                matched=matched,
                sources=loaded,
                policies=policies,
                fetched_at=fetched_at,
                run_id=source_runs[owner],
                artifact_sha=artifact_sha,
                artifact_id=entrez_artifact_id(source_runs[owner]),
                suppress_pmids=file_pmids,
                suppress_publishers=file_publishers,
            )
        )
        newly_processed.append(pmid)
    looked_up = prior
    reader = getattr(store, "existing_entrez_captures", None) if store is not None else None
    if callable(reader) and items:
        looked_up = tuple(prior) + tuple(reader(tuple(item["item_id"] for item in items)))
    kept, _skipped = partition_pubmed_items(items, looked_up)
    for item_id, revision_id, _source_id in looked_up:
        revisions.keys.add((item_id, revision_id))
    inserted = revisions.apply(kept)
    _write_kept(
        kept,
        store=store,
        checkpoints=checkpoints,
        sources=loaded,
        source_runs=source_runs,
        body=b"".join(session.bodies),
        fetched_at=fetched_at,
    )
    all_processed = list(current.processed_pmids) + newly_processed
    still_pending = [pair for pair in ordered if pair[0] not in set(all_processed)]
    complete = not still_pending
    remaining = len(still_pending)
    saved = BackfillCursor(
        retstart=len(all_processed),
        last_pmid=all_processed[-1] if all_processed else None,
        slice_complete=complete,
        remaining=remaining,
        processed_pmids=tuple(all_processed),
        sequence=attempt,
    )
    note_pubmed_step("CHECKPOINT_SAVE")
    _save_cursor(checkpoints, run_id=run_id, plan=plan, item=item, cursor=saved)
    return _outcome(
        plan=plan,
        item=item,
        cursor=saved,
        requests=budget.requests,
        items_captured=len(items),
        revisions_inserted=inserted,
        run_id=run_id,
        dry_run=False,
        watermarks=watermarks,
        planned=planned_request_count(plan, current, pending=len(pending)),
        items=items,
        writes=len(kept),
    )


def _sha(bodies: list[bytes]) -> str:
    return hashlib.sha256(b"".join(bodies)).hexdigest()


def _sources(sources: Mapping[str, dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    if sources is None:
        selected = registered_entrez_sources(PROD_DAILY_SOURCE_SHA256)
        loaded = {source["source_id"]: source for source in selected}
    else:
        loaded = dict(sources)
    _require_run_sources(loaded)
    for source_id, source in loaded.items():
        if source.get("state") != "active":
            _refuse(_UNREGISTERED)
        if source_id not in SOURCE_ORDER:
            _refuse(_UNREGISTERED)
    if set(loaded) != set(SOURCE_ORDER):
        _refuse(_UNREGISTERED)
    return loaded


def _write_kept(
    kept: list[dict[str, Any]],
    *,
    store: Any | None,
    checkpoints: RunLedger,
    sources: Mapping[str, dict[str, Any]],
    source_runs: Mapping[str, str],
    body: bytes,
    fetched_at: str,
) -> None:
    if store is None or not kept:
        return
    retention = getattr(checkpoints, "feed_retention", None)
    grouped: dict[str, list[dict[str, Any]]] = {source_id: [] for source_id in SOURCE_ORDER}
    for item in kept:
        grouped.setdefault(item["source_id"], []).append(item)
    for source_id in SOURCE_ORDER:
        rows = grouped.get(source_id) or []
        write_run = source_runs.get(source_id)
        if not rows or write_run is None:
            continue
        if isinstance(retention, FeedRawRetention):
            context = prepare_entrez_source_capture(
                retention=retention,
                source=sources[source_id],
                run_id=write_run,
                body=body,
                fetched_at=fetched_at,
                capture_session=store.capture_session,
            )
            store.record_acquisition(
                source_id=source_id,
                registry_version=int(sources[source_id]["registry_version"]),
                resource_key=source_id,
                run_id=write_run,
                artifact_id=entrez_artifact_id(write_run),
                context=context,
            )
        note_pubmed_step("ITEM_WRITE")
        store.write(
            source_id=source_id,
            registry_version=int(sources[source_id]["registry_version"]),
            resource_key=source_id,
            run_id=write_run,
            items=rows,
        )


def _policies_for_store() -> dict[str, NativeMetadataPolicy]:
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
    return policies


def open_pubmed_backfill_io(
    settings: PipelineSettings,
) -> tuple[IntelligenceStore, Any, PilotBudget]:
    """Ledger and item store for one operator run. This does not claim a daily slot."""
    environment: Literal["DEV", "PROD"] = "PROD" if settings.topx_env == "prod" else "DEV"
    budget = PilotBudget(seconds=WALK_SECONDS, request_limit=MATTHEW_APPROVED_REQUEST_LIMIT)

    @contextmanager
    def factory() -> Iterator[Any]:
        note_step_deadline()
        budget.remaining()
        with connect(SnowflakeSettings()) as raw:
            try:
                yield _budget_connection(raw, budget)
            finally:
                note_step_deadline()

    policies = _policies_for_store()
    store = IntelligenceStore(
        connection_factory=factory,
        retention_allowed=lambda ref: str(ref).endswith("metadata-raw-30d-v1"),
        native_policy_lookup=lambda sid, version: policies[sid],
        settings=settings,
    )
    retention = FeedRawRetention(
        SnowflakeRawLedger(factory, environment),
        environment=environment,
        source_lookup=store.lookup_source,
        policy_lookup=lambda source: source["access_use"]["content_retention_policy_ref"],
    )
    checkpoints = IntelligenceSnowflakeCheckpoints(retention, connection_factory=factory)
    return store, checkpoints, budget


def _budget_connection(raw: Any, budget: PilotBudget) -> Any:
    return _Connection(raw, budget)


def run_operator_pubmed_backfill(
    *,
    plan_id: str,
    slice_id: str,
    settings: PipelineSettings,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Operator entry. Reads the plan, then the ledger. ``--dry-run`` makes no provider call."""
    plan = load_backfill_plan(plan_id)
    store, checkpoints, budget = open_pubmed_backfill_io(settings)
    budget.request_limit = plan.request_limit
    return execute_pubmed_backfill(
        plan=plan,
        slice_id=slice_id,
        sender=live_entrez_get,
        settings=settings,
        budget=budget,
        checkpoints=checkpoints,
        store=store,
        today=datetime.now(UTC).date(),
        fetched_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        clock=time.monotonic,
        sleep=time.sleep,
        environment=settings.topx_env,
        now=now,
        dry_run=dry_run,
    )


def public_outcome(result: Mapping[str, Any]) -> dict[str, Any]:
    """Fields safe to print. Contact settings and response bytes are not included."""
    cursor = result.get("cursor")
    safe_cursor: dict[str, Any] = {}
    if isinstance(cursor, dict):
        for key in ("retstart", "last_pmid", "slice_complete", "remaining"):
            if key in cursor:
                safe_cursor[key] = cursor[key]
    kept: dict[str, Any] = {"cursor": safe_cursor}
    for key in (
        "plan_id",
        "slice_id",
        "mindate",
        "maxdate",
        "planned_request_count",
        "requests",
        "items_captured",
        "revisions_inserted",
        "remaining",
        "slice_complete",
        "run_id",
        "dry_run",
        "writes",
        "watermarks",
    ):
        if key in result:
            kept[key] = result[key]
    return kept
