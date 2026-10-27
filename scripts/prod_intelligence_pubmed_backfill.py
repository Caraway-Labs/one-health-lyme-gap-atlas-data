"""Gate and one-shot spec for one PubMed backfill slice.

The gate refuses the dispatch before any provider call. The build mode writes a
temporary PRE_DEPLOY job and leaves the scheduled daily job unchanged.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import deploy_intelligence_daily as daily
import prod_intelligence_daily_job_spec as daily_spec

JOB_NAME = "intelligence-pubmed-backfill"
COMMAND = (
    "/app/.venv/bin/atlas-data pipeline run-intelligence-pubmed-backfill"
    " --backfill-plan-id {plan_id} --slice-id {slice_id}"
)
OUTCOME_LOG_PREFIX = "ATLAS_PUBMED_BACKFILL_OUTCOME "
DENVER = ZoneInfo("America/Denver")
BLACKOUT_START_MINUTE = 17 * 60 + 45
BLACKOUT_END_MINUTE = 18 * 60 + 45
_TOKEN = re.compile(r"^[a-z0-9][a-z0-9-]{0,48}$")
_PLAN_INVALID = "INTELLIGENCE_PUBMED_BACKFILL_PLAN_INVALID"
_DAILY_RUNNING = "INTELLIGENCE_PUBMED_BACKFILL_DAILY_RUNNING"
_DAILY_UNKNOWN = "INTELLIGENCE_PUBMED_BACKFILL_DAILY_STATUS_UNKNOWN"
_BLACKOUT = "INTELLIGENCE_PUBMED_BACKFILL_BLACKOUT"
_OUTCOME_KEYS = (
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
    "cursor",
)
_CURSOR_KEYS = ("retstart", "last_pmid", "slice_complete", "remaining")


def in_backfill_blackout(moment: datetime) -> bool:
    """True from 5:45 PM through 6:45 PM America/Denver, inclusive of those minutes."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise PermissionError(_PLAN_INVALID)
    local = moment.astimezone(DENVER)
    minute = local.hour * 60 + local.minute
    return BLACKOUT_START_MINUTE <= minute <= BLACKOUT_END_MINUTE


def _token(value: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise PermissionError(_PLAN_INVALID)
    return value


def backfill_command(plan_id: str, slice_id: str) -> str:
    return COMMAND.format(plan_id=_token(plan_id), slice_id=_token(slice_id))


def evaluate_gate(
    *,
    now: datetime,
    plan_id: str,
    slice_id: str,
    reason: str,
    daily_running_count: int,
    daily_status_known: bool,
) -> str | None:
    """Return an allowlisted refusal, or None when the workflow may continue."""
    _token(plan_id)
    _token(slice_id)
    daily_spec.normalize_reason(reason)
    if not daily_status_known:
        return _DAILY_UNKNOWN
    if daily_running_count > 0:
        return _DAILY_RUNNING
    if in_backfill_blackout(now):
        return _BLACKOUT
    return None


def build_backfill_spec(baseline: dict[str, Any], *, plan_id: str, slice_id: str) -> dict[str, Any]:
    """Copy the daily image into one PRE_DEPLOY job. The scheduled job stays as it was."""
    jobs = baseline.get("jobs", [])
    job_names = {job.get("name") for job in jobs if isinstance(job, dict)}
    if not isinstance(jobs, list) or job_names != daily_spec.EXPECTED_JOBS:
        raise PermissionError("INTELLIGENCE_DAILY_BASELINE_TOPOLOGY_REQUIRED")
    if any(job.get("kind") == "PRE_DEPLOY" for job in jobs if isinstance(job, dict)):
        raise PermissionError("INTELLIGENCE_DAILY_COMPETING_PREDEPLOY")
    template = next(job for job in jobs if isinstance(job, dict) and job.get("name") == daily.NAME)
    digest = template.get("image", {}).get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(digest)):
        raise PermissionError("INTELLIGENCE_DAILY_IMAGE_REQUIRED")
    if template.get("run_command") not in daily_spec.ACCEPTED_SCHEDULED_COMMANDS:
        raise PermissionError("INTELLIGENCE_DAILY_COMMAND_REQUIRED")
    manual = copy.deepcopy(template)
    manual.update(
        name=JOB_NAME,
        kind="PRE_DEPLOY",
        run_command=backfill_command(plan_id, slice_id),
        instance_count=1,
        timeout="20m",
    )
    manual.pop("schedule", None)
    result = copy.deepcopy(baseline)
    result["jobs"] = [job for job in result["jobs"] if job.get("name") != JOB_NAME] + [manual]
    for job in result["jobs"]:
        if isinstance(job, dict) and job.get("name") == JOB_NAME:
            daily.place_daily_otel(job, result)
    original = next(job for job in baseline["jobs"] if job.get("name") == daily.NAME)
    scheduled = next(job for job in result["jobs"] if job.get("name") == daily.NAME)
    if scheduled != original:
        raise PermissionError(_PLAN_INVALID)
    return result


def redact_outcome(text: str) -> dict[str, Any] | None:
    """Keep one outcome line. Drop every other field, including contact settings."""
    found: dict[str, Any] | None = None
    for line in text.splitlines():
        if OUTCOME_LOG_PREFIX not in line:
            continue
        payload = line.split(OUTCOME_LOG_PREFIX, 1)[1].strip()
        try:
            document = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(document, dict):
            continue
        kept = {key: document[key] for key in _OUTCOME_KEYS if key in document}
        cursor = kept.get("cursor")
        if isinstance(cursor, dict):
            kept["cursor"] = {key: cursor[key] for key in _CURSOR_KEYS if key in cursor}
        found = kept
    return found


def _parse_now(value: str) -> datetime:
    if not value:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _gate(args: argparse.Namespace) -> int:
    try:
        code = evaluate_gate(
            now=_parse_now(args.now),
            plan_id=args.backfill_plan_id,
            slice_id=args.slice_id,
            reason=args.reason,
            daily_running_count=args.daily_running_count,
            daily_status_known=not args.daily_status_unknown,
        )
    except (PermissionError, ValueError) as error:
        print(str(error) or _PLAN_INVALID)
        return 2
    if code is not None:
        print(code)
        return 2
    print("ready")
    return 0


def _build(args: argparse.Namespace) -> int:
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    spec = build_backfill_spec(baseline, plan_id=args.backfill_plan_id, slice_id=args.slice_id)
    args.output.write_text(json.dumps(spec), encoding="utf-8")
    return 0


def _render(args: argparse.Namespace) -> int:
    text = args.logs.read_text(encoding="utf-8") if args.logs is not None else ""
    outcome = redact_outcome(text)
    if outcome is None:
        print("OUTCOME_LOG_UNAVAILABLE")
        return 1
    print(json.dumps(outcome, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("gate", "build", "render-outcome"), required=True)
    parser.add_argument("--backfill-plan-id", default="")
    parser.add_argument("--slice-id", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--now", default="")
    parser.add_argument("--daily-running-count", type=int, default=0)
    parser.add_argument("--daily-status-unknown", action="store_true")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--logs", type=Path)
    args = parser.parse_args(argv)
    if args.mode == "gate":
        return _gate(args)
    if args.mode == "build":
        if args.baseline is None or args.output is None:
            print(_PLAN_INVALID)
            return 2
        return _build(args)
    return _render(args)


if __name__ == "__main__":
    sys.exit(main())
