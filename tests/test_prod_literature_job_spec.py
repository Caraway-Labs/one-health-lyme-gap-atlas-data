"""Regression coverage for the protected one-shot PROD literature topology."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from runpy import run_path

import pytest
import yaml

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prod_literature_job_spec.py"
_MODULE = run_path(
    str(Path(__file__).resolve().parents[1] / "scripts" / "prod_literature_job_spec.py")
)
build_spec = _MODULE["build_spec"]
secret_readiness = _MODULE["secret_readiness"]
host_readiness = _MODULE["host_readiness"]

DIGEST = "sha256:" + "a" * 64


def test_host_report_aggregates_drift_and_secrets_without_echoing_values() -> None:
    baseline = _baseline()
    baseline["name"] = baseline["region"] = "private-sentinel"
    baseline["vpc"] = {"id": "private-sentinel"}
    baseline["jobs"][0]["kind"] = "PRE_DEPLOY"
    baseline["jobs"][0]["image"]["digest"] = "private-sentinel"
    for entry in baseline["jobs"][0]["envs"]:
        if entry["key"] in {"SNOWFLAKE_ROLE", "SPACES_BUCKET"}:
            entry["value"] = "private-sentinel"
    before = deepcopy(baseline)
    report = host_readiness(baseline, operation="preflight", image_digest=DIGEST, secrets={})
    capabilities = {item["capability"] for item in report["blockers"]}
    assert capabilities >= {
        "reviewed_production_app",
        "reviewed_production_region",
        "reviewed_private_vpc",
        "reviewed_scheduled_job_kinds",
        "active_job_image_digest",
        "SNOWFLAKE_ROLE",
        "SPACES_BUCKET",
        "NCBI_EMAIL",
        "GROQ_API_KEY",
        "OPENAI_API_KEY",
        "NEO4J_RUNTIME_PASSWORD",
    }
    assert report["status"] == "BLOCKED"
    assert report["scope"] == "host_baseline_configuration"
    assert report["runtime_readiness"] == "NOT_CHECKED"
    assert "private-sentinel" not in json.dumps(report)
    assert baseline == before
    with pytest.raises(ValueError) as error:
        build_spec(baseline, operation="preflight", image_digest=DIGEST)
    assert capabilities <= {
        item["capability"] for item in json.loads(str(error.value).split(": ", 1)[1])["blockers"]
    }


@pytest.mark.parametrize("jobs", [None, {}, [None], [{"name": []}]])
def test_malformed_topology_returns_sanitized_aggregate_blockers(jobs: object) -> None:
    baseline = _baseline()
    baseline["jobs"] = jobs
    report = host_readiness(baseline, operation="preflight", image_digest=DIGEST, secrets={})
    assert report["status"] == "BLOCKED"
    assert "reviewed_six_job_topology" in {item["capability"] for item in report["blockers"]}


def test_duplicate_template_env_and_preexisting_secret_are_reported_together() -> None:
    baseline = _baseline()
    baseline["jobs"][0]["envs"].append(deepcopy(baseline["jobs"][0]["envs"][0]))
    baseline["jobs"][0]["envs"].append({"key": "NCBI_EMAIL", "value": "private-sentinel"})
    report = host_readiness(
        baseline,
        operation="discover",
        image_digest=DIGEST,
        secrets={"NCBI_EMAIL": "operator@example.test"},
    )
    assert {item["capability"] for item in report["blockers"]} >= {
        "unique_valid_template_environment",
        "no_preexisting_NCBI_EMAIL",
    }
    assert "private-sentinel" not in json.dumps(report)


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
def test_existing_opaque_collector_headers_follow_only_temporary_job(
    operation: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _baseline()
    endpoint = {
        "key": "OTEL_EXPORTER_OTLP_ENDPOINT",
        "scope": "RUN_TIME",
        "value": "https://collector.example.invalid/v1/traces",
    }
    headers = {
        "key": "OTEL_EXPORTER_OTLP_HEADERS",
        "scope": "RUN_TIME",
        "type": "SECRET",
        "value": "DUMMY_OPAQUE_ENCRYPTED_HEADER_SENTINEL",
    }
    for job in baseline["jobs"]:
        job["envs"] += [
            deepcopy(endpoint),
            deepcopy(headers),
            {"key": "DATA_GOV_API_KEY", "type": "SECRET", "value": "dummy-source"},
            {"key": "SOCRATA_APP_TOKEN", "type": "SECRET", "value": "dummy-source"},
        ]
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
            "NEO4J_RUNTIME_PASSWORD": "dummy",
            "GROQ_API_KEY": "dummy",
            "OPENAI_API_KEY": "dummy",
        },
    )
    assert baseline == before
    assert result["jobs"][:6] == before["jobs"]
    envs = {entry["key"]: entry for entry in result["jobs"][-1]["envs"]}
    assert envs["OTEL_EXPORTER_OTLP_ENDPOINT"] == endpoint
    assert envs["OTEL_EXPORTER_OTLP_HEADERS"] == headers
    assert "DATA_GOV_API_KEY" not in envs
    assert "SOCRATA_APP_TOKEN" not in envs
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_spec_cli_never_prints_opaque_header(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _baseline()
    for job in baseline["jobs"]:
        job["envs"] += [
            {
                "key": "OTEL_EXPORTER_OTLP_ENDPOINT",
                "value": "https://collector.example.invalid/v1/traces",
            },
            {
                "key": "OTEL_EXPORTER_OTLP_HEADERS",
                "type": "SECRET",
                "scope": "RUN_TIME",
                "value": "DUMMY_OPAQUE_HEADER_SENTINEL",
            },
        ]
    source, output = tmp_path / "baseline.json", tmp_path / "output.json"
    source.write_text(json.dumps(baseline), encoding="utf-8")
    monkeypatch.setenv("NCBI_EMAIL", "operator@example.test")
    for key in ("NCBI_API_KEY", "NEO4J_RUNTIME_PASSWORD", "GROQ_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "spec",
            "--baseline",
            str(source),
            "--output",
            str(output),
            "--operation",
            "discover",
            "--image-digest",
            DIGEST,
        ],
    )
    run_path(str(Path(__file__).resolve().parents[1] / "scripts/prod_literature_job_spec.py"))[
        "main"
    ]()
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    envs = {entry["key"]: entry for entry in json.loads(output.read_text())["jobs"][-1]["envs"]}
    assert envs["OTEL_EXPORTER_OTLP_HEADERS"]["value"] == "DUMMY_OPAQUE_HEADER_SENTINEL"


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
        secrets={
            "NCBI_EMAIL": "operator@example.test",
            "NEO4J_RUNTIME_PASSWORD": "graph-secret",
            "GROQ_API_KEY": "groq-secret",
            "OPENAI_API_KEY": "openai-secret",
        },
    )
    assert "vpc" not in baseline
    assert preflight["vpc"]["id"] == "a937d8dd-4ee9-4de2-a8df-b32e7ad4098e"
    assert "literature-preflight --operation all" in preflight["jobs"][-1]["run_command"]


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


def test_host_secret_readiness_collects_every_stage_without_values() -> None:
    baseline = _baseline()
    for job in baseline["jobs"]:
        job["envs"] = [
            entry
            for entry in job["envs"]
            if entry["key"] not in {"SNOWFLAKE_PRIVATE_KEY_B64", "SPACES_ACCESS_KEY_ID"}
        ]
    before = deepcopy(baseline)
    result = secret_readiness(
        baseline,
        operation="preflight",
        secrets={"NCBI_API_KEY": "OPTIONAL_SECRET_SENTINEL"},
        workflow_run_id="12345",
    )
    assert result["status"] == "BLOCKED"
    assert result["run_id"] == "12345"
    assert result["scope"] == "host_secret_presence"
    assert result["runtime_readiness"] == "NOT_CHECKED"
    assert {(item["stage"], item["capability"]) for item in result["blockers"]} == {
        (stage, key)
        for stage in ("discover", "extract", "build-corpus")
        for key in ("SNOWFLAKE_PRIVATE_KEY_B64", "SPACES_ACCESS_KEY_ID")
    } | {
        ("discover", "NCBI_EMAIL"),
        ("extract", "NEO4J_RUNTIME_PASSWORD"),
        ("extract", "GROQ_API_KEY"),
        ("extract", "OPENAI_API_KEY"),
    }
    assert all(
        item["remediation_owner"] and item["next_action"] and item["retryable"] is False
        for item in result["blockers"]
    )
    assert "OPTIONAL_SECRET_SENTINEL" not in json.dumps(result)
    assert "encrypted" not in json.dumps(result)
    assert baseline == before


@pytest.mark.parametrize("credential_type", [None, "GENERAL", "SECRET"])
def test_empty_or_unprotected_inherited_credential_blocks(credential_type: str | None) -> None:
    baseline = _baseline()
    credential = next(
        entry for entry in baseline["jobs"][1]["envs"] if entry["key"] == "SPACES_ACCESS_KEY_ID"
    )
    credential.update(type=credential_type, value="" if credential_type == "SECRET" else "x")
    result = secret_readiness(baseline, operation="build-corpus", secrets={})
    assert [item["capability"] for item in result["blockers"]] == ["SPACES_ACCESS_KEY_ID"]


def test_ready_host_report_never_claims_runtime_or_optional_key_is_required() -> None:
    result = secret_readiness(
        _baseline(), operation="discover", secrets={"NCBI_EMAIL": "EMAIL_SENTINEL"}
    )
    assert result["status"] == "READY"
    assert result["runtime_readiness"] == "NOT_CHECKED"
    assert result["blockers"] == []
    assert result["optional_configuration"] == {"NCBI_API_KEY_present": False}
    assert "EMAIL_SENTINEL" not in json.dumps(result)


def test_cli_blocked_report_does_not_write_a_deployable_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline_path, output, report = (
        tmp_path / "baseline.json",
        tmp_path / "operation.json",
        tmp_path / "readiness.json",
    )
    baseline_path.write_text(json.dumps(_baseline()), encoding="utf-8")
    for key in ("NCBI_EMAIL", "NEO4J_RUNTIME_PASSWORD", "GROQ_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NCBI_API_KEY", "OPTIONAL_SECRET_SENTINEL")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "spec",
            "--baseline",
            str(baseline_path),
            "--output",
            str(output),
            "--operation",
            "preflight",
            "--image-digest",
            DIGEST,
            "--workflow-run-id",
            "12345",
            "--readiness-report",
            str(report),
        ],
    )
    with pytest.raises(SystemExit) as error:
        run_path(str(_SCRIPT))["main"]()
    result = json.loads(report.read_text())
    assert result["status"] == "BLOCKED"
    assert {item["capability"] for item in result["blockers"]} == {
        "NCBI_EMAIL",
        "NEO4J_RUNTIME_PASSWORD",
        "GROQ_API_KEY",
        "OPENAI_API_KEY",
    }
    assert not output.exists()
    assert "OPTIONAL_SECRET_SENTINEL" not in str(error.value)


def test_real_workflow_aggregate_drift_and_secrets_never_updates_or_restores_topology(
    tmp_path: Path,
) -> None:
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    if not bash or not Path(bash).exists():
        pytest.skip("workflow integration requires bash")
    workflow = yaml.safe_load(Path(".github/workflows/run-prod-literature-once.yml").read_text())
    body = workflow["jobs"]["run"]["steps"][-1]["run"]
    fixture, updates = tmp_path / "baseline.json", tmp_path / "updates"
    baseline = _baseline()
    baseline["region"] = "private-drift-sentinel"
    next(entry for entry in baseline["jobs"][0]["envs"] if entry["key"] == "SNOWFLAKE_ROLE")[
        "value"
    ] = "private-drift-sentinel"
    fixture.write_text(json.dumps(baseline), encoding="utf-8")
    # The actual deployed-image/topology reads use fixture-only doctl/jq functions.
    # Every App update (including restoration) is a failing, recorded sentinel.
    harness = (
        r"""
