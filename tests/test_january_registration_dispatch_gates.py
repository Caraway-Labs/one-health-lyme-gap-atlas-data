"""Execute actual dispatch guards with stubbed Git/GitHub; no service access."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(".github/workflows/run-ingestion.yml")
SHA = "a" * 40


def bash():
    candidate = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    if not candidate or not Path(candidate).is_file():
        pytest.skip("bash is required for executable workflow guard checks")
    return candidate


def execute_guard(name, overrides=None, inputs=None):
    workflow = yaml.safe_load(WORKFLOW.read_text())
    step = next(step for step in workflow["jobs"]["ingest"]["steps"] if step.get("name") == name)
    script = step["run"]
    for key, value in (inputs or {}).items():
        script = script.replace("${{ inputs." + key + " }}", value)
    env = (
        dict(os.environ)
        | {
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": SHA,
            "REVIEWED_COMMIT": SHA,
            "PHASE": "inspect",
            "TEST_HEAD": SHA,
            "TEST_CHECKS": "1",
            "GITHUB_REPOSITORY": "fixture/repository",
            "SOURCE_DEFINITION": "config/sources/noaa_nclimgrid_daily_202501.yml",
            "MEASUREMENT_RUN_ID": "c2eb2146-005d-44d2-bac4-e2805ca42577",
        }
        | (overrides or {})
    )
    stubs = 'git() { printf "%s" "$TEST_HEAD"; }; gh() { printf "%s" "$TEST_CHECKS"; };\n'
    return subprocess.run(
        [bash(), "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", stubs + script],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    ).returncode


@pytest.mark.parametrize(
    "overrides",
    [
        {"GITHUB_REF": "refs/heads/unreviewed"},
        {"REVIEWED_COMMIT": "not-a-sha"},
        {"REVIEWED_COMMIT": "A" * 40},
        {"GITHUB_SHA": "b" * 40},
        {"TEST_HEAD": "b" * 40},
        {"PHASE": "record-steward"},
        {"PHASE": "publish"},
        {"TEST_CHECKS": "0"},
    ],
)
def test_reviewed_commit_guard_rejects_unreviewed_scope(overrides):
    assert execute_guard("Verify reviewed main for January registration", overrides) != 0


@pytest.mark.parametrize("phase", ["inspect", "register-pending"])
def test_only_two_reviewed_registration_phases_pass(phase):
    assert execute_guard("Verify reviewed main for January registration", {"PHASE": phase}) == 0


INPUTS = {
    "operation": "january-source-registration",
    "tier": "B",
    "environment_name": "dev",
    "recapture": "false",
    "publish": "false",
    "measurement_action": "preflight",
}


@pytest.mark.parametrize(
    ("input_changes", "env_changes"),
    [
        ({"environment_name": "production"}, {}),
        ({"tier": "C"}, {}),
        ({"tier": "A"}, {}),
        ({"recapture": "true"}, {}),
        ({"publish": "true"}, {}),
        ({}, {"SOURCE_DEFINITION": "config/sources/other_month.yml"}),
        ({}, {"MEASUREMENT_RUN_ID": "other-run"}),
        ({}, {"MEASUREMENT_RUN_ID": ""}),
    ],
)
def test_environment_guard_rejects_unapproved_period_action_or_target(input_changes, env_changes):
    assert execute_guard(
        "Enforce environment and tier boundary", env_changes, INPUTS | input_changes
    )


def test_exact_retained_dev_scope_passes_environment_guard():
    assert execute_guard("Enforce environment and tier boundary", inputs=INPUTS) == 0
