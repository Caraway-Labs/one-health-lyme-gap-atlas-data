"""Add only the approved daily RSS job to the existing app; no secret output."""

from __future__ import annotations

import argparse
import base64
import copy
import json
import os
import re
import subprocess
from typing import Any
from urllib.parse import quote, quote_plus

APP_ID = "5d8966ed-d152-4a78-bdd6-14553dbc1483"
NAME = "intelligence-feed-daily"
CHECK = "intelligence-feed-preflight"
COMMAND = "/app/.venv/bin/atlas-data pipeline run-intelligence-daily"
# Only the standing scheduled job retries a failed source. The manual job
# rebuilds its command from COMMAND and never copies this flag.
SCHEDULED_RETRY_FLAG = "--scheduled-same-day-retry"
SCHEDULED_RUN_COMMAND = f"{COMMAND} {SCHEDULED_RETRY_FLAG}"
DAILY_SCHEDULE = {"cron": "15 18 * * *", "time_zone": "America/Denver"}
# Only the standing daily job runs on 1 GB (approved 2026-10-26, #862).
# Every other job keeps the size it already has in the platform spec.
DAILY_JOB_INSTANCE_SIZE_SLUG = "apps-s-1vcpu-1gb"
BASE = {
    "catalog-discovery",
    "approved-source-ingestion",
    "cdc-operations-watchdog",
    "catalog-registration-01",
    "catalog-registration-02",
    "catalog-registration-03",
}
# Existing pipeline images that must share one digest before DO accepts a spec update.
OPERATIONAL_IMAGE_JOBS = BASE | {NAME, CHECK}
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
# Contact settings for the daily component. NCBI_EMAIL is required.
# NCBI_API_KEY is optional: a missing or empty process value is skipped
# and is never written onto the job. Values come from the process
# environment only, never from argv.
NCBI_PLACEMENT_ALLOWLIST = ("NCBI_EMAIL", "NCBI_API_KEY")
NCBI_EMAIL_REQUIRED = "INTELLIGENCE_DAILY_NCBI_EMAIL_REQUIRED"
# Copied from a sibling job that already exports traces. Values stay in the
# platform spec; this module never prints them.
OTEL_ENV_KEYS = ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS")
OTEL_SOURCE_JOBS = (
    "catalog-registration-01",
    "catalog-registration-02",
    "catalog-registration-03",
    "approved-source-ingestion",
    "catalog-discovery",
)


def render(spec: dict[str, Any], digest: str, phase: str) -> dict[str, Any]:
    if spec.get("name") != "oh-lyme-data-prod" or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise PermissionError("INTELLIGENCE_DAILY_DEPLOY_TARGET_REQUIRED")
    jobs = spec.get("jobs", [])
    if (
        len({j["name"] for j in jobs}) != len(jobs)
        or {j["name"] for j in jobs} - {NAME, CHECK} != BASE
    ):
        raise PermissionError("INTELLIGENCE_DAILY_BASELINE_REQUIRED")
    # --update-sources refreshes all component sources. It is safe here only
    # when every existing source is an immutable image, with no mutable aliases
    # or Git-backed components that could advance unrelated application code.
    if any(spec.get(kind) for kind in ("services", "workers", "static_sites", "functions")):
        raise PermissionError("INTELLIGENCE_DAILY_IMMUTABLE_SOURCES_REQUIRED")
    for job in jobs:
        image = job.get("image", {})
        if (
            any(job.get(kind) for kind in ("git", "github", "gitlab", "bitbucket"))
            or set(image) != {"registry_type", "registry", "repository", "digest"}
            or image.get("registry_type") != "DOCR"
            or image.get("registry") != "oh-lyme-data"
            or image.get("repository") != "pipeline"
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", image.get("digest", ""))
        ):
            raise PermissionError("INTELLIGENCE_DAILY_IMMUTABLE_SOURCES_REQUIRED")
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
        run_command=(
            COMMAND + " --preflight-only" if phase == "preflight" else SCHEDULED_RUN_COMMAND
        ),
        instance_count=1,
    )
    new["envs"] = [dict(copy.deepcopy(env[k]), scope="RUN_TIME") for k in sorted(KEYS)] + [
        {"key": "INTELLIGENCE_DAILY_ENABLED", "scope": "RUN_TIME", "value": "true"}
    ]
    # The preflight component is replaced by the standing job on activate.
    # Both phases place contact settings on the component this phase writes.
    _apply_ncbi_placement(new, keep_existing_email=False)
    place_daily_otel(new, result)
    new["image"] = {
        "registry_type": "DOCR",
        "registry": "oh-lyme-data",
        "repository": "pipeline",
        "digest": digest,
    }
    if phase == "preflight":
        new.pop("schedule", None)
    else:
        new["schedule"] = dict(DAILY_SCHEDULE)
        new["instance_size_slug"] = DAILY_JOB_INSTANCE_SIZE_SLUG
    removed = {CHECK} if phase == "preflight" else {CHECK, NAME}
    result["jobs"] = [j for j in result["jobs"] if j["name"] not in removed] + [new]
    assert [j for j in result["jobs"] if j["name"] in BASE] == [
        j for j in jobs if j["name"] in BASE
    ]
    return result


