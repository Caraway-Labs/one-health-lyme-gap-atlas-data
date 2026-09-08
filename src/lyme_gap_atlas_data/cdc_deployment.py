"""Bounded specification changes for the approved CDC operating policy."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


def operating_policy_spec(spec: dict[str, Any], verified_digest: str) -> dict[str, Any]:
    """Preserve unrelated jobs and provider-encrypted configuration; never log it.

    The protected caller must first prove V043, publication bootstrap, notification
    delivery, and the DEV scenario suite. This function does not deploy anything.
    """
    if re.fullmatch(r"sha256:[0-9a-f]{64}", verified_digest) is None:
        raise ValueError("A verified immutable digest is required")
    if spec.get("name") != "oh-lyme-data-prod":
        raise ValueError("Unexpected production application")
    updated = deepcopy(spec)
    jobs = updated.get("jobs", [])
    candidates = [job for job in jobs if job.get("name") == "approved-source-ingestion"]
    if len(candidates) != 1:
        raise ValueError("Expected exactly one CDC schedule")
    source = candidates[0]
    if source.get("run_command") != "uv run atlas-data pipeline run-production-schedule":
        raise ValueError("Unexpected CDC schedule command")
    if source.get("image", {}).get("digest") != verified_digest:
        raise ValueError("Deploy and verify the operating-policy digest before scheduling")
    source["schedule"] = {"cron": "0 9 1 * *", "time_zone": "America/Denver"}
    source["kind"] = "SCHEDULED"
    watchdogs = [job for job in jobs if job.get("name") == "cdc-operations-watchdog"]
    if len(watchdogs) > 1:
        raise ValueError("Duplicate CDC watchdog jobs")
    if watchdogs:
        watchdog = watchdogs[0]
        if watchdog.get("run_command") != "uv run atlas-data pipeline check-cdc-overdue":
            raise ValueError("Unexpected CDC watchdog command")
    else:
        watchdog = deepcopy(source)
        watchdog["name"] = "cdc-operations-watchdog"
        watchdog["run_command"] = "uv run atlas-data pipeline check-cdc-overdue"
        # This watchdog only queries Snowflake; it must not inherit source or
        # object-storage credentials from the ingestion job's explicit env list.
        watchdog["envs"] = [
            env
            for env in watchdog.get("envs", [])
            if env["key"].startswith("SNOWFLAKE_")
            or env["key"] in {"TOPX_ENV", "ENABLE_PRODUCTION_EXECUTION"}
        ]
        jobs.append(watchdog)
    watchdog["image"] = deepcopy(source["image"])
    watchdog["kind"] = "SCHEDULED"
    watchdog["schedule"] = {"cron": "0 10 * * *", "time_zone": "America/Denver"}
    return updated
