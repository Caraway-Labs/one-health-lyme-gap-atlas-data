"""Execute the checked-in EID dispatch guard without credentials or services."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(".github/workflows/run-prod-ingestion.yml")


def guard_result(overrides):
    candidate = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    if not candidate or not Path(candidate).is_file():
        pytest.skip("bash required for actual workflow guard execution")
    workflow = yaml.safe_load(WORKFLOW.read_text())
    step = next(
        item
        for item in workflow["jobs"]["ingest"]["steps"]
        if item.get("name") == "Require exact reviewed EID-only production request"
    )
    env = (
        dict(os.environ)
        | {
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": "a" * 40,
            "GITHUB_REPOSITORY": "fixture/repository",
            "REQUEST_OPERATION": "run",
            "REQUEST_RUN_ID": "",
            "REQUEST_SOURCE_VERSION_ID": "",
            "REQUEST_SOURCE_DECISION_ID": "",
            "TEST_CHECKS": "1",
        }
        | overrides
    )
    return subprocess.run(
        [
            candidate,
            "--noprofile",
            "--norc",
            "-e",
            "-o",
            "pipefail",
            "-c",
            'gh() { printf "%s" "$TEST_CHECKS"; };\n' + step["run"],
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    ).returncode


def test_only_bounded_new_eid_request_passes():
    assert guard_result({}) == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"GITHUB_REF": "refs/heads/unreviewed"},
        {"REQUEST_OPERATION": "resume"},
        {"REQUEST_RUN_ID": "retained-run"},
        {"REQUEST_SOURCE_VERSION_ID": "other-source"},
        {"REQUEST_SOURCE_DECISION_ID": "other-decision"},
        {"TEST_CHECKS": "0"},
    ],
)
def test_eid_guard_rejects_widened_request_or_missing_exact_sha_check(overrides):
    assert guard_result(overrides) != 0


def test_shared_production_boundaries_remain_present():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    assert workflow["permissions"] == {"contents": "read", "checks": "read", "actions": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    job = workflow["jobs"]["ingest"]
    assert job["environment"] == "production"
    steps = {step["name"]: step for step in job["steps"] if "name" in step}
    generic = steps["Verify protected PROD runtime identity and approved source decision"]
    assert (
        generic["if"]
        == "inputs.source_definition != 'config/sources/intelligence_cdc_eid_expedited.yml'"
    )
    assert 'uuid.UUID(os.environ["SOURCE_VERSION_ID"])' in generic["run"]
    assert 'uuid.UUID(os.environ["SOURCE_DECISION_ID"])' in generic["run"]
    assert "approval[2] != source_decision_id" in generic["run"]
    assert "approval[3] is not None" in generic["run"]
    assert steps["Verify exact reviewed V153 deployment receipt"]["timeout-minutes"] == 4
    assert "MAX_CON_RETRY_ATTEMPTS=0" in steps["Set reviewed January connection limits"]["run"]
    execution = steps["Execute canonical Tier C run or resume"]
    for route in ("&& 31", "&& 301", "&& 6", "&& 5", "|| 360"):
        assert route in execution["timeout-minutes"]
    assert "timeout --signal=INT --kill-after=15s 1800s" in execution["run"]
    assert "timeout --signal=INT --kill-after=15s 18000s" in execution["run"]
