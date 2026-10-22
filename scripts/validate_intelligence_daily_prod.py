"""Two credential-free Propose calls in the existing protected PROD context."""

from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess

import deploy_intelligence_daily as daily

API = "https://api.digitalocean.com/"
OLD = "sha256:a0338b6a34a31a7015ac0df45edf186e080cce116de8ecf4f892d67cd9048457"
NEW = "sha256:3b3002e1fed2386b336fb14951e06e13a0ddecdfbde1d63945fcf0ca91149226"
PUBLIC_JOBS = {
    "catalog-discovery": ("uv run atlas-data pipeline discover", "0 8 * * 1"),
    "approved-source-ingestion": (
        "uv run atlas-data pipeline run-production-schedule",
        "0 9 1 * *",
    ),
    "cdc-operations-watchdog": ("uv run atlas-data pipeline check-cdc-overdue", "0 10 * * *"),
    **{
        f"catalog-registration-{number:02}": (
            "/app/.venv/bin/atlas-data pipeline register-latest-discovery "
            "--max-artifacts 12 --max-datasets 1500",
            f"{minute} * * * *",
        )
        for number, minute in ((1, 15), (2, 30), (3, 45))
    },
}


def image(digest):
    return {
        "registry_type": "DOCR",
        "registry": "oh-lyme-data",
        "repository": "pipeline",
        "digest": digest,
    }


def public_spec(app, digest):
    """Construct from fixed public values; never copy arbitrary configuration."""
    spec = app["spec"]
    if (
        digest != NEW
        or app.get("in_progress_deployment")
        or set(spec) != {"name", "region", "features", "ingress", "jobs"}
        or spec["name"] != "oh-lyme-data-prod"
        or spec["features"] != ["buildpack-stack=ubuntu-22"]
        or spec["ingress"] not in ({}, {"rules": []})
        or not isinstance(spec["region"], str)
        or not re.fullmatch(r"(?:nyc|ams|sfo|fra|lon|sgp|blr|tor|syd)[0-9]?", spec["region"])
        or len(spec["jobs"]) != 6
        or {j["name"] for j in spec["jobs"]} != daily.BASE
    ):
        raise PermissionError("DAILY_VALIDATION_BASELINE_DRIFT")
    jobs = []
    for job in spec["jobs"]:
        command, cron = PUBLIC_JOBS[job["name"]]
        expected = {
            "name": job["name"],
            "kind": "SCHEDULED",
            "image": image(OLD),
            "run_command": command,
            "schedule": {"cron": cron, "time_zone": "America/Denver"},
            "instance_count": 1,
            "instance_size_slug": "apps-s-1vcpu-0.5gb",
        }
        if set(job) - {"envs"} != set(expected) or any(job[k] != v for k, v in expected.items()):
            raise PermissionError("DAILY_VALIDATION_JOB_DRIFT")
        jobs.append(expected)
    return {
        "name": "oh-lyme-data-prod",
        "region": spec["region"],
        "features": ["buildpack-stack=ubuntu-22"],
        "ingress": copy.deepcopy(spec["ingress"]),
        "jobs": jobs,
    }


def proposal(base, digest):
    result = copy.deepcopy(base)
    job = copy.deepcopy(next(j for j in base["jobs"] if j["name"] == "approved-source-ingestion"))
    job.update(
        name=daily.CHECK,
        kind="PRE_DEPLOY",
        image=image(digest),
        run_command=daily.COMMAND + " --preflight-only",
    )
    job.pop("schedule")
    result["jobs"].append(job)
    return result


def run_validation(digest):
    before = daily.get(["apps", "get", daily.APP_ID])
    base = public_spec(before, digest)
    active = daily.get(["apps", "get-deployment", daily.APP_ID, before["active_deployment"]["id"]])
    if active.get("phase") != "ACTIVE" or active["spec"] != before["spec"]:
        raise PermissionError("DAILY_VALIDATION_ACTIVE_DRIFT")
    dev = daily.get(["apps", "get", "b33dbae7-e243-4e27-b3ca-1018f5897f87"])
    if (
        dev.get("in_progress_deployment")
        or not dev["spec"]["jobs"]
        or any(j.get("image", {}).get("digest") != NEW for j in dev["spec"]["jobs"])
    ):
        raise PermissionError("DAILY_VALIDATION_DEV_DIGEST_REQUIRED")
    outcomes = []
    for label, version in (("original_digest", OLD), ("verified_digest", NEW)):
        payload = proposal(base, version)
        result = subprocess.run(
            [
                "doctl",
                "--api-url",
                API,
                "apps",
                "propose",
                "--app",
                daily.APP_ID,
                "--spec",
                "-",
                "--output",
                "json",
                "--http-retry-max",
                "0",
            ],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
        )
        outcome = {"case": label, "accepted": result.returncode == 0}
        if result.returncode:
            outcome["safe_error"] = daily.validation_metadata(
                result.stderr, result.stdout, daily.diagnostic_sensitive_values({})
            )
        else:
            try:
                if len(result.stdout.encode()) > 1_048_576:
                    raise ValueError()
                normalized = json.loads(result.stdout)["spec"]["jobs"]
                outcome["normalized_image_refs_match"] = {
                    j["name"]: j.get("image") for j in normalized
                } == {j["name"]: j["image"] for j in payload["jobs"]}
            except (ValueError, KeyError, TypeError):
                outcome["normalized_image_refs_match"] = False
        outcomes.append(outcome)
    after = daily.get(["apps", "get", daily.APP_ID])
    if (
        after["spec"] != before["spec"]
        or after["active_deployment"]["id"] != before["active_deployment"]["id"]
        or after.get("in_progress_deployment")
    ):
        raise PermissionError("DAILY_VALIDATION_POSTCHECK_DRIFT")
    return {
        "mode": "validation_only",
        "proposals": outcomes,
        "provider_updates": 0,
        "credential_fields_in_payload": False,
        "app_unchanged": True,
        "update_source_resolution_not_proven": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-digest", required=True)
    result = run_validation(parser.parse_args().image_digest)
    print(json.dumps(result))
    return 0 if all(x["accepted"] for x in result["proposals"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
