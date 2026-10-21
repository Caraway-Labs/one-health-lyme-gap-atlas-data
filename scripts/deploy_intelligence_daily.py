"""Add only the approved daily RSS job to the existing app; no secret output."""

from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
from typing import Any

APP_ID = "5d8966ed-d152-4a78-bdd6-14553dbc1483"
NAME = "intelligence-feed-daily"
CHECK = NAME + "-preflight"
COMMAND = "/app/.venv/bin/atlas-data pipeline run-intelligence-daily"
BASE = {
    "catalog-discovery",
    "approved-source-ingestion",
    "cdc-operations-watchdog",
    "catalog-registration-01",
    "catalog-registration-02",
    "catalog-registration-03",
}
KEYS = {
    "TOPX_ENV",
    "ENABLE_PRODUCTION_EXECUTION",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_ROLE",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_AUTH_METHOD",
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PRIVATE_KEY_B64",
    "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE",
    "SPACES_REGION",
    "SPACES_ENDPOINT",
    "SPACES_BUCKET",
    "SPACES_PREFIX",
    "SPACES_ACCESS_KEY_ID",
    "SPACES_SECRET_ACCESS_KEY",
}


def render(spec: dict[str, Any], digest: str, phase: str) -> dict[str, Any]:
    if spec.get("name") != "oh-lyme-data-prod" or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise PermissionError("INTELLIGENCE_DAILY_DEPLOY_TARGET_REQUIRED")
    jobs = spec.get("jobs", [])
    if (
        len({j["name"] for j in jobs}) != len(jobs)
        or {j["name"] for j in jobs} - {NAME, CHECK} != BASE
    ):
        raise PermissionError("INTELLIGENCE_DAILY_BASELINE_REQUIRED")
    template = next(j for j in jobs if j["name"] == "approved-source-ingestion")
    env = {e["key"]: e for e in template.get("envs", [])}
    if not env.keys() >= KEYS:
        raise PermissionError("INTELLIGENCE_DAILY_EXISTING_CREDENTIALS_REQUIRED")
    expected = {
        "TOPX_ENV": "prod",
        "ENABLE_PRODUCTION_EXECUTION": "true",
        "SNOWFLAKE_ROLE": "OH_LYME_PROD_RUNTIME",
        "SNOWFLAKE_DATABASE": "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        "SNOWFLAKE_WAREHOUSE": "OH_LYME_PROD_INGEST_XS_WH",
        "SNOWFLAKE_AUTH_METHOD": "key_pair",
    }
    if any(env[k].get("value") != v for k, v in expected.items()):
        raise PermissionError("INTELLIGENCE_DAILY_RUNTIME_SCOPE_REQUIRED")
    if phase not in {"preflight", "activate"}:
        raise ValueError("INTELLIGENCE_DAILY_DEPLOY_PHASE_REQUIRED")
    result = copy.deepcopy(spec)
    new = copy.deepcopy(template)
    new.update(
        name=CHECK if phase == "preflight" else NAME,
        kind="PRE_DEPLOY" if phase == "preflight" else "SCHEDULED",
        run_command=COMMAND + (" --preflight-only" if phase == "preflight" else ""),
        instance_count=1,
    )
    new["envs"] = [dict(copy.deepcopy(env[k]), scope="RUN_TIME") for k in sorted(KEYS)] + [
        {"key": "INTELLIGENCE_DAILY_ENABLED", "scope": "RUN_TIME", "value": "true"}
    ]
    new["image"] = {
        "registry_type": "DOCR",
        "registry": "oh-lyme-data",
        "repository": "pipeline",
        "digest": digest,
    }
    if phase == "preflight":
        new.pop("schedule", None)
    else:
        new["schedule"] = {"cron": "0 7 * * *", "time_zone": "America/Denver"}
    removed = {CHECK} if phase == "preflight" else {CHECK, NAME}
    result["jobs"] = [j for j in result["jobs"] if j["name"] not in removed] + [new]
    assert [j for j in result["jobs"] if j["name"] in BASE] == [
        j for j in jobs if j["name"] in BASE
    ]
    return result


