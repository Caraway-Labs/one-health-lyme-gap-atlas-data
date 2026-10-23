"""Regression coverage for one-shot PROD intelligence-daily topology."""

from __future__ import annotations

import json
from pathlib import Path
from runpy import run_path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
_MODULE = run_path(str(ROOT / "scripts" / "prod_intelligence_daily_job_spec.py"))
build_operation_spec = _MODULE["build_operation_spec"]
COMMAND = _MODULE["COMMAND"]
DIGEST = "sha256:" + "a" * 64


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
            "schedule": {"cron": "0 7 * * *", "time_zone": "America/Denver"},
        }
    )
    return {"jobs": base_jobs}


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


def test_cli_writes_json(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    output_path = tmp_path / "out.json"
    baseline_path.write_text(json.dumps(_baseline()), encoding="utf-8")
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "scripts" / "prod_intelligence_daily_job_spec.py"),
            "--baseline",
            str(baseline_path),
            "--output",
            str(output_path),
        ],
        check=True,
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert any(job.get("name") == _MODULE["MANUAL_JOB"] for job in payload["jobs"])
