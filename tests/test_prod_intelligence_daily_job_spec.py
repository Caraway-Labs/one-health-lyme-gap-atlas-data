"""Regression coverage for one-shot PROD intelligence-daily topology."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from runpy import run_path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
_MODULE = run_path(str(ROOT / "scripts" / "prod_intelligence_daily_job_spec.py"))
build_operation_spec = _MODULE["build_operation_spec"]
COMMAND = _MODULE["COMMAND"]
DIGEST = "sha256:" + "a" * 64


def test_pubmed_failed_class_name_is_reported() -> None:
    prefix = _MODULE["OUTCOME_LOG_PREFIX"]
    text = "\n".join(
        (
            prefix
            + '{"error_class":"TimeoutError","source_id":"pubmed-tick-borne","status":"FAILED"}',
            prefix + '{"source_id":"cdc-mmwr","status":"FAILED"}',
            prefix
            + '{"error_class":"not a class","source_id":"pubmed-lyme-borrelia","status":"FAILED"}',
        )
    )
    rows = {row["source"]: row["error_code"] for row in _MODULE["parse_daily_outcomes"](text)}
    assert rows["pubmed-tick-borne"] == "TimeoutError"
    assert rows["cdc-mmwr"] == "UNCLASSIFIED_EXCEPTION"
    assert rows["pubmed-lyme-borrelia"] == "UNCLASSIFIED_EXCEPTION"


def test_pubmed_outcome_prefers_the_redacted_error_code() -> None:
    prefix = _MODULE["OUTCOME_LOG_PREFIX"]
    text = (
        prefix + '{"error_class":"AcquisitionError","error_code":"FEED_HTTP_403",'
        '"http_status":403,"source_id":"pubmed-tick-borne","status":"FAILED"}'
    )
    rows = {row["source"]: row["error_code"] for row in _MODULE["parse_daily_outcomes"](text)}
    assert rows["pubmed-tick-borne"] == "FEED_HTTP_403"


def _baseline() -> dict:
    base_jobs = [
        {"name": n, "kind": "SCHEDULED", "image": {"digest": DIGEST}, "run_command": "x"}
        for n in sorted(
            {
                "catalog-discovery",
                "approved-source-ingestion",
                "cdc-operations-watchdog",
                "catalog-registration-01",
                "catalog-registration-02",
                "catalog-registration-03",
            }
        )
    ]
    base_jobs.append(
        {
            "name": "intelligence-feed-daily",
            "kind": "SCHEDULED",
            "image": {"digest": DIGEST},
            "run_command": COMMAND,
            "schedule": {"cron": "15 18 * * *", "time_zone": "America/Denver"},
        }
    )
    return {"jobs": base_jobs}


def test_manual_and_scheduled_jobs_copy_sibling_otel_settings() -> None:
    baseline = _baseline()
    sentinel = "DUMMY_OPAQUE_HEADER_SENTINEL"
    endpoint = "https://otel.example.invalid/v1/traces"
    registration = next(job for job in baseline["jobs"] if job["name"] == "catalog-registration-01")
    registration["envs"] = [
        {"key": "OTEL_EXPORTER_OTLP_ENDPOINT", "scope": "RUN_TIME", "value": endpoint},
        {
            "key": "OTEL_EXPORTER_OTLP_HEADERS",
            "scope": "RUN_TIME",
            "type": "SECRET",
            "value": sentinel,
        },
    ]
    spec = build_operation_spec(baseline, preflight_only=False)
    for name in ("intelligence-feed-daily", _MODULE["MANUAL_JOB"]):
        job = next(item for item in spec["jobs"] if item["name"] == name)
        envs = {entry["key"]: entry for entry in job["envs"]}
        assert envs["OTEL_EXPORTER_OTLP_ENDPOINT"]["value"] == endpoint
        assert envs["OTEL_EXPORTER_OTLP_HEADERS"]["value"] == sentinel
        assert envs["OTEL_EXPORTER_OTLP_HEADERS"]["type"] == "SECRET"


def test_builds_manual_predeploy_from_daily_template() -> None:
    baseline = _baseline()
    spec = build_operation_spec(baseline, preflight_only=False)
    names = {job["name"] for job in spec["jobs"]}
    assert names == {_MODULE["MANUAL_JOB"], *_MODULE["EXPECTED_JOBS"]}
    manual = next(job for job in spec["jobs"] if job["name"] == _MODULE["MANUAL_JOB"])
    assert manual["kind"] == "PRE_DEPLOY"
    assert manual["run_command"] == COMMAND
    assert "schedule" not in manual


def test_preflight_appends_flag() -> None:
    spec = build_operation_spec(_baseline(), preflight_only=True)
    manual = next(job for job in spec["jobs"] if job["name"] == _MODULE["MANUAL_JOB"])
    assert manual["run_command"] == COMMAND + " --preflight-only"


def test_rejects_competing_predeploy() -> None:
    baseline = _baseline()
    baseline["jobs"][0]["kind"] = "PRE_DEPLOY"
    with pytest.raises(PermissionError, match="COMPETING_PREDEPLOY"):
        build_operation_spec(baseline, preflight_only=False)


def test_reopen_attempt_appends_flag_and_env() -> None:
    spec = build_operation_spec(
        _baseline(),
        preflight_only=False,
        reopen_attempt=2,
        source_ids=("cdc-mmwr",),
    )
    manual = next(job for job in spec["jobs"] if job["name"] == _MODULE["MANUAL_JOB"])
    assert manual["run_command"] == COMMAND + " --reopen-attempt 2 --source cdc-mmwr"
    assert any(
        entry.get("key") == "INTELLIGENCE_DAILY_REOPEN" and entry.get("value") == "true"
        for entry in manual.get("envs", [])
    )


def test_default_manual_spec_never_sets_reopen_env_or_flag() -> None:
    spec = build_operation_spec(_baseline(), preflight_only=False)
    for job in spec["jobs"]:
        assert "--reopen-attempt" not in job["run_command"]
        assert not any(e.get("key") == "INTELLIGENCE_DAILY_REOPEN" for e in job.get("envs", []))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"preflight_only": True, "reopen_attempt": 2},
        {"preflight_only": False, "reopen_attempt": 2, "recover_ingestion_run_id": "x"},
        {"preflight_only": False, "reopen_attempt": 0},
        {"preflight_only": False, "reopen_attempt": 32},
    ],
)
def test_reopen_is_exclusive_and_bounded(kwargs) -> None:
    with pytest.raises(PermissionError, match="REOPEN|RECOVERY"):
        build_operation_spec(_baseline(), **kwargs)


def test_reopen_leaves_scheduled_daily_job_untouched() -> None:
    baseline = _baseline()
    spec = build_operation_spec(
        baseline,
        preflight_only=False,
        reopen_attempt=2,
        source_ids=("cdc-mmwr",),
    )
    scheduled = next(j for j in spec["jobs"] if j["name"] == "intelligence-feed-daily")
    assert scheduled == next(j for j in baseline["jobs"] if j["name"] == "intelligence-feed-daily")


def test_reopen_without_source_or_with_all_is_rejected() -> None:
    with pytest.raises(PermissionError, match="REOPEN_SOURCE_REQUIRED"):
        build_operation_spec(_baseline(), preflight_only=False, reopen_attempt=2)
    with pytest.raises(PermissionError, match="SOURCE_SELECTION_INVALID"):
        build_operation_spec(
            _baseline(),
            preflight_only=False,
            reopen_attempt=2,
            source_ids=("all",),
        )
    with pytest.raises(PermissionError, match="SOURCE_SELECTION_INVALID"):
        build_operation_spec(
            _baseline(),
            preflight_only=False,
            reopen_attempt=2,
            source_ids=("cdc-mmwr",) * 6,
        )


def test_recover_command_requires_the_matching_source() -> None:
    run_id = "76e241c4-815f-5c27-b97f-882be9c53903"
    with pytest.raises(PermissionError, match="RECOVERY_SOURCE_REQUIRED"):
        build_operation_spec(
            _baseline(),
            preflight_only=False,
            recover_ingestion_run_id=run_id,
        )
    spec = build_operation_spec(
        _baseline(),
        preflight_only=False,
        recover_ingestion_run_id=run_id,
        source_ids=("cdc-mmwr",),
    )
    manual = next(job for job in spec["jobs"] if job["name"] == _MODULE["MANUAL_JOB"])
    assert manual["run_command"].endswith(f"{run_id} --source cdc-mmwr")


def test_cli_writes_json(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    output_path = tmp_path / "out.json"
    baseline_path.write_text(json.dumps(_baseline()), encoding="utf-8")
    import subprocess
    import sys

    script = ROOT / "scripts" / "prod_intelligence_daily_job_spec.py"
    subprocess.run(
        [
            sys.executable,
            str(script),
            "--baseline",
            str(baseline_path),
            "--output",
            str(output_path),
        ],
        check=True,
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert any(job.get("name") == _MODULE["MANUAL_JOB"] for job in payload["jobs"])
