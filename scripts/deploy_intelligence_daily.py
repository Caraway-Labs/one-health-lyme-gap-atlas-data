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
    # Refuse structured payloads and raw HTTP traces rather than risk logging a spec.
    if re.search(
        r'(?im)^\s*(?:[\{\[]|["\'](?:spec|envs)["\']\s*:|'
        r"(?:request|response)\s+(?:body|headers)\s*:|[<>]\s*(?:PUT|POST|GET|HTTP/))",
        message,
    ):
        return "[structured payload or trace withheld]"
    for value in representations:
        message = message.replace(value, "[REDACTED]")
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
    # Keep the provider's prose, not the transport envelope or arbitrary controls.
    message = re.sub(
        r"^(?:Error:\s*)?(?:PUT|POST|GET|PATCH|DELETE) https?://\S+: [1-5][0-9]{2} "
        r'\(request "[0-9a-fA-F-]{36}"\)\s*',
        "",
        message,
    )
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

    def visit(node):
        if isinstance(node, dict):
            envs = node.get("envs")
            if isinstance(envs, list):
                values.extend(
                    e.get("value", "")
                    for e in envs
                    if isinstance(e, dict)
                    and (
                        e.get("type") == "SECRET"
                        or re.search(
                            r"TOKEN|SECRET|PASSWORD|PASSPHRASE|PRIVATE_KEY|ACCESS_KEY|CREDENTIAL",
                            str(e.get("key", "")),
                            re.IGNORECASE,
                        )
                    )
                )
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(spec)
    return values


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
        raise RuntimeError(update_failure(r.stderr, r.stdout, diagnostic_sensitive_values(spec)))
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
