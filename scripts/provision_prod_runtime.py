"""Interactively provision the protected DigitalOcean PROD runtime.

Run this only in a user-controlled terminal. Secrets are prompted locally,
held in process memory, sent directly to the intended services, and never
written to disk or echoed.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
from pathlib import Path

import yaml

from lyme_gap_atlas_data.preflight import run_preflight

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / ".do" / "app.prod.yaml"
PROD_APP_NAME = "oh-lyme-data-prod"


def _secret(name: str) -> str:
    value = getpass.getpass(f"{name}: ")
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _value(name: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{name}{suffix}: ").strip()
    return value or (default or "")


def _doctl(*args: str, stdin: str | None = None) -> str:
    completed = subprocess.run(
        ["doctl", *args],
        check=True,
        input=stdin,
        text=True,
        capture_output=True,
    )
    return completed.stdout


def _app_exists() -> bool:
    apps = json.loads(_doctl("apps", "list", "--output", "json"))
    return any(app.get("spec", {}).get("name") == PROD_APP_NAME for app in apps)


def _runtime_environment(private_key_b64: str) -> dict[str, str]:
    return {
        "TOPX_ENV": "prod",
        "ENABLE_PRODUCTION_EXECUTION": "true",
        "SNOWFLAKE_ACCOUNT": _value("SNOWFLAKE_ACCOUNT", "TXB06009"),
        "SNOWFLAKE_USER": "OH_LYME_PROD_PIPELINE_SVC",
        "SNOWFLAKE_ROLE": "OH_LYME_PROD_PIPELINE_RUNTIME",
        "SNOWFLAKE_WAREHOUSE": "OH_LYME_PROD_INGEST_XS_WH",
        "SNOWFLAKE_DATABASE": "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        "SNOWFLAKE_AUTH_METHOD": "key_pair",
        "SNOWFLAKE_PRIVATE_KEY_B64": private_key_b64,
        "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE": _secret("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"),
        "DATA_GOV_API_KEY": _secret("DATA_GOV_API_KEY"),
        "SOCRATA_APP_TOKEN": _secret("SOCRATA_APP_TOKEN"),
        "NCBI_EMAIL": _value("NCBI_EMAIL"),
        "NCBI_API_KEY": _secret("NCBI_API_KEY"),
        "NEO4J_URI": _value("NEO4J_URI"),
        "NEO4J_RUNTIME_PASSWORD": _secret("NEO4J_RUNTIME_PASSWORD"),
        "GROQ_API_KEY": _secret("GROQ_API_KEY"),
        "OPENAI_API_KEY": _secret("OPENAI_API_KEY"),
        "SPACES_REGION": "sfo3",
        "SPACES_ENDPOINT": "https://sfo3.digitaloceanspaces.com",
        "SPACES_BUCKET": "one-health-lyme-gap-atlas-data-prod",
        "SPACES_PREFIX": "prod",
        "SPACES_ACCESS_KEY_ID": _secret("SPACES_ACCESS_KEY_ID"),
        "SPACES_SECRET_ACCESS_KEY": _secret("SPACES_SECRET_ACCESS_KEY"),
    }


def _render_spec(image_digest: str, values: dict[str, str]) -> str:
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    for job in spec["jobs"]:
        job["image"]["digest"] = image_digest
        for env in job["envs"]:
            if env["key"] in values:
                env["value"] = values[env["key"]]
    return yaml.safe_dump(spec, sort_keys=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        raise ValueError("Review the target and pass --confirm to create the PROD job")
    if _app_exists():
        raise ValueError(f"{PROD_APP_NAME} already exists; refusing to overwrite its secrets")

    private_key_path = Path(_value("Encrypted private-key path"))
    if not private_key_path.is_file():
        raise ValueError("Encrypted private-key file was not found")
    private_key_b64 = __import__("base64").b64encode(private_key_path.read_bytes()).decode()
    values = _runtime_environment(private_key_b64)
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        preflight = run_preflight()
        print(json.dumps(preflight, default=str))
        created = _doctl(
            "apps",
            "create",
            "--spec",
            "-",
            "--format",
            "ID,Spec.Name,ActiveDeployment.ID",
            stdin=_render_spec(args.image_digest, values),
        )
        print(created.strip())
    finally:
        for key, prior_value in previous.items():
            if prior_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior_value


if __name__ == "__main__":
    main()
