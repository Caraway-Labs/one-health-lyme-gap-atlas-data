"""Read-only provider monitoring with deduplicated repository issue receipts."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from typing import Any

from .cdc_policy import overdue_metadata_period

REPOSITORY = "Caraway-Labs/one-health-lyme-gap-atlas-data"
PROD_APP = "5d8966ed-d152-4a78-bdd6-14553dbc1483"


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Monitoring requires timezone-aware timestamps")
    return parsed


def incident_candidates(
    invocations: list[dict[str, Any]], *, now: datetime, enabled_at: datetime
) -> dict[str, str]:
    """The activation receipt certifies the initial successful metadata baseline."""
    incidents: dict[str, str] = {}
    latest_metadata_success = enabled_at
    for invocation in invocations:
        started = timestamp(str(invocation.get("created_at")))
        if started < enabled_at:
            continue
        job = invocation["job_name"]
        if job not in {"approved-source-ingestion", "cdc-operations-watchdog"}:
            continue
        phase = invocation["phase"]
        if phase == "SUCCEEDED" and job == "approved-source-ingestion":
            latest_metadata_success = max(latest_metadata_success, started)
        elif phase in {"FAILED", "CANCELED", "ERROR"}:
            incidents[f"job:{invocation['id']}"] = f"CDC {job} ended with {phase}"
        elif phase not in {"SUCCEEDED", "RUNNING", "PENDING", "QUEUED"}:
            incidents[f"unknown-state:{invocation['id']}"] = "CDC job reported an unknown state"
    period = overdue_metadata_period(now, latest_metadata_success)
    if period:
        incidents[f"overdue:{period}"] = f"CDC metadata check overdue for {period}"
    return incidents


def run_json(arguments: list[str], *, body: dict[str, Any] | None = None) -> Any:
    result = subprocess.run(
        arguments,
        input=json.dumps(body) if body is not None else None,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if result.returncode:
        # Provider responses and CLI configuration may contain sensitive data.
        raise RuntimeError(f"Monitoring request failed: {arguments[0]}")
    return json.loads(result.stdout)


def deliver_incidents(incidents: dict[str, str]) -> int:
    pages = run_json(
        [
            "gh",
            "api",
            f"repos/{REPOSITORY}/issues?state=all&per_page=100",
            "--paginate",
            "--slurp",
        ]
    )
    bodies = [issue.get("body") or "" for page in pages for issue in page]
    delivered = 0
    for key, title in incidents.items():
        marker = f"<!-- atlas-cdc-incident:{key} -->"
        if any(marker in body for body in bodies):
            continue
        body = (
            f"{marker}\n\n{title}.\n\n"
            "Review the governed run history and post-ingestion validation page. "
            "Do not retry a full refresh or change the published snapshot automatically. "
            "This issue is the durable notification receipt for this incident."
        )
        run_json(
            ["gh", "api", f"repos/{REPOSITORY}/issues", "--method", "POST", "--input", "-"],
            body={"title": title, "body": body},
        )
        bodies.append(body)
        delivered += 1
    return delivered


def main() -> None:
    enabled_at = timestamp(os.environ["CDC_MONITOR_ENABLED_AT"])
    now = datetime.now(UTC)
    if enabled_at > now:
        raise ValueError("Monitoring activation cannot be in the future")
    invocations: list[dict[str, Any]] = []
    for job in ("approved-source-ingestion", "cdc-operations-watchdog"):
        invocations.extend(
            run_json(
                [
                    "doctl",
                    "apps",
                    "list-job-invocations",
                    PROD_APP,
                    "--job-name",
                    job,
                    "--output",
                    "json",
                ]
            )
            or []
        )
    incidents = incident_candidates(invocations, now=now, enabled_at=enabled_at)
    # Full refreshes are protected manual workflows, not scheduled invocations.
    pages = run_json(
        [
            "gh",
            "api",
            f"repos/{REPOSITORY}/actions/workflows/run-prod-approved-ingestion.yml/runs?per_page=100",
            "--paginate",
            "--slurp",
        ]
    )
    for page in pages:
        for run in page["workflow_runs"]:
            if timestamp(run["created_at"]) >= enabled_at and run["conclusion"] in {
                "failure",
                "timed_out",
                "action_required",
            }:
                incidents[f"refresh:{run['id']}"] = f"CDC protected refresh failed: run {run['id']}"
    print(
        json.dumps(
            {"status": "COMPLETED", "new_incident_notifications": deliver_incidents(incidents)}
        )
    )


if __name__ == "__main__":
    main()
