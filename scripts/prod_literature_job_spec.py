"""Build one bounded, temporary PROD literature job from the live six-job spec.

The input and output specs contain provider-encrypted values and must stay in
private temporary files. This module never prints either specification.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

EXPECTED_JOBS = frozenset(
    {
        "catalog-discovery",
        "approved-source-ingestion",
        "catalog-registration-01",
        "catalog-registration-02",
        "catalog-registration-03",
        "cdc-operations-watchdog",
    }
)
FAMILIES = frozenset(
    {
        "surveillance_epidemiology",
        "vector_host_pathogen",
        "environment_exposure",
        "diagnostics_interventions_outcomes",
    }
)
PROD_DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_PROD"
PROD_ROLE = "OH_LYME_PROD_RUNTIME"
PROD_BUCKET = "one-health-lyme-gap-atlas-data-prod"
NEO4J_URI = "bolt://10.116.0.3:7687"
VPC_ID = "a937d8dd-4ee9-4de2-a8df-b32e7ad4098e"
RUNTIME_CREDENTIALS = (
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PRIVATE_KEY_B64",
    "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE",
    "SPACES_ACCESS_KEY_ID",
    "SPACES_SECRET_ACCESS_KEY",
)
LITERATURE_SECRETS = {
    "discover": ("NCBI_EMAIL",),
    "extract": ("NEO4J_RUNTIME_PASSWORD", "GROQ_API_KEY", "OPENAI_API_KEY"),
    "build-corpus": (),
}


def secret_readiness(
    baseline: dict[str, Any],
    *,
    operation: str,
    secrets: dict[str, str],
    workflow_run_id: str = "",
) -> dict[str, Any]:
    """Aggregate known credential omissions without revealing any values or making calls."""
    if operation not in {"preflight", *LITERATURE_SECRETS}:
        raise ValueError("unsupported literature operation")
    stages = tuple(LITERATURE_SECRETS) if operation == "preflight" else (operation,)
    blockers: list[dict[str, Any]] = []
    raw_jobs = baseline.get("jobs", [])
    jobs = [job for job in raw_jobs if isinstance(job, dict)] if isinstance(raw_jobs, list) else []
    for stage in stages:
        template_name = "catalog-discovery" if stage == "discover" else "approved-source-ingestion"
        template = next((job for job in jobs if job.get("name") == template_name), {})
        env = _env(template) if template else {}
        for key in RUNTIME_CREDENTIALS:
            entry = env.get(key, {})
            if entry.get("type") != "SECRET" or not entry.get("value"):
                blockers.append(
                    {
                        "stage": stage,
                        "capability": key,
                        "failure_category": "preflight_configuration",
                        "remediation_owner": "production_platform_owner",
                        "retryable": False,
                        "next_action": "repair_existing_runtime_credential_configuration",
                    }
                )
        for key in LITERATURE_SECRETS[stage]:
            if not secrets.get(key):
                blockers.append(
                    {
                        "stage": stage,
                        "capability": key,
                        "failure_category": "preflight_configuration",
                        "remediation_owner": "production_environment_owner",
                        "retryable": False,
                        "next_action": "configure_required_environment_secret",
                    }
                )
    return {
        "run_id": workflow_run_id
        if re.fullmatch(r"[0-9]{1,20}", workflow_run_id)
        else str(uuid.uuid4()),
        "operation": operation,
        "scope": "host_secret_presence",
        "status": "BLOCKED" if blockers else "READY",
        "runtime_readiness": "NOT_CHECKED",
        "blockers": blockers,
        "optional_configuration": {"NCBI_API_KEY_present": bool(secrets.get("NCBI_API_KEY"))},
    }


def _env(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = job.get("envs", [])
    return (
        {
            entry["key"]: entry
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("key"), str)
        }
        if isinstance(entries, list)
        else {}
    )


def host_readiness(
    baseline: dict[str, Any],
    *,
    operation: str,
    image_digest: str,
    secrets: dict[str, str],
    workflow_run_id: str = "",
) -> dict[str, Any]:
    """Aggregate existing baseline/configuration guards with credential omissions."""
    report = secret_readiness(
        baseline, operation=operation, secrets=secrets, workflow_run_id=workflow_run_id
    )
    report["scope"] = "host_baseline_configuration"
    blockers = report["blockers"]

    def check(valid: bool, capability: str, stage: str = "host") -> None:
        if not valid:
            blockers.append(
                {
                    "stage": stage,
                    "capability": capability,
                    "failure_category": "preflight_configuration",
                    "remediation_owner": "production_platform_owner",
                    "retryable": False,
                    "next_action": "restore_reviewed_baseline_configuration",
                }
            )

    check(baseline.get("name") == "oh-lyme-data-prod", "reviewed_production_app")
    check(baseline.get("region") == "sfo", "reviewed_production_region")
    vpc = baseline.get("vpc")
    check(not vpc or isinstance(vpc, dict) and vpc.get("id") == VPC_ID, "reviewed_private_vpc")
    check(re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest) is not None, "immutable_image_digest")
    raw_jobs = baseline.get("jobs")
    jobs = [job for job in raw_jobs if isinstance(job, dict)] if isinstance(raw_jobs, list) else []
    check(
        isinstance(raw_jobs, list) and len(raw_jobs) == len(jobs) == 6, "reviewed_six_job_topology"
    )
    names = [job.get("name") for job in jobs]
    check(
        all(isinstance(name, str) for name in names) and set(names) == EXPECTED_JOBS,
        "reviewed_scheduled_job_names",
    )
    check(all(job.get("kind") == "SCHEDULED" for job in jobs), "reviewed_scheduled_job_kinds")
    check(
        all(
            isinstance(job.get("image"), dict) and job["image"].get("digest") == image_digest
            for job in jobs
        ),
        "active_job_image_digest",
    )
    stages = tuple(LITERATURE_SECRETS) if operation == "preflight" else (operation,)
    required = {
        "TOPX_ENV": "prod",
        "ENABLE_PRODUCTION_EXECUTION": "true",
        "SNOWFLAKE_DATABASE": PROD_DATABASE,
        "SNOWFLAKE_ROLE": PROD_ROLE,
        "SNOWFLAKE_AUTH_METHOD": "key_pair",
        "SPACES_BUCKET": PROD_BUCKET,
        "SPACES_PREFIX": "prod",
    }
    for stage in stages:
        name = "catalog-discovery" if stage == "discover" else "approved-source-ingestion"
        matches = [job for job in jobs if job.get("name") == name]
        check(len(matches) == 1, "one_reviewed_runtime_template", stage)
        template = matches[0] if len(matches) == 1 else {}
        entries = template.get("envs")
        env = _env(template)
        check(
            isinstance(entries, list) and len(entries) == len(env),
            "unique_valid_template_environment",
            stage,
        )
        for key, value in required.items():
            check(env.get(key, {}).get("value") == value, key, stage)
        for key in LITERATURE_SECRETS[stage]:
            check(key not in env, "no_preexisting_" + key, stage)
        if stage == "discover" and secrets.get("NCBI_API_KEY"):
            check("NCBI_API_KEY" not in env, "no_preexisting_NCBI_API_KEY", stage)
    report["status"] = "BLOCKED" if blockers else "READY"
    return report


def _require_runtime(job: dict[str, Any], *, spaces: bool) -> None:
    env = _env(job)
    required = {
        "TOPX_ENV": "prod",
        "ENABLE_PRODUCTION_EXECUTION": "true",
        "SNOWFLAKE_DATABASE": PROD_DATABASE,
        "SNOWFLAKE_ROLE": PROD_ROLE,
        "SNOWFLAKE_AUTH_METHOD": "key_pair",
    }
    if spaces:
        required |= {"SPACES_BUCKET": PROD_BUCKET, "SPACES_PREFIX": "prod"}
    if any(env.get(key, {}).get("value") != value for key, value in required.items()):
        raise ValueError("baseline runtime environment differs from reviewed PROD values")
    credential_keys = set(RUNTIME_CREDENTIALS[:4])
    if spaces:
        credential_keys |= set(RUNTIME_CREDENTIALS[4:])
    if any(env.get(key, {}).get("type") != "SECRET" for key in credential_keys):
        raise ValueError("baseline is missing a protected runtime credential")


def _add_secret(job: dict[str, Any], name: str, value: str) -> None:
    if not value:
        raise ValueError(f"required production secret {name} is unavailable")
    if name in _env(job):
        raise ValueError(f"unexpected pre-existing {name} on template job")
    job["envs"].append({"key": name, "scope": "RUN_TIME", "type": "SECRET", "value": value})


def build_spec(
    baseline: dict[str, Any],
    *,
    operation: str,
    image_digest: str,
    family: str = "surveillance_epidemiology",
    max_records: int = 25,
    batch_size: int = 25,
    estimated_cost_usd: str = "0.20",
    discovery_run_id: str = "",
    source_commit: str = "",
    workflow_run_id: str = "",
    secrets: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return a new spec; reject drift and every unbounded invocation."""
    readiness = host_readiness(
        baseline,
        operation=operation,
        image_digest=image_digest,
        secrets=secrets or {},
        workflow_run_id=workflow_run_id,
    )
    if readiness["status"] == "BLOCKED":
        raise ValueError("host readiness BLOCKED: " + json.dumps(readiness))
    if baseline.get("name") != "oh-lyme-data-prod":
        raise ValueError("unexpected production app")
    if baseline.get("region") != "sfo":
        raise ValueError("production app is not in the reviewed SFO region")
    if baseline.get("vpc") and baseline["vpc"].get("id") != VPC_ID:
        raise ValueError("production app has an unexpected private VPC")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
        raise ValueError("image digest must be an immutable SHA-256 reference")
    jobs = baseline.get("jobs")
    if not isinstance(jobs, list) or len(jobs) != 6:
        raise ValueError("production topology is not the reviewed six-job baseline")
    by_name = {job["name"]: job for job in jobs}
    if set(by_name) != EXPECTED_JOBS or any(job.get("kind") != "SCHEDULED" for job in jobs):
        raise ValueError("production topology differs from reviewed scheduled jobs")
    if any(job.get("image", {}).get("digest") != image_digest for job in jobs):
        raise ValueError("production image digest differs from the reviewed active digest")
    if operation not in {"preflight", "discover", "extract", "build-corpus"}:
        raise ValueError("unsupported literature operation")
    if discovery_run_id:
        try:
            discovery_run_id = str(uuid.UUID(discovery_run_id))
        except ValueError as error:
            raise ValueError("discovery_run_id must be a UUID") from error
    if source_commit and not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source_commit must be a full Git SHA")
    if workflow_run_id and not re.fullmatch(r"[0-9]{1,20}", workflow_run_id):
        raise ValueError("workflow_run_id must be numeric")
    if (
        family not in FAMILIES
        or not 1 <= max_records <= 400
        or not 1 <= batch_size <= min(max_records, 200)
    ):
        raise ValueError("discovery must name an approved family and request 1-400 records")
    try:
        estimate = Decimal(estimated_cost_usd)
    except InvalidOperation as error:
        raise ValueError("estimated cost must be a decimal number") from error
    if not estimate.is_finite() or not Decimal("0.20") <= estimate <= Decimal("20"):
        raise ValueError("estimated cost must be between 0.20 and 20 USD")

    readiness = secret_readiness(
        baseline, operation=operation, secrets=secrets or {}, workflow_run_id=workflow_run_id
    )
    if readiness["status"] == "BLOCKED":
        raise ValueError("host secret readiness BLOCKED: " + json.dumps(readiness))

    template_name = (
        "approved-source-ingestion"
        if operation == "preflight"
        else "catalog-discovery"
        if operation == "discover"
        else "approved-source-ingestion"
    )
    result = copy.deepcopy(baseline)
    template = next(job for job in result["jobs"] if job["name"] == template_name)
    _require_runtime(template, spaces=True)
    job = copy.deepcopy(template)
    job["name"] = f"literature-{operation}-once"
    job["kind"] = "PRE_DEPLOY"
    job["envs"].extend(
        {"key": key, "scope": "RUN_TIME", "value": value}
        for key, value in (
            ("IMAGE_DIGEST", image_digest),
            ("SOURCE_COMMIT", source_commit),
            ("GITHUB_RUN_ID", workflow_run_id),
            ("ATLAS_DISCOVERY_RUN_ID", discovery_run_id),
        )
        if value
    )
    job.pop("schedule", None)
    # Remove unrelated source tokens. Preserve the existing opaque collector
    # headers with the inherited endpoint; neither is added to persistent jobs.
    unrelated = {"DATA_GOV_API_KEY", "SOCRATA_APP_TOKEN"}
    job["envs"] = [entry for entry in job["envs"] if entry["key"] not in unrelated]
    supplied = secrets or {}
    if operation == "preflight":
        result["vpc"] = {"id": VPC_ID}
        for key in ("NCBI_EMAIL", "NEO4J_RUNTIME_PASSWORD", "GROQ_API_KEY", "OPENAI_API_KEY"):
            if supplied.get(key):
                _add_secret(job, key, supplied[key])
        job["envs"] += [
            {"key": "NEO4J_URI", "scope": "RUN_TIME", "value": NEO4J_URI},
            {"key": "NEO4J_RUNTIME_USER", "scope": "RUN_TIME", "value": "graph_runtime"},
        ]
        job["run_command"] = (
            "/app/.venv/bin/atlas-data pipeline literature-preflight --operation all"
        )
    elif operation == "discover":
        _add_secret(job, "NCBI_EMAIL", supplied.get("NCBI_EMAIL", ""))
        if supplied.get("NCBI_API_KEY"):
            _add_secret(job, "NCBI_API_KEY", supplied["NCBI_API_KEY"])
        job["envs"].append(
            {"key": "PAPERS_REQUIRE_HUMAN_REVIEW", "scope": "RUN_TIME", "value": "true"}
        )
        job["run_command"] = (
            "/app/.venv/bin/atlas-data pipeline pubmed-discover"
            f" --family {family} --max-records {max_records} --batch-size {batch_size}"
        )
    elif operation == "extract":
        result["vpc"] = {"id": VPC_ID}
        for key in ("NEO4J_RUNTIME_PASSWORD", "GROQ_API_KEY", "OPENAI_API_KEY"):
            _add_secret(job, key, supplied.get(key, ""))
        job["envs"] += [
            {"key": "NEO4J_URI", "scope": "RUN_TIME", "value": NEO4J_URI},
            {"key": "NEO4J_RUNTIME_USER", "scope": "RUN_TIME", "value": "graph_runtime"},
            {"key": "PAPERS_REQUIRE_HUMAN_REVIEW", "scope": "RUN_TIME", "value": "true"},
        ]
        job["run_command"] = (
            "/app/.venv/bin/atlas-data pipeline pmc-extract"
            f" --estimated-cost-usd {estimated_cost_usd} --confirm"
        )
    else:
        job["run_command"] = "/app/.venv/bin/atlas-data pipeline build-retrieval-corpus --confirm"
    result["jobs"].append(job)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--family", default="surveillance_epidemiology")
    parser.add_argument("--max-records", type=int, default=25)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--estimated-cost-usd", default="0.20")
    parser.add_argument("--discovery-run-id", default="")
    parser.add_argument("--source-commit", default="")
    parser.add_argument("--workflow-run-id", default="")
    parser.add_argument("--readiness-report", type=Path)
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    supplied = {
        key: os.environ.get(key, "")
        for key in (
            "NCBI_EMAIL",
            "NCBI_API_KEY",
            "NEO4J_RUNTIME_PASSWORD",
            "GROQ_API_KEY",
            "OPENAI_API_KEY",
        )
    }
    readiness = host_readiness(
        baseline,
        operation=args.operation,
        image_digest=args.image_digest,
        secrets=supplied,
        workflow_run_id=args.workflow_run_id,
    )
    if args.readiness_report:
        args.readiness_report.write_text(json.dumps(readiness), encoding="utf-8")
    if readiness["status"] == "BLOCKED":
        raise SystemExit("host readiness BLOCKED: " + json.dumps(readiness))
    result = build_spec(
        baseline,
        operation=args.operation,
        image_digest=args.image_digest,
        family=args.family,
        max_records=args.max_records,
        batch_size=args.batch_size,
        estimated_cost_usd=args.estimated_cost_usd,
        discovery_run_id=args.discovery_run_id,
        source_commit=args.source_commit,
        workflow_run_id=args.workflow_run_id,
        secrets=supplied,
    )
    args.output.write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
