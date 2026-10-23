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
RECOVER_PREFIX = "/app/.venv/bin/atlas-data pipeline recover-intelligence-daily-stuck-run --ingestion-run-id "


def build_operation_spec(
    baseline: dict[str, Any],
    *,
    preflight_only: bool,
    recover_ingestion_run_id: str = "",
) -> dict[str, Any]:
    jobs = baseline.get("jobs", [])
    job_names = {job.get("name") for job in jobs if isinstance(job, dict)}
    if not isinstance(jobs, list) or job_names != EXPECTED_JOBS:
        raise PermissionError("INTELLIGENCE_DAILY_BASELINE_TOPOLOGY_REQUIRED")
    if any(job.get("kind") == "PRE_DEPLOY" for job in jobs if isinstance(job, dict)):
        raise PermissionError("INTELLIGENCE_DAILY_COMPETING_PREDEPLOY")
    template = next(job for job in jobs if job.get("name") == daily.NAME)
    digest = template.get("image", {}).get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise PermissionError("INTELLIGENCE_DAILY_IMAGE_REQUIRED")
    if template.get("run_command") != COMMAND:
        raise PermissionError("INTELLIGENCE_DAILY_COMMAND_REQUIRED")
    if recover_ingestion_run_id and preflight_only:
        raise PermissionError("INTELLIGENCE_DAILY_RECOVERY_MODE_EXCLUSIVE")
    if recover_ingestion_run_id:
        if not re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            recover_ingestion_run_id,
        ):
            raise PermissionError("INTELLIGENCE_DAILY_RECOVERY_RUN_ID_REQUIRED")
        run_command = RECOVER_PREFIX + recover_ingestion_run_id
    else:
        run_command = COMMAND + (" --preflight-only" if preflight_only else "")
    manual = copy.deepcopy(template)
    manual.update(
        name=MANUAL_JOB,
        kind="PRE_DEPLOY",
        run_command=run_command,
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
    parser.add_argument("--recover-ingestion-run-id", default="")
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    args.output.write_text(
        json.dumps(
            build_operation_spec(
                baseline,
                preflight_only=args.preflight_only,
                recover_ingestion_run_id=args.recover_ingestion_run_id,
            )
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
