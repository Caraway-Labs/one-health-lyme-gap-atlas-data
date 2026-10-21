"""Verify the canonical V153 Actions receipt; no Snowflake session or grants."""

import json
import os
import re
import subprocess
from typing import Any

REPOSITORY = "Caraway-Labs/one-health-lyme-gap-atlas-data"
JOB = "Protected January PROD migrations only"


def require_receipt(run: dict[str, Any], jobs: dict[str, Any], log: str, sha: str) -> None:
    if (
        run.get("repository", {}).get("full_name") != REPOSITORY
        or run.get("path") != ".github/workflows/promote-prod.yml"
        or run.get("head_sha") != sha
        or run.get("head_branch") != "main"
        or run.get("event") != "workflow_dispatch"
        or run.get("run_attempt") != 1
        or run.get("conclusion") != "success"
        or not any(
            job.get("name") == JOB and job.get("conclusion") == "success"
            for job in jobs.get("jobs", [])
        )
    ):
        raise ValueError("JANUARY_BULK_REPAIR_RUN_UNVERIFIED")
    receipts = []
    for line in log.splitlines():
        if not line.startswith(JOB + "\tApply only reviewed climate migrations\t"):
            continue
        offset = line.find('{"applied":')
        if offset >= 0:
            try:
                receipts.append(json.loads(line[offset:]))
            except ValueError:
                continue
    if receipts != [{"applied": ["V153"], "excluded": ["V150"]}]:
        raise ValueError("JANUARY_BULK_REPAIR_RECEIPT_UNVERIFIED")


def main() -> None:
    run_id = os.environ.get("JANUARY_BULK_REPAIR_RUN_ID", "")
    sha = os.environ.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9]+", run_id) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise SystemExit("JANUARY_BULK_REPAIR_INPUT")

    def gh(*args: str) -> str:
        return subprocess.run(
            ["gh", *args], capture_output=True, text=True, check=True, timeout=30
        ).stdout

    root = f"repos/{REPOSITORY}/actions/runs/{run_id}"
    require_receipt(
        json.loads(gh("api", root)),
        json.loads(gh("api", root + "/jobs")),
        gh("run", "view", run_id, "--repo", REPOSITORY, "--log"),
        sha,
    )
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as output:
        output.write("JANUARY_BULK_REPAIR_VERIFIED=true\n")
    print(json.dumps({"bulk_repair_run_id": run_id, "status": "PASS", "sha": sha}))


if __name__ == "__main__":
    main()
