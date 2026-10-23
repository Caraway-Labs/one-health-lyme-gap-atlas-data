"""Offline proof that protected production validation cannot update an app."""

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "daily_prod_validation", ROOT / "scripts/validate_intelligence_daily_prod.py"
)
m = importlib.util.module_from_spec(spec)
with patch.object(sys, "path", [str(ROOT / "scripts"), *sys.path]):
    spec.loader.exec_module(m)
PRIVATE = "private-configuration-canary"


def app():
    jobs = []
    for name, (command, cron) in m.PUBLIC_JOBS.items():
        jobs.append(
            {
                "name": name,
                "kind": "SCHEDULED",
                "image": m.image(m.OLD),
                "run_command": command,
                "schedule": {"cron": cron, "time_zone": "America/Denver"},
                "instance_count": 1,
                "instance_size_slug": "apps-s-1vcpu-0.5gb",
                "envs": [
                    {"key": "API_KEY", "value": PRIVATE},
                    {"key": "OTHER", "value": "EV[opaque-reference-canary]"},
                ],
            }
        )
    return {
        "spec": {
            "name": "oh-lyme-data-prod",
            "region": "nyc",
            "features": ["buildpack-stack=ubuntu-22"],
            "ingress": {"rules": []},
            "jobs": jobs,
        },
        "active_deployment": {"id": "active"},
    }


def install_reads(monkeypatch, before, after=None):
    responses = [
        before,
        {"phase": "ACTIVE", "spec": copy.deepcopy(before["spec"])},
        {"spec": {"jobs": [{"image": m.image(m.NEW)}]}},
        after or copy.deepcopy(before),
    ]
    calls = []

    def get(args):
        calls.append(args)
        return responses.pop(0)

    monkeypatch.setattr(m.daily, "get", get)
    return calls


def test_only_two_existing_app_proposals_and_no_private_configuration(monkeypatch):
    before = app()
    snapshot = copy.deepcopy(before)
    reads = install_reads(monkeypatch, before)
    requests = []

    def run(args, **kwargs):
        assert args[:5] == ["doctl", "--api-url", m.API, "apps", "propose"]
        assert args[args.index("--app") + 1] == m.daily.APP_ID
        assert args[-2:] == ["--http-retry-max", "0"]
        assert kwargs["timeout"] == 90
        payload = json.loads(kwargs["input"])
        assert all(
            x not in kwargs["input"]
            for x in [PRIVATE, "EV[", "envs", "credentials", "SNOWFLAKE", "SPACES_"]
        )
        requests.append(payload)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"spec": payload}), stderr="")

    monkeypatch.setattr(m.subprocess, "run", run)
    result = m.run_validation(m.NEW)
    assert len(requests) == 2 and len(reads) == 4
    assert before == snapshot and result["app_unchanged"] and result["provider_updates"] == 0
    assert all(x["accepted"] and x["normalized_image_refs_match"] for x in result["proposals"])
    assert [p["jobs"][-1]["image"]["digest"] for p in requests] == [m.OLD, m.NEW]
    assert all(
        p["jobs"][-1]["run_command"] == m.daily.COMMAND + " --preflight-only" for p in requests
    )
    assert all(
        len(p["jobs"]) == 7 and p["features"] == snapshot["spec"]["features"] for p in requests
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("image", {"tag": "latest"}),
        ("run_command", PRIVATE),
        ("kind", "PRE_DEPLOY"),
        ("instance_count", 2),
        ("instance_size_slug", PRIVATE),
        ("schedule", {"cron": PRIVATE}),
        ("github", {"repo": "owner/repo"}),
    ],
)
def test_job_drift_stops_before_any_proposal(monkeypatch, field, value):
    before = app()
    before["spec"]["jobs"][0][field] = value
    monkeypatch.setattr(m.daily, "get", lambda args: before)
    monkeypatch.setattr(
        m.subprocess, "run", lambda *a, **k: pytest.fail("unexpected external request")
    )
    with pytest.raises(PermissionError):
        m.run_validation(m.NEW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("envs", [{"value": PRIVATE}]),
        ("features", [PRIVATE]),
        ("ingress", {"rules": [{"value": PRIVATE}]}),
        ("services", []),
    ],
)
def test_unknown_or_private_root_structure_stops_before_proposal(field, value):
    before = app()
    before["spec"][field] = value
    with pytest.raises(PermissionError):
        m.public_spec(before, m.NEW)


