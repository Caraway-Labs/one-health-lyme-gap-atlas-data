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


def _env(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["key"]: entry for entry in job["envs"]}


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
    credential_keys = {
        "SNOWFLAKE_ACCOUNT",
        "SNOWFLAKE_USER",
        "SNOWFLAKE_PRIVATE_KEY_B64",
        "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE",
    }
    if spaces:
        credential_keys |= {"SPACES_ACCESS_KEY_ID", "SPACES_SECRET_ACCESS_KEY"}
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
    secrets: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return a new spec; reject drift and every unbounded invocation."""
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

    template_name = (
        "cdc-operations-watchdog"
        if operation == "preflight"
        else "catalog-discovery"
        if operation == "discover"
        else "approved-source-ingestion"
    )
    result = copy.deepcopy(baseline)
    template = next(job for job in result["jobs"] if job["name"] == template_name)
    _require_runtime(template, spaces=operation != "preflight")
    job = copy.deepcopy(template)
    job["name"] = f"literature-{operation}-once"
    job["kind"] = "PRE_DEPLOY"
    job.pop("schedule", None)
    # Remove unrelated source tokens. The temporary job has only the credentials
    # its chosen literature stage needs, and none are added to persistent jobs.
    unrelated = {"DATA_GOV_API_KEY", "SOCRATA_APP_TOKEN", "OTEL_EXPORTER_OTLP_HEADERS"}
    job["envs"] = [entry for entry in job["envs"] if entry["key"] not in unrelated]
    supplied = secrets or {}
    if operation == "preflight":
        result["vpc"] = {"id": VPC_ID}
        _add_secret(job, "NEO4J_RUNTIME_PASSWORD", supplied.get("NEO4J_RUNTIME_PASSWORD", ""))
        job["envs"] += [
            {"key": "NEO4J_URI", "scope": "RUN_TIME", "value": NEO4J_URI},
            {"key": "NEO4J_RUNTIME_USER", "scope": "RUN_TIME", "value": "graph_runtime"},
        ]
        job["run_command"] = (
            "/app/.venv/bin/python -c 'import os; from neo4j import GraphDatabase; "
            'd=GraphDatabase.driver(os.environ["NEO4J_URI"], '
            'auth=(os.environ["NEO4J_RUNTIME_USER"], '
            'os.environ["NEO4J_RUNTIME_PASSWORD"])); '
            "d.verify_connectivity(); d.close()'"
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
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    result = build_spec(
        baseline,
        operation=args.operation,
        image_digest=args.image_digest,
        family=args.family,
        max_records=args.max_records,
        batch_size=args.batch_size,
        estimated_cost_usd=args.estimated_cost_usd,
        secrets={
            key: os.environ.get(key, "")
            for key in (
                "NCBI_EMAIL",
                "NCBI_API_KEY",
                "NEO4J_RUNTIME_PASSWORD",
                "GROQ_API_KEY",
                "OPENAI_API_KEY",
            )
        },
    )
    args.output.write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
