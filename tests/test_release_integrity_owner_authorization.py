"""Native sole-owner approval is fresh and bound to one exact fixture execution."""

import copy
import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


@pytest.fixture
def gate():
    spec = importlib.util.spec_from_file_location(
        "owner_gate", ROOT / "scripts/review_release_integrity_fixture_gate.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def evidence(gate):
    run = {
        "head_sha": "a" * 40,
        "event": "workflow_dispatch",
        "id": 123,
        "run_attempt": 1,
        "created_at": "2026-10-18T00:00:00Z",
        "updated_at": "2026-10-18T00:40:00Z",
        "repository": {"full_name": gate.REPOSITORY},
        "path": ".github/workflows/deploy-dev.yml",
    }
    artifacts = [{"version": "V157", "sha": "original-and-rendered"}, {"version": "V158"}]
    binding = gate.execution_binding(run["head_sha"], run, artifacts)
    environment = {
        "name": gate.ENVIRONMENT,
        "id": 42,
        "can_admins_bypass": False,
        "protection_rules": [
            {
                "type": "required_reviewers",
                "prevent_self_review": False,
                "reviewers": [{"type": "User", "reviewer": gate.OWNER.copy()}],
            }
        ],
    }
    approvals = [
        {
            "state": "approved",
            "comment": gate.authorization_comment(binding),
            "user": gate.OWNER.copy(),
            "environments": [{"id": 42, "name": gate.ENVIRONMENT}],
        }
    ]
    return run, artifacts, binding, environment, approvals, gate.timestamp("2026-10-18T00:05:00Z")


def test_native_owner_authorization_preserves_identity_and_complete_binding(gate):
    run, artifacts, binding, environment, approvals, now = evidence(gate)
    auth = gate.validate_owner_authorization(binding, environment, approvals, now)
    assert auth["owner"]["login"] == "CarawayLabs"
    assert "human_reviews" not in auth
    review = {"reviewed_commit": run["head_sha"], "owner_authorization": auth}
    gate.validate_retained_authorization(review, run, artifacts, environment, approvals)
    auth["binding"]["run_attempt"] = 2
    with pytest.raises(ValueError):
        gate.validate_retained_authorization(review, run, artifacts, environment, approvals)


@pytest.mark.parametrize(
    "bad",
    [
        "missing",
        "actor",
        "bot",
        "id",
        "comment",
        "rejected",
        "env_id",
        "bypass",
        "reviewer",
        "self_review",
        "commit",
        "scope",
        "artifact",
        "attempt",
        "expired",
        "future",
    ],
)
def test_changed_expired_or_untrusted_authorization_fails_closed(gate, bad):
    _, _, binding, environment, approvals, now = copy.deepcopy(evidence(gate))
    if bad == "missing":
        approvals.clear()
    elif bad in {"actor", "bot", "id"}:
        key, value = {"actor": ("login", "other"), "bot": ("type", "Bot"), "id": ("id", 99)}[bad]
        approvals[0]["user"][key] = value
    elif bad == "comment":
        approvals[0]["comment"] = "owner approved in an agent-generated comment"
    elif bad == "rejected":
        approvals[0]["state"] = "rejected"
    elif bad == "env_id":
        approvals[0]["environments"][0]["id"] = 99
    elif bad == "bypass":
        environment["can_admins_bypass"] = True
    elif bad == "reviewer":
        environment["protection_rules"][0]["reviewers"][0]["reviewer"]["login"] = "other"
    elif bad == "self_review":
        environment["protection_rules"][0]["prevent_self_review"] = True
    elif bad == "commit":
        binding["commit"] = "b" * 40
    elif bad == "scope":
        binding["scope"] = "PROD"
    elif bad == "artifact":
        binding["artifacts"][0]["sha"] = "changed"
    elif bad == "attempt":
        binding["run_attempt"] = 2
    elif bad == "expired":
        now = gate.timestamp("2026-10-18T02:00:00Z")
    else:
        now = gate.timestamp("2026-10-17T23:59:59Z")
    with pytest.raises(ValueError):
        gate.validate_owner_authorization(binding, environment, approvals, now)


def test_workflow_cannot_submit_approval_or_obtain_credentials_before_owner_gate():
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-dev.yml").read_text())
    jobs = workflow["jobs"]
    assert jobs["release-integrity-owner-authorization"]["environment"] == "ri706-dev-fixture"
    assert jobs["release-integrity-owner-authorization"]["needs"] == "release-integrity-prepare"
    assert jobs["release-integrity-fixture"]["needs"] == "release-integrity-owner-authorization"
    assert jobs["release-integrity-fixture"]["environment"] == "dev"
    for name in (
        "release-integrity-prepare",
        "release-integrity-owner-authorization",
        "release-integrity-fixture",
    ):
        assert set(jobs[name]["permissions"].values()) == {"read"}
        if name != "release-integrity-fixture":
            assert "secrets." not in str(jobs[name])
    source = (ROOT / "scripts/review_release_integrity_fixture_gate.py").read_text()
    assert '"POST"' not in source
    assert "pending_deployments" not in source