def test_rejected_proposals_redact_auth_token_and_do_not_retry(monkeypatch):
    monkeypatch.setenv("DIGITALOCEAN_ACCESS_TOKEN", PRIVATE)
    install_reads(monkeypatch, app())
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps({"errors": [{"detail": "invalid value " + PRIVATE}]}),
            stderr="",
        )

    monkeypatch.setattr(m.subprocess, "run", run)
    result = m.run_validation(m.NEW)
    assert len(calls) == 2 and not any(x["accepted"] for x in result["proposals"])
    assert PRIVATE not in json.dumps(result)


def test_normalized_response_canary_is_not_logged(monkeypatch):
    install_reads(monkeypatch, app())
    monkeypatch.setattr(
        m.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {"spec": {"jobs": [{"name": PRIVATE, "image": {"digest": PRIVATE}}]}}
            ),
            stderr="",
        ),
    )
    result = m.run_validation(m.NEW)
    assert PRIVATE not in json.dumps(result)
    assert not any(x["normalized_image_refs_match"] for x in result["proposals"])


def test_postcheck_detects_external_drift_without_fixing_it(monkeypatch):
    before = app()
    after = copy.deepcopy(before)
    after["active_deployment"]["id"] = "changed"
    install_reads(monkeypatch, before, after)
    monkeypatch.setattr(
        m.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="{}", stderr="")
    )
    with pytest.raises(PermissionError, match="POSTCHECK_DRIFT"):
        m.run_validation(m.NEW)


def test_validation_mode_keeps_native_gate_and_excludes_every_mutation_job():
    workflow = yaml.safe_load((ROOT / ".github/workflows/promote-prod.yml").read_text())
    job = workflow["jobs"]["intelligence-daily"]
    assert job["environment"] == "production"
    assert set(job["env"]) == {
        "DIGITALOCEAN_ACCESS_TOKEN",
        "IMAGE_DIGEST",
        "REVIEWED_COMMIT",
        "GH_TOKEN",
    }
    for name, node in workflow["jobs"].items():
        if name != "intelligence-daily":
            assert "inputs.intelligence_daily_validate_only != true" in node["if"]
    for step in job["steps"]:
        if "--phase refresh-digest" in step.get("run", ""):
            assert (
                step["if"]
                == "inputs.intelligence_daily_validate_only != true && steps.intelligence_daily_prod_state.outputs.active == 'true'"
            )
        if "--phase preflight" in step.get("run", "") or "--phase activate" in step.get("run", ""):
            assert (
                step["if"]
                == "inputs.intelligence_daily_validate_only != true && steps.intelligence_daily_prod_state.outputs.active != 'true'"
            )
    checks = next(
        s["run"] for s in job["steps"] if s.get("name", "").startswith("Require isolated")
    )
    code = checks.split("python - <<'PY'\n", 1)[1].split("\nPY", 1)[0]
    for validation, placement, allowed in [
        (True, False, True),
        (False, True, True),
        (True, True, False),
        (False, False, False),
    ]:
        request = {
            "intelligence_daily_only": True,
            "intelligence_daily_validate_only": validation,
            "daily_credential_placement_approved": placement,
        }
        import os

        with patch.dict(os.environ, {"REQUEST": json.dumps(request)}):
            if allowed:
                exec(code, {})
            else:
                with pytest.raises(AssertionError):
                    exec(code, {})
