"""Early expected_pending_json failures explain quote stripping before migration guards."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
VALIDATOR = ROOT / "scripts" / "validate_expected_pending_json.sh"
SHA = "a" * 64
VALID_OBJECT = '[{"version":"V155","filename":"V155__county_context.sql","sha256":"' + SHA + '"}]'
DISPATCH_HINT = (
    "gh api repos/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/workflows/"
    "<file>/dispatches --input payload.json"
)


def _run(raw: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["EXPECTED_PENDING_JSON"] = raw
    return subprocess.run(
        ["bash", str(VALIDATOR)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _assert_rejected(raw: str) -> subprocess.CompletedProcess[str]:
    result = _run(raw)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "expected: " in result.stderr
    assert f"received: {raw}" in result.stderr
    assert "quoting probably stripped the quotes" in result.stderr
    assert DISPATCH_HINT in result.stderr
    return result


def test_valid_string_array_is_compacted() -> None:
    result = _run('[ "V155" , "V157" ]')
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == '["V155","V157"]\n'


def test_valid_migration_object_array_keeps_field_order() -> None:
    spaced = (
        "[\n"
        '  {"version": "V155", "filename": "V155__county_context.sql", "sha256": "' + SHA + '"}\n]'
    )
    result = _run(spaced)
    assert result.returncode == 0
    assert result.stdout == VALID_OBJECT + "\n"


def test_empty_array_is_allowed() -> None:
    result = _run("[]")
    assert result.returncode == 0
    assert result.stdout == "[]\n"


def test_quote_stripped_value_explains_expected_and_received() -> None:
    _assert_rejected("[V155,V157]")


def test_quote_stripped_migration_object_is_rejected() -> None:
    stripped = (
        "[{version:V166,filename:V166__prod_nih_news_daily_activation_view.sql,"
        "sha256:6ebe428121436db840a357506003d654df82a159f02737d9ab10c52d7f41500c}]"
    )
    _assert_rejected(stripped)


def test_non_array_value_is_rejected() -> None:
    _assert_rejected('{"version":"V155"}')


def test_empty_string_is_rejected() -> None:
    result = _assert_rejected("")
    assert "received: \n" in result.stderr


def test_workflows_validate_pending_json_immediately_after_checkout() -> None:
    jobs_by_workflow = {
        "promote-prod.yml": (
            "promote",
            "january-climate",
            "retained-lineage",
            "approve-intelligence-cleanup",
        ),
        "deploy-dev.yml": ("deploy",),
        "register-prod-eid.yml": ("register",),
    }
    for filename, job_names in jobs_by_workflow.items():
        document = yaml.safe_load((ROOT / ".github" / "workflows" / filename).read_text())
        for job_name in job_names:
            steps = document["jobs"][job_name]["steps"]
            checkout = next(
                index
                for index, step in enumerate(steps)
                if str(step.get("uses", "")).startswith("actions/checkout@")
            )
            step = steps[checkout + 1]
            assert step["id"] == "expected_pending"
            assert "scripts/validate_expected_pending_json.sh" in step["run"]
            assert step["env"]["EXPECTED_PENDING_JSON"] == "${{ inputs.expected_pending_json }}"