def with_baseline_digests(spec: dict[str, Any], digest: str) -> dict[str, Any]:
    """Pin every operational pipeline job image to digest without adding components."""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise PermissionError("INTELLIGENCE_DAILY_DEPLOY_TARGET_REQUIRED")
    result = copy.deepcopy(spec)
    for job in result.get("jobs", []):
        if job["name"] not in OPERATIONAL_IMAGE_JOBS:
            continue
        image = job.get("image", {})
        if (
            set(image) != {"registry_type", "registry", "repository", "digest"}
            or image.get("registry_type") != "DOCR"
            or image.get("registry") != "oh-lyme-data"
            or image.get("repository") != "pipeline"
        ):
            raise PermissionError("INTELLIGENCE_DAILY_IMMUTABLE_SOURCES_REQUIRED")
        job["image"] = {
            "registry_type": "DOCR",
            "registry": "oh-lyme-data",
            "repository": "pipeline",
            "digest": digest,
        }
    return result


def baseline_needs_digest_alignment(spec: dict[str, Any], digest: str) -> bool:
    return any(
        job.get("name") in OPERATIONAL_IMAGE_JOBS and job.get("image", {}).get("digest") != digest
        for job in spec.get("jobs", [])
    )


def daily_job_active(spec: dict[str, Any]) -> bool:
    return any(job.get("name") == NAME for job in spec.get("jobs", []))


def sync_daily_job_command(spec: dict[str, Any]) -> dict[str, Any]:
    """Put the scheduled-retry flag on the standing job. Leave every other command."""
    result = copy.deepcopy(spec)
    for job in result.get("jobs", []):
        if job.get("name") == NAME and job.get("run_command") == COMMAND:
            job["run_command"] = SCHEDULED_RUN_COMMAND
    return result


def sync_daily_job_schedule(spec: dict[str, Any]) -> dict[str, Any]:
    """Align the active scheduled job cron with the reviewed deploy helper constant."""
    if not daily_job_active(spec):
        return copy.deepcopy(spec)
    result = copy.deepcopy(spec)
    for job in result.get("jobs", []):
        if job.get("name") == NAME and job.get("schedule") != DAILY_SCHEDULE:
            job["schedule"] = dict(DAILY_SCHEDULE)
    return result


def sync_daily_job_size(spec: dict[str, Any]) -> dict[str, Any]:
    """Set the reviewed size on the active daily job only. Other jobs are untouched."""
    result = copy.deepcopy(spec)
    for job in result.get("jobs", []):
        if job.get("name") == NAME:
            job["instance_size_slug"] = DAILY_JOB_INSTANCE_SIZE_SLUG
    return result


def other_job_sizes(spec: dict[str, Any]) -> dict[str, Any]:
    """Map every job except the daily job to its size, to prove they never change."""
    return {
        job.get("name"): job.get("instance_size_slug")
        for job in spec.get("jobs", [])
        if isinstance(job, dict) and job.get("name") != NAME
    }


