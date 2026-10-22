"""Enforce the checked-in workflow's migration-only authorization boundary."""

from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).parents[1] / ".github/workflows/promote-prod.yml"


def image_update_steps():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return [
        step
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if "doctl apps update" in step.get("run", "")
    ]


@pytest.mark.parametrize(
    "intelligence,integrity,allowed",
    [(False, False, True), (True, False, False), (False, True, False), (True, True, False)],
)
@pytest.mark.parametrize("daily", [False, True])
@pytest.mark.parametrize("validation", [False, True])
def test_actual_image_update_condition_excludes_each_migration_only_mode(
    intelligence, integrity, allowed, daily, validation
):
    steps = image_update_steps()
    assert len(steps) == 1
    expression = steps[0]["if"].removeprefix("${{").removesuffix("}}").strip()
    # Evaluate only the two boolean comparisons used by this checked-in boundary.
    clauses = expression.split(" && ")
    inputs = {
        "inputs.intelligence_daily_only": daily,
        "inputs.intelligence_daily_validate_only": validation,
        "inputs.protected_intelligence_prerequisite": intelligence,
        "inputs.release_integrity_only": integrity,
    }
    results = []
    for clause in clauses:
        name, operator, value = clause.strip("()").split()
        assert name in inputs and operator == "!=" and value == "true"
        results.append(inputs[name] is not True)
    assert all(results) is (allowed and not daily and not validation)


def test_migration_path_keeps_exact_pending_set_and_protected_environment():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    job = workflow["jobs"]["promote"]
    assert job["environment"] == "production"
    assert workflow["concurrency"] == {"group": "prod-app-topology", "cancel-in-progress": False}
    migration = next(
        step
        for step in job["steps"]
        if step.get("name") == "Apply checksum-validated PROD migrations before image promotion"
    )
    assert "protected_intelligence_prerequisite" not in migration["if"]
    assert '--expected-pending-json "$EXPECTED_PENDING_JSON"' in migration["run"]
    assert "--protected-intelligence-prerequisite --confirm" in migration["run"]
    assert (
        migration["env"]["PROTECTED_INTELLIGENCE_PREREQUISITE"]
        == "${{ inputs.protected_intelligence_prerequisite }}"
    )
