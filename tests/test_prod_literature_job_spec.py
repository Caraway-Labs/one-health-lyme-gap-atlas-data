"""Regression coverage for the protected one-shot PROD literature topology."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from runpy import run_path

import pytest
import yaml

build_spec = run_path(
    str(Path(__file__).resolve().parents[1] / "scripts" / "prod_literature_job_spec.py")
)["build_spec"]

DIGEST = "sha256:" + "a" * 64


def _baseline() -> dict:
    def job(name: str, *, spaces: bool = True) -> dict:
        envs = [
            {"key": key, "value": value}
            for key, value in {
                "TOPX_ENV": "prod",
                "ENABLE_PRODUCTION_EXECUTION": "true",
                "SNOWFLAKE_DATABASE": "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
                "SNOWFLAKE_ROLE": "OH_LYME_PROD_RUNTIME",
                "SNOWFLAKE_AUTH_METHOD": "key_pair",
            }.items()
        ]
        envs += [
            {"key": key, "type": "SECRET", "value": "encrypted"}
            for key in (
                "SNOWFLAKE_ACCOUNT",
                "SNOWFLAKE_USER",
                "SNOWFLAKE_PRIVATE_KEY_B64",
                "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE",
            )
        ]
        if spaces:
            envs += [
                {"key": "SPACES_BUCKET", "value": "one-health-lyme-gap-atlas-data-prod"},
                {"key": "SPACES_PREFIX", "value": "prod"},
                {"key": "SPACES_ACCESS_KEY_ID", "type": "SECRET", "value": "encrypted"},
                {"key": "SPACES_SECRET_ACCESS_KEY", "type": "SECRET", "value": "encrypted"},
            ]
        return {
            "name": name,
            "kind": "SCHEDULED",
            "schedule": {"cron": "15 * * * *"},
            "image": {"digest": DIGEST},
            "run_command": "existing command",
            "envs": envs,
        }

    names = (
        "catalog-discovery",
        "approved-source-ingestion",
        "catalog-registration-01",
        "catalog-registration-02",
        "catalog-registration-03",
        "cdc-operations-watchdog",
    )
    return {
        "name": "oh-lyme-data-prod",
        "region": "sfo",
        "vpc": {"id": "a937d8dd-4ee9-4de2-a8df-b32e7ad4098e"},
        "jobs": [job(name, spaces=name != names[-1]) for name in names],
    }


@pytest.mark.parametrize("operation", ["preflight", "discover", "extract", "build-corpus"])
def test_one_shot_job_is_separate_and_restores_clean_baseline(operation: str) -> None:
    baseline = _baseline()
    before = deepcopy(baseline)
    result = build_spec(
        baseline,
        operation=operation,
        image_digest=DIGEST,
        family="vector_host_pathogen",
        max_records=10,
        batch_size=10,
        secrets={
            "NCBI_EMAIL": "operator@example.test",
            "NEO4J_RUNTIME_PASSWORD": "graph-secret",
            "GROQ_API_KEY": "groq-secret",
            "OPENAI_API_KEY": "openai-secret",
        },
    )
    assert baseline == before
    assert result["jobs"][:6] == before["jobs"]
    temporary = result["jobs"][-1]
    assert temporary["name"] == f"literature-{operation}-once"
    assert temporary["kind"] == "PRE_DEPLOY"
    assert "schedule" not in temporary
    assert temporary["image"]["digest"] == DIGEST
    assert all(
        "NCBI_EMAIL" not in {env["key"] for env in job["envs"]} for job in result["jobs"][:6]
    )
    if operation == "discover":
        assert "--max-records 10 --batch-size 10" in temporary["run_command"]
        assert "--family vector_host_pathogen" in temporary["run_command"]
        assert "PAPERS_REQUIRE_HUMAN_REVIEW" in {env["key"] for env in temporary["envs"]}
    if operation == "extract":
        assert temporary["run_command"].endswith("pmc-extract --estimated-cost-usd 0.20 --confirm")
        assert "NEO4J_RUNTIME_PASSWORD" in {env["key"] for env in temporary["envs"]}
    if operation in {"preflight", "extract"}:
        assert result["vpc"]["id"] == "a937d8dd-4ee9-4de2-a8df-b32e7ad4098e"
    if operation == "build-corpus":
        assert temporary["run_command"].endswith("build-retrieval-corpus --confirm")


def test_live_app_without_vpc_gets_private_network_only_for_graph_stage() -> None:
    baseline = _baseline()
    baseline.pop("vpc")
    preflight = build_spec(
        baseline,
        operation="preflight",
        image_digest=DIGEST,
        secrets={"NEO4J_RUNTIME_PASSWORD": "graph-secret"},
    )
    assert "vpc" not in baseline
    assert preflight["vpc"]["id"] == "a937d8dd-4ee9-4de2-a8df-b32e7ad4098e"
    assert "literature-preflight --operation extract" in preflight["jobs"][-1]["run_command"]


@pytest.mark.parametrize(
    ("change", "operation"),
    [
        (lambda spec: spec["jobs"].pop(), "preflight"),
        (lambda spec: spec["jobs"][0].update(kind="PRE_DEPLOY"), "preflight"),
        (lambda spec: spec["jobs"][0]["image"].update(digest="sha256:" + "b" * 64), "preflight"),
        (lambda spec: spec["jobs"][0]["envs"][0].update(value="dev"), "discover"),
    ],
)
def test_drift_fails_closed(change, operation: str) -> None:
    spec = _baseline()
    change(spec)
    with pytest.raises(ValueError):
        build_spec(
            spec, operation=operation, image_digest=DIGEST, secrets={"NCBI_EMAIL": "x@y.test"}
        )


def test_missing_provider_credentials_and_unbounded_discovery_fail_closed() -> None:
    for kwargs in (
        {"max_records": 401},
        {"max_records": 400, "batch_size": 201},
        {"max_records": 10, "batch_size": 11},
        {"secrets": {}},
    ):
        with pytest.raises(ValueError):
            build_spec(_baseline(), operation="discover", image_digest=DIGEST, **kwargs)
    with pytest.raises(ValueError):
        build_spec(_baseline(), operation="extract", image_digest=DIGEST, secrets={})
    with pytest.raises(ValueError, match="0.20"):
        build_spec(
            _baseline(),
            operation="extract",
            image_digest=DIGEST,
            estimated_cost_usd="0.10",
            secrets={"NEO4J_RUNTIME_PASSWORD": "x", "GROQ_API_KEY": "x", "OPENAI_API_KEY": "x"},
        )
    with pytest.raises(ValueError):
        build_spec(
            _baseline(),
            operation="extract",
            image_digest=DIGEST,
            estimated_cost_usd="0.10; echo unsafe",
            secrets={"NEO4J_RUNTIME_PASSWORD": "x", "GROQ_API_KEY": "x", "OPENAI_API_KEY": "x"},
        )


def test_governed_discovery_accepts_existing_worker_limit() -> None:
    spec = build_spec(
        _baseline(),
        operation="discover",
        image_digest=DIGEST,
        max_records=400,
        batch_size=25,
        secrets={"NCBI_EMAIL": "steward@example.test"},
    )
    assert "--max-records 400 --batch-size 25" in spec["jobs"][-1]["run_command"]


def test_repo_prod_spec_has_no_scheduled_literature_jobs() -> None:
    spec = yaml.safe_load(Path(".do/app.prod.yaml").read_text(encoding="utf-8"))
    jobs = spec["jobs"]
    assert len(jobs) == 6
    assert all(job["kind"] == "SCHEDULED" for job in jobs)
    assert all("pubmed" not in job["name"] and "extraction" not in job["name"] for job in jobs)
    workflow = Path(".github/workflows/run-prod-literature-once.yml").read_text(encoding="utf-8")
    assert "environment: production" in workflow
    assert '[[ "$MAX_RECORDS" =~ ^[0-9]{1,3}$ ]]' in workflow
    assert 'test "$GITHUB_REF" = refs/heads/main' in workflow
    assert "trap restore_baseline EXIT" in workflow
    assert 'doctl apps update "$PROD_APP_ID" --spec "$baseline_spec" --wait' in workflow


def test_all_prod_app_spec_mutators_share_one_non_canceling_lock() -> None:
    workflows = Path(".github/workflows")
    mutators = []
    for path in workflows.glob("*.yml"):
        source = path.read_text(encoding="utf-8")
        if 'doctl apps update "$PROD_APP_ID"' not in source:
            continue
        mutators.append(path.name)
        definition = yaml.safe_load(source)
        assert definition["concurrency"] == {
            "group": "prod-app-topology",
            "cancel-in-progress": False,
        }, path.name
    assert "promote-prod.yml" in mutators
    assert "run-prod-literature-once.yml" in mutators
    assert len(mutators) == 7