def get(args: list[str]) -> dict[str, Any]:
    r = subprocess.run(
        ["doctl", *args, "--output", "json"], capture_output=True, text=True, timeout=90
    )
    if r.returncode:
        raise RuntimeError("INTELLIGENCE_DAILY_PLATFORM_READ_FAILED")
    data = json.loads(r.stdout)
    return data[0] if isinstance(data, list) else data


def verify_preflight(deployment: dict[str, Any], digest: str) -> None:
    if deployment.get("phase") != "ACTIVE":
        raise PermissionError("INTELLIGENCE_DAILY_PREFLIGHT_NOT_ACTIVE")
    job = next((j for j in deployment["spec"]["jobs"] if j["name"] == CHECK), None)
    if (
        not job
        or job["image"]["digest"] != digest
        or job["run_command"] != COMMAND + " --preflight-only"
    ):
        raise PermissionError("INTELLIGENCE_DAILY_PREFLIGHT_IMAGE_REQUIRED")
    components = [
        c
        for stage in deployment["progress"]["steps"]
        if stage["name"] == "deploy"
        for block in stage.get("steps", [])
        if block["name"] == "components"
        for c in block.get("steps", [])
        if c.get("component_name") == CHECK
    ]
    if (
        len(components) != 1
        or components[0]["status"] != "SUCCESS"
        or any(s["status"] != "SUCCESS" for s in components[0]["steps"])
    ):
        raise PermissionError("INTELLIGENCE_DAILY_SERVICE_PREFLIGHT_REQUIRED")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--image-digest", required=True)
    p.add_argument("--credential-placement-approved", action="store_true")
    p.add_argument("--phase", choices=["preflight", "activate"], required=True)
    args = p.parse_args()
    if not args.credential_placement_approved:
        raise PermissionError("INTELLIGENCE_DAILY_NEW_COMPONENT_CREDENTIAL_APPROVAL_REQUIRED")
    app = get(["apps", "get", APP_ID])
    if app.get("in_progress_deployment"):
        raise PermissionError("INTELLIGENCE_DAILY_COMPETING_DEPLOYMENT")
    if args.phase == "activate":
        verify_preflight(
            get(["apps", "get-deployment", APP_ID, app["active_deployment"]["id"]]),
            args.image_digest,
        )
    spec = render(app["spec"], args.image_digest, args.phase)
    r = subprocess.run(
        ["doctl", "apps", "update", APP_ID, "--spec", "-", "--wait", "--output", "json"],
        input=json.dumps(spec),
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if r.returncode:
        raise RuntimeError("INTELLIGENCE_DAILY_PLATFORM_UPDATE_FAILED_INSPECT_OUTCOME")
    current = get(["apps", "get", APP_ID])
    before = {j["name"]: j for j in app["spec"]["jobs"] if j["name"] in BASE}
    after = {j["name"]: j for j in current["spec"]["jobs"] if j["name"] in BASE}
    if before != after or current.get("in_progress_deployment"):
        raise PermissionError("INTELLIGENCE_DAILY_POST_DEPLOY_BASELINE_CHANGED")
    installed = next(
        (j for j in current["spec"]["jobs"] if j["name"] == spec["jobs"][-1]["name"]), None
    )
    if installed != spec["jobs"][-1]:
        raise PermissionError("INTELLIGENCE_DAILY_POST_DEPLOY_COMPONENT_MISMATCH")
    print(
        json.dumps(
            {
                "phase": args.phase,
                "app_id": APP_ID,
                "deployment_id": current["active_deployment"]["id"],
                "original_six_jobs_preserved": True,
                "credential_provisioning": False,
            }
        )
    )


if __name__ == "__main__":
    main()