doctl() {
  if [ "$1 $2" = "apps update" ]; then
    echo UPDATE >> "$UPDATE_SENTINEL"
    return 99
  fi
  if [ "$1 $2 $3" = "apps spec get" ]; then cat "$BASELINE_FIXTURE"; else echo '{}'; fi
}
jq() {
  if [ "$#" -ne 3 ]; then cat >/dev/null; fi
  case "$*" in
    *phase*) echo ACTIVE ;;
    *active_deployment*) echo deployment ;;
    *length*) echo 1 ;;
    *) echo "$IMAGE_DIGEST" ;;
  esac
}
python() { "$PYTHON_EXECUTABLE" "$@"; }
"""
        + body
    )
    env = os.environ.copy()
    env.update(
        GITHUB_REF="refs/heads/main",
        GITHUB_SHA="a" * 40,
        GITHUB_RUN_ID="12345",
        PROD_APP_ID="fixture-prod",
        DEV_APP_ID="fixture-dev",
        IMAGE_DIGEST=DIGEST,
        MAX_RECORDS="25",
        BATCH_SIZE="25",
        ESTIMATED_COST_USD="0.20",
        DISCOVERY_RUN_ID="",
        LITERATURE_OPERATION="preflight",
        LITERATURE_FAMILY="surveillance_epidemiology",
        BASELINE_FIXTURE=fixture.as_posix(),
        UPDATE_SENTINEL=updates.as_posix(),
        PYTHON_EXECUTABLE=Path(sys.executable).as_posix(),
    )
    for key in (
        "NCBI_EMAIL",
        "NCBI_API_KEY",
        "NEO4J_RUNTIME_PASSWORD",
        "GROQ_API_KEY",
        "OPENAI_API_KEY",
    ):
        env.pop(key, None)
    result = subprocess.run(
        [bash, "-c", harness], env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode != 0
    assert '"status": "BLOCKED"' in result.stdout
    for key in ("NCBI_EMAIL", "NEO4J_RUNTIME_PASSWORD", "GROQ_API_KEY", "OPENAI_API_KEY"):
        assert key in result.stdout
    assert "reviewed_production_region" in result.stdout
    assert "SNOWFLAKE_ROLE" in result.stdout
    assert "host_baseline_configuration" in result.stdout
    assert not updates.exists()
    assert "encrypted" not in result.stdout + result.stderr
    assert "private-drift-sentinel" not in result.stdout + result.stderr
