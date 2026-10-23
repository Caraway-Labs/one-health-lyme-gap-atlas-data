"""Build one temporary PROD intelligence-daily job from the live seven-job spec."""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any

import deploy_intelligence_daily as daily

EXPECTED_JOBS = daily.BASE | {daily.NAME}
MANUAL_JOB = "intelligence-daily-manual-once"
COMMAND = daily.COMMAND


def build_operation_spec(baseline: dict[str, Any], *, preflight_only: bool) -> dict[str, Any]:
    jobs = baseline.get("jobs", [])
    if not isinstance(jobs, list) or {job.get("name") for job in jobs if isinstance(job, dict)} != EXPECTED_JOBS:
        raise PermissionError("INTELLIGENCE_DAILY_BASELINE_TOPOLOGY_REQUIRED")
    if any(job.get("kind") == "PRE_DEPLOY" for job in jobs if isinstance(job, dict)):
        raise PermissionError("INTELLIGENCE_DAILY_COMPETING_PREDEPLOY")
    template = next(job for job in jobs if job.get("name") == daily.NAME)
    digest = template.get("image", {}).get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise PermissionError("INTELLIGENCE_DAILY_IMAGE_REQUIRED")
    if template.get("run_command") != COMMAND:
        raise PermissionError("INTELLIGENCE_DAILY_COMMAND_REQUIRED")
    manual = copy.deepcopy(template)
    manual.update(
        name=MANUAL_JOB,
        kind="PRE_DEPLOY",
        run_command=COMMAND + (" --preflight-only" if preflight_only else ""),
        instance_count=1,
    )
    manual.pop("schedule", None)
    result = copy.deepcopy(baseline)
    result["jobs"] = [job for job in jobs if job.get("name") != MANUAL_JOB] + [manual]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    args.output.write_text(
        json.dumps(build_operation_spec(baseline, preflight_only=args.preflight_only)),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