def daily_job_size(spec: dict[str, Any]) -> Any:
    job = next((j for j in spec.get("jobs", []) if j.get("name") == NAME), None)
    return (job or {}).get("instance_size_slug")


def otel_entries(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Copy the sibling OTLP endpoint and headers. Missing keys leave the job unchanged."""
    jobs = spec.get("jobs", [])
    if not isinstance(jobs, list):
        return []
    for name in OTEL_SOURCE_JOBS:
        job = next(
            (item for item in jobs if isinstance(item, dict) and item.get("name") == name),
            None,
        )
        if job is None:
            continue
        found: dict[str, dict[str, Any]] = {}
        for entry in job.get("envs", []):
            if isinstance(entry, dict) and entry.get("key") in OTEL_ENV_KEYS:
                value = entry.get("value")
                if isinstance(value, str) and value.strip():
                    found[str(entry["key"])] = entry
        if set(OTEL_ENV_KEYS) <= set(found):
            copied: list[dict[str, Any]] = []
            for key in OTEL_ENV_KEYS:
                item = copy.deepcopy(found[key])
                item["scope"] = "RUN_TIME"
                copied.append(item)
            return copied
    return []


def place_daily_otel(job: dict[str, Any], spec: dict[str, Any]) -> None:
    """Add OTEL settings the sibling jobs already carry. Do not replace existing values."""
    wanted = otel_entries(spec)
    if not wanted:
        return
    envs = [entry for entry in job.get("envs", []) if isinstance(entry, dict)]
    present = {entry.get("key") for entry in envs}
    for entry in wanted:
        if entry.get("key") not in present:
            envs.append(entry)
    job["envs"] = envs


def _nonempty_process_env(name: str) -> str | None:
    """Return one process-environment value, or None when it is missing or blank."""
    value = os.environ.get(name)
    if not isinstance(value, str) or value.strip() == "":
        return None
    return value


def _apply_ncbi_placement(job: dict[str, Any], *, keep_existing_email: bool) -> None:
    """Set NCBI contact settings on one job, then refuse a missing email.

    This runs on the in-memory spec before any platform update, so a missing
    email never starts a job that could call PubMed. Secret values are not
    included in the raised error.
    """
    envs = [entry for entry in job.get("envs", []) if isinstance(entry, dict)]
    supplied: dict[str, str] = {}
    for key in NCBI_PLACEMENT_ALLOWLIST:
        value = _nonempty_process_env(key)
        if value is not None:
            supplied[key] = value
    email = supplied.get("NCBI_EMAIL")
    if email is not None:
        envs = _upsert_secret(envs, "NCBI_EMAIL", email)
    else:
        envs = _retain_nonblank(envs, "NCBI_EMAIL", drop_all=not keep_existing_email)
    api_key = supplied.get("NCBI_API_KEY")
    if api_key is not None:
        envs = _upsert_secret(envs, "NCBI_API_KEY", api_key)
    else:
        envs = _retain_nonblank(envs, "NCBI_API_KEY", drop_all=False)
    job["envs"] = envs
    if not _ncbi_email_ready(job):
        raise PermissionError(NCBI_EMAIL_REQUIRED)


def _upsert_secret(envs: list[dict[str, Any]], key: str, value: str) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    replaced = False
    for entry in envs:
        if entry.get("key") == key:
            updated.append({"key": key, "scope": "RUN_TIME", "type": "SECRET", "value": value})
            replaced = True
        else:
            updated.append(entry)
    if not replaced:
        updated.append({"key": key, "scope": "RUN_TIME", "type": "SECRET", "value": value})
    return updated


def _retain_nonblank(
    envs: list[dict[str, Any]], key: str, *, drop_all: bool
) -> list[dict[str, Any]]:
    retained: list[dict[str, Any]] = []
    for entry in envs:
        if entry.get("key") != key:
            retained.append(entry)
            continue
        if drop_all:
            continue
        value = entry.get("value")
        if isinstance(value, str) and value.strip() != "":
            retained.append(entry)
    return retained


def _ncbi_email_ready(job: dict[str, Any]) -> bool:
    for entry in job.get("envs", []):
        if not isinstance(entry, dict) or entry.get("key") != "NCBI_EMAIL":
            continue
        value = entry.get("value")
        if (
            entry.get("scope") == "RUN_TIME"
            and entry.get("type") == "SECRET"
            and isinstance(value, str)
            and value.strip() != ""
        ):
            return True
    return False


def ncbi_presence(spec: dict[str, Any]) -> dict[str, bool]:
    """Report whether the daily component has each contact setting. No values."""
    job = next((item for item in spec.get("jobs", []) if item.get("name") == NAME), None)
    if job is None:
        job = next((item for item in spec.get("jobs", []) if item.get("name") == CHECK), None)
    present: set[str] = set()
    for entry in (job or {}).get("envs", []):
        if not isinstance(entry, dict) or entry.get("type") != "SECRET":
            continue
        value = entry.get("value")
        if isinstance(value, str) and value.strip() != "":
            present.add(str(entry.get("key")))
    return {
        "ncbi_email_present": "NCBI_EMAIL" in present,
        "ncbi_api_key_present": "NCBI_API_KEY" in present,
    }


def _deployed_component_matches(installed: dict[str, Any], expected: dict[str, Any]) -> bool:
    """Match a readback component. Provider encryption may replace NCBI values."""
    left = copy.deepcopy(installed)
    right = copy.deepcopy(expected)
    if _ncbi_projection(left.get("envs", [])) != _ncbi_projection(right.get("envs", [])):
        return False
    left["envs"] = _without_ncbi(left.get("envs", []))
    right["envs"] = _without_ncbi(right.get("envs", []))
    return left == right


def _ncbi_projection(envs: list[Any]) -> list[dict[str, Any]]:
    projected = []
    for entry in envs:
        if not isinstance(entry, dict) or entry.get("key") not in NCBI_PLACEMENT_ALLOWLIST:
            continue
        item = dict(entry)
        value = item.get("value")
        if (isinstance(value, str) and value.strip() != "") or (
            value is None and item.get("type") == "SECRET"
        ):
            item["value"] = "PRESENT"
        else:
            item["value"] = "MISSING"
        projected.append(item)
    return projected


def _without_ncbi(envs: list[Any]) -> list[Any]:
    return [
        entry
        for entry in envs
        if not (isinstance(entry, dict) and entry.get("key") in NCBI_PLACEMENT_ALLOWLIST)
    ]


def _provider_encrypted(value: object) -> bool:
    return isinstance(value, str) and value.startswith("EV[") and value.endswith("]")


def _ncbi_entries_equivalent(before: list[Any], after: list[Any]) -> bool:
    """Treat a provider ciphertext and its plaintext replacement as the same setting."""

    def indexed(envs: list[Any]) -> dict[str, dict[str, Any]]:
        return {
            str(entry.get("key")): entry
            for entry in envs
            if isinstance(entry, dict) and entry.get("key") in NCBI_PLACEMENT_ALLOWLIST
        }

    left = indexed(before)
    right = indexed(after)
    if set(left) != set(right):
        return False
    for key, old in left.items():
        new = right[key]
        if old == new or _encrypted_plaintext_pair(old, new):
            continue
        return False
    return True


def _encrypted_plaintext_pair(old: dict[str, Any], new: dict[str, Any]) -> bool:
    if old.get("scope") != "RUN_TIME" or new.get("scope") != "RUN_TIME":
        return False
    if old.get("type") != "SECRET" or new.get("type") != "SECRET":
        return False
    new_value = new.get("value")
    return (
        _provider_encrypted(old.get("value"))
        and isinstance(new_value, str)
        and new_value.strip() != ""
    )


def _same_except_encrypted_ncbi(before: dict[str, Any], after: dict[str, Any]) -> bool:
    left = copy.deepcopy(before)
    right = copy.deepcopy(after)
    left_jobs = left.get("jobs", [])
    right_jobs = right.get("jobs", [])
    if len(left_jobs) != len(right_jobs):
        return False
    for left_job, right_job in zip(left_jobs, right_jobs, strict=True):
        if not isinstance(left_job, dict) or not isinstance(right_job, dict):
            return False
        if not _ncbi_entries_equivalent(left_job.get("envs", []), right_job.get("envs", [])):
            return False
        left_job["envs"] = _without_ncbi(left_job.get("envs", []))
        right_job["envs"] = _without_ncbi(right_job.get("envs", []))
    return left == right


def refresh_operational_digests(spec: dict[str, Any], digest: str) -> dict[str, Any]:
    if not daily_job_active(spec):
        raise PermissionError("INTELLIGENCE_DAILY_REFRESH_REQUIRES_ACTIVE_JOB")
    if any(job.get("name") == CHECK for job in spec.get("jobs", [])):
        raise PermissionError("INTELLIGENCE_DAILY_REFRESH_REQUIRES_NO_PREFLIGHT_JOB")
    aligned = sync_daily_job_command(
        sync_daily_job_size(sync_daily_job_schedule(with_baseline_digests(spec, digest)))
    )
    if other_job_sizes(aligned) != other_job_sizes(spec):
        raise PermissionError("INTELLIGENCE_DAILY_OTHER_JOB_SIZE_CHANGED")
    daily = next(job for job in aligned.get("jobs", []) if job.get("name") == NAME)
    _apply_ncbi_placement(daily, keep_existing_email=True)
    place_daily_otel(daily, aligned)
    # A stored EV[...] value is the provider form of a secret already on the job.
    # Rewriting that ciphertext as plaintext is not a separate deployment.
    if _same_except_encrypted_ncbi(spec, aligned):
        return copy.deepcopy(spec)
    return aligned


def platform_update(
    spec: dict[str, Any], *, update_sources: bool
) -> subprocess.CompletedProcess[str]:
    command = [
        "doctl",
        "apps",
        "update",
        APP_ID,
        "--spec",
        "-",
        "--wait",
        "--output",
        "json",
    ]
    if update_sources:
        command.append("--update-sources")
    return subprocess.run(
        command,
        input=json.dumps(spec),
        capture_output=True,
        text=True,
        timeout=1800,
    )


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


MAX_ERROR_INPUT = 131072
MAX_ERROR_MESSAGES = 8
MAX_ERROR_MESSAGE = 2048
MAX_ERROR_TOTAL = 8192


def _error_channel_messages(channel: str) -> list[str]:
    """Decode each CLI channel once; never stringify arbitrary JSON/specs."""
    if not channel.strip():
        return []
    if len(channel) > MAX_ERROR_INPUT:
        return ["[oversized error channel withheld]"]
    try:
        data = json.loads(channel)
    except ValueError:
        if channel.lstrip().startswith(("{", "[")):
            return ["[malformed JSON error channel withheld]"]
        return [channel]
    if isinstance(data, dict) and isinstance(data.get("errors"), list):
        return [
            error["detail"]
            for error in data["errors"][: MAX_ERROR_MESSAGES + 1]
            if isinstance(error, dict) and isinstance(error.get("detail"), str)
        ]
    if isinstance(data, dict) and isinstance(data.get("message"), str):
        return [data["message"]]
    return ["[non-error JSON output withheld]"]


def _secret_representations(values) -> list[str]:
    forms = set()
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        seeds = {value, value.replace("\r\n", "\n"), value.replace("\n", "\r\n")}
        for encoded in (base64.b64encode(value.encode()), base64.urlsafe_b64encode(value.encode())):
            seeds.update({encoded.decode(), encoded.decode().rstrip("=")})
        # Cover JSON/URL escaping, including a doubly escaped error representation.
        frontier = seeds
        forms.update(seeds)
        for _ in range(2):
            generated = set()
            for item in frontier:
                encoded = quote(item, safe="")
                generated.update(
                    {
                        json.dumps(item, ensure_ascii=True)[1:-1],
                        json.dumps(item, ensure_ascii=False)[1:-1].replace("/", "\\/"),
                        encoded,
                        re.sub(r"%[0-9A-F]{2}", lambda m: m[0].lower(), encoded),
                        quote_plus(item, safe=""),
                    }
                )
            frontier = generated - forms
            forms.update(generated)
    return sorted(forms, key=len, reverse=True)


def _redact_error_prose(message: str, representations: list[str]) -> str:
    if message in {
        "[oversized error channel withheld]",
        "[malformed JSON error channel withheld]",
        "[non-error JSON output withheld]",
    }:
        return message
    if len(message) > MAX_ERROR_INPUT:
        return "[oversized error message withheld]"
    message = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", message)
    message = re.sub(
        r"^(?:Error:\s*)?(?:PUT|POST|GET|PATCH|DELETE) https?://\S+: [1-5][0-9]{2} "
        r'\(request "[0-9a-fA-F-]{36}"\)\s*',
        "",
        message,
    )
    for value in representations:
        # Hex casing can vary independently in every URL escape, at any nesting
        # depth represented by this value. Literal secret bytes remain case-sensitive.
        parts = []
        position = 0
        for escape in re.finditer(r"%(?:25)*[0-9a-fA-F]{2}", value):
            parts.extend(
                (re.escape(value[position : escape.start()]), "(?i:%(?:25)*" + escape[0][-2:] + ")")
            )
            position = escape.end()
        parts.append(re.escape(value[position:]))
        message = re.sub("".join(parts), "[REDACTED]", message)
    # A provider can embed a complete or malformed spec after ordinary prose.
    # Withhold it anywhere, including JSON/URL-escaped opening delimiters.
    payload = re.search(
        r"(?i)\{|\[\s*[\{\[\"']|%(?:25)*7b|%(?:25)*5b|"
        r"\\+(?:u007b|x7b|u005b|x5b)|"
        r"\b(?:spec|jobs|services|workers|envs)\s*:\s*(?:[\r\n-]|\\+[nr])|"
        r"(?:request|response)\s+(?:body|headers)\s*:|[<>]\s*(?:PUT|POST|GET|HTTP/)",
        message,
    )
    if payload:
        message = message[: payload.start()] + "[structured payload or trace withheld]"
    message = re.sub(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)",
        "[REDACTED PRIVATE KEY]",
        message,
        flags=re.DOTALL,
    )
    message = re.sub(r"EV\[[^\]\r\n]*\]", "[REDACTED]", message)
    message = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [REDACTED]", message)
    message = re.sub(
        r"\b(?:dop_v1_|doo_v1_|gh[pousr]_|github_pat_)[A-Za-z0-9_]+\b",
        "[REDACTED TOKEN]",
        message,
    )
    message = re.sub(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "[REDACTED KEY]", message)
    message = re.sub(
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
        "[REDACTED TOKEN]",
        message,
    )
    message = re.sub(
        r"(?i)(\b(?:authorization|[A-Z0-9_]*(?:token|secret|password|passwd|passphrase|"
        r"api_key|access_key(?:_id)?|private_key(?:_b64)?|registry_credentials))\b\s*[:=]\s*)"
        r"""(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;]+)""",
        r"\1[REDACTED]",
        message,
    )
    message = re.sub(r"(https?://)[^\s/@:]+:[^\s/@]+@", r"\1[REDACTED]@", message)
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", message).strip()


def validation_metadata(stderr: str, stdout: str = "", sensitive_values=()) -> dict:
    messages = _error_channel_messages(stderr) + _error_channel_messages(stdout)
    joined = "\n".join(messages)
    status = re.search(r"https://api\.digitalocean\.com/[^\s:]+: ([1-5][0-9]{2})\b", joined)
    request = re.search(r'\(request "([0-9a-fA-F-]{36})"\)', joined)
    representations = _secret_representations(sensitive_values)
    prose = []
    remaining = MAX_ERROR_TOTAL
    truncated = len(messages) > MAX_ERROR_MESSAGES
    for message in messages[:MAX_ERROR_MESSAGES]:
        safe = _redact_error_prose(message, representations)
        limit = min(MAX_ERROR_MESSAGE, remaining)
        if len(safe) > limit:
            safe = safe[: max(0, limit - 12)] + " [TRUNCATED]"
            truncated = True
        prose.append(safe)
        remaining -= len(safe)
        if remaining <= 12:
            truncated = True
            break
    return {
        "status": status[1] if status else "UNKNOWN",
        "request_id": request[1].lower() if request else "UNKNOWN",
        "redacted_messages": prose,
        "truncated": truncated,
        "raw_output_withheld": True,
        "root_cause_established": False,
    }


def update_failure(stderr: str, stdout: str = "", sensitive_values=()) -> str:
    metadata = validation_metadata(stderr, stdout, sensitive_values)
    joined = "\n".join(metadata["redacted_messages"])
    category = "UNCLASSIFIED"
    for text, code in (
        ("secret env value must not be encrypted", "ENCRYPTED_SECRET_REJECTED"),
        ("should be at most 32 chars long", "COMPONENT_NAME_TOO_LONG"),
        ("Unable to authenticate", "AUTHENTICATION_REJECTED"),
        ("not authorized", "AUTHORIZATION_REJECTED"),
        ("not configured for this app", "IMAGE_DIGEST_NOT_CONFIGURED"),
    ):
        if text in joined:
            category = code
            break
    return (
        "INTELLIGENCE_DAILY_PLATFORM_UPDATE_FAILED_INSPECT_OUTCOME"
        f" status={metadata['status']} request_id={metadata['request_id']} category={category}"
        " validation=" + json.dumps(metadata, sort_keys=True)
    )


def diagnostic_sensitive_values(spec):
    """Collect values for redaction only; never return them to a log or artifact."""
    values = [os.environ.get("DIGITALOCEAN_ACCESS_TOKEN", "")]
    # Unknown keys are private by default, even with GENERAL or omitted type.
    # This avoids guessing every possible credential name (API_KEY, PASSWD, etc.).
    public_keys = {
        "TOPX_ENV",
        "ENABLE_PRODUCTION_EXECUTION",
        "SNOWFLAKE_DATABASE",
        "SNOWFLAKE_ROLE",
        "SNOWFLAKE_WAREHOUSE",
        "SNOWFLAKE_AUTH_METHOD",
        "SPACES_REGION",
        "SPACES_ENDPOINT",
        "SPACES_BUCKET",
        "SPACES_PREFIX",
        "INTELLIGENCE_DAILY_ENABLED",
    }

    def visit(node):
        if isinstance(node, dict):
            envs = node.get("envs")
            if isinstance(envs, list):
                values.extend(
                    e.get("value", "")
                    for e in envs
                    if isinstance(e, dict)
                    and (
                        str(e.get("type", "")).strip().upper() == "SECRET"
                        or e.get("key") not in public_keys
                    )
                )
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(spec)
    return values


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # A rejected token may be an NCBI value. Do not echo unrecognized arguments.
        if message.startswith("unrecognized arguments"):
            raise SystemExit(2)
        super().error(message)


def main() -> None:
    p = _ArgumentParser()
    p.add_argument("--image-digest", required=True)
    p.add_argument("--credential-placement-approved", action="store_true")
    p.add_argument(
        "--phase",
        choices=["preflight", "activate", "refresh-digest"],
        required=True,
    )
    args = p.parse_args()
    if not args.credential_placement_approved:
        raise PermissionError("INTELLIGENCE_DAILY_NEW_COMPONENT_CREDENTIAL_APPROVAL_REQUIRED")
    # Preflight and activate build a new component from the template, which has
    # no NCBI email. Refuse before any platform read or update. Refresh can
    # keep an email that is already stored on the standing job.
    if args.phase in {"preflight", "activate"} and _nonempty_process_env("NCBI_EMAIL") is None:
        raise PermissionError(NCBI_EMAIL_REQUIRED)
    app = get(["apps", "get", APP_ID])
    if app.get("in_progress_deployment"):
        raise PermissionError("INTELLIGENCE_DAILY_COMPETING_DEPLOYMENT")
    if args.phase == "refresh-digest":
        sizes_before = other_job_sizes(app["spec"])
        spec = refresh_operational_digests(app["spec"], args.image_digest)
        if spec != app["spec"]:
            align = platform_update(spec, update_sources=False)
            if align.returncode:
                raise RuntimeError(
                    update_failure(align.stderr, align.stdout, diagnostic_sensitive_values(spec))
                )
            app = get(["apps", "get", APP_ID])
            if app.get("in_progress_deployment"):
                raise PermissionError("INTELLIGENCE_DAILY_BASELINE_ALIGNMENT_INCOMPLETE")
        if baseline_needs_digest_alignment(app["spec"], args.image_digest):
            raise PermissionError("INTELLIGENCE_DAILY_REFRESH_DIGEST_INCOMPLETE")
        if daily_job_size(app["spec"]) != DAILY_JOB_INSTANCE_SIZE_SLUG:
            raise PermissionError("INTELLIGENCE_DAILY_POST_DEPLOY_SIZE_MISMATCH")
        if other_job_sizes(app["spec"]) != sizes_before:
            raise PermissionError("INTELLIGENCE_DAILY_OTHER_JOB_SIZE_CHANGED")
        print(
            json.dumps(
                {
                    "phase": args.phase,
                    "app_id": APP_ID,
                    "deployment_id": app["active_deployment"]["id"],
                    "operational_jobs_aligned": True,
                    "daily_instance_size_slug": DAILY_JOB_INSTANCE_SIZE_SLUG,
                    "credential_provisioning": False,
                    **ncbi_presence(app["spec"]),
                }
            )
        )
        return
    if args.phase == "activate":
        verify_preflight(
            get(["apps", "get-deployment", APP_ID, app["active_deployment"]["id"]]),
            args.image_digest,
        )
    if baseline_needs_digest_alignment(app["spec"], args.image_digest):
        aligned = with_baseline_digests(app["spec"], args.image_digest)
        align = platform_update(aligned, update_sources=False)
        if align.returncode:
            raise RuntimeError(
                update_failure(align.stderr, align.stdout, diagnostic_sensitive_values(aligned))
            )
        app = get(["apps", "get", APP_ID])
        if app.get("in_progress_deployment"):
            raise PermissionError("INTELLIGENCE_DAILY_BASELINE_ALIGNMENT_INCOMPLETE")
    preserved_baseline = {j["name"]: j for j in app["spec"]["jobs"] if j.get("name") in BASE}
    spec = render(app["spec"], args.image_digest, args.phase)
    r = platform_update(spec, update_sources=True)
    if r.returncode:
        raise RuntimeError(update_failure(r.stderr, r.stdout, diagnostic_sensitive_values(spec)))
    current = get(["apps", "get", APP_ID])
    before = preserved_baseline
    after = {j["name"]: j for j in current["spec"]["jobs"] if j.get("name") in BASE}
    if before != after or current.get("in_progress_deployment"):
        raise PermissionError("INTELLIGENCE_DAILY_POST_DEPLOY_BASELINE_CHANGED")
    installed = next(
        (j for j in current["spec"]["jobs"] if j["name"] == spec["jobs"][-1]["name"]), None
    )
    if not isinstance(installed, dict) or not _deployed_component_matches(
        installed, spec["jobs"][-1]
    ):
        raise PermissionError("INTELLIGENCE_DAILY_POST_DEPLOY_COMPONENT_MISMATCH")
    print(
        json.dumps(
            {
                "phase": args.phase,
                "app_id": APP_ID,
                "deployment_id": current["active_deployment"]["id"],
                "original_six_jobs_preserved": True,
                "credential_provisioning": False,
                **ncbi_presence(current["spec"]),
            }
        )
    )


if __name__ == "__main__":
    main()
