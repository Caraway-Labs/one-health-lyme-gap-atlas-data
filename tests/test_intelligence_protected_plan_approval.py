"""Approval-only workflow uses existing protected credentials and exact inventory."""

import ast
import importlib
import itertools
import json
import os
import re
import subprocess
import sys
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from lyme_gap_atlas_data.intelligence_retention import RawCopy, capture_lease

ROOT = Path(__file__).parents[1]
# Mirror the workflow's `python -m scripts...` root without relying on the
# pytest console entry point adding the repository to its import path.
sys.path.insert(0, str(ROOT))
try:
    module = importlib.import_module("scripts.approve_intelligence_raw_cleanup_prod")
    canonical = importlib.import_module("scripts.intelligence_raw_cleanup_prod")
finally:
    sys.path.remove(str(ROOT))
DATABASE, SYNTHETIC_RUN, SYNTHETIC_SHA = (
    canonical.DATABASE,
    canonical.SYNTHETIC_RUN,
    canonical.SYNTHETIC_SHA,
)
synthetic_plan = canonical.synthetic_plan


def request():
    inputs = {
        "approve_intelligence_cleanup_only": True,
        "reviewed_commit": "a" * 40,
        "cleanup_plan_sha256": "b" * 64,
        "cleanup_planned_at": "2026-09-30T23:59:59Z",
        "cleanup_approval_ref": "DATA-680-reviewed-plan",
        "image_digest": module.MODE,
        "expected_pending_json": "[]",
    }
    environment = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "Caraway-Labs/one-health-lyme-gap-atlas-data",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": "a" * 40,
    }
    return inputs, environment


def snapshot():
    lease = capture_lease(
        source_id="cdc-eid-expedited",
        registry_version=1,
        source_sha256="a" * 64,
        capture_id=SYNTHETIC_RUN,
        artifact_sha256=SYNTHETIC_SHA,
        captured_at="2026-09-01T00:00:00Z",
        policy_ref="reviewed-synthetic-raw30",
        permitted=lambda *_: True,
    )
    copies = (
        RawCopy(
            "PROD",
            lease.source_id,
            "checkpoint_payload",
            f"snowflake://{DATABASE}/GOVERNANCE/INGESTION_RUN_PAYLOADS/{SYNTHETIC_RUN}",
            lease.sha256,
        ),
        RawCopy(
            "PROD",
            lease.source_id,
            "raw_object",
            f"s3://{module.BUCKET}/prod/prod/cdc-eid-expedited/{SYNTHETIC_RUN}/{SYNTHETIC_SHA}.bin",
            lease.sha256,
        ),
    )
    return SimpleNamespace(
        environment="PROD",
        ledger=SimpleNamespace(guard=nullcontext),
        copies=lambda: copies,
        claims=lambda copy: tuple(c for c in copies if c.physical_key == copy.physical_key),
        lease=lambda _: lease,
    )


def test_protected_request_accepts_only_exact_main_and_existing_approval_lane():
    inputs, environment = request()
    assert module.validate_request(inputs, environment) == (
        "b" * 64,
        inputs["cleanup_planned_at"],
        inputs["cleanup_approval_ref"],
    )


@pytest.mark.parametrize("mode", module.OTHER_MODES)
def test_every_mixed_operation_is_rejected(mode):
    inputs, environment = request()
    inputs[mode] = True
    with pytest.raises(PermissionError):
        module.validate_request(inputs, environment)


@pytest.mark.parametrize(
    "key,value",
    [
        ("GITHUB_ACTIONS", "false"),
        ("GITHUB_REF", "refs/heads/unreviewed"),
        ("GITHUB_SHA", "c" * 40),
        ("GITHUB_REPOSITORY", "untrusted/repository"),
    ],
)
def test_unreviewed_execution_context_is_rejected(key, value):
    inputs, environment = request()
    environment[key] = value
    with pytest.raises(PermissionError):
        module.validate_request(inputs, environment)


@pytest.mark.parametrize(
    "key,value",
    [
        ("approve_intelligence_cleanup_only", False),
        ("cleanup_plan_sha256", "bad"),
        ("cleanup_approval_ref", "unsafe'; SQL"),
        ("cleanup_approval_ref", "x" * 129),
        ("image_digest", "sha256:" + "a" * 64),
        ("expected_pending_json", '[{"version":"V999"}]'),
        ("cleanup_planned_at", "2026-09-30T23:59:59+00:00"),
    ],
)
def test_invalid_approval_inputs_are_rejected(key, value):
    inputs, environment = request()
    inputs[key] = value
    with pytest.raises((PermissionError, ValueError)):
        module.validate_request(inputs, environment)


def test_future_plan_is_rejected():
    inputs, environment = request()
    inputs["cleanup_planned_at"] = (
        (datetime.now(UTC) + timedelta(days=1)).isoformat().replace("+00:00", "Z")
    )
    with pytest.raises(PermissionError):
        module.validate_request(inputs, environment)


def test_exact_plan_reuses_existing_separate_service_approver(monkeypatch, capsys):
    gate = snapshot()
    plan = synthetic_plan(gate, "2026-09-30T23:59:59Z")
    calls = []
    monkeypatch.setattr(module, "identity", lambda *args: calls.append(("identity", args)))
    monkeypatch.setattr(module, "gate_for", lambda *args: gate)
    monkeypatch.setattr(module, "approve", lambda *args: calls.append(("approve", args)))
    module.approve_exact_plan(plan.sha256, plan.planned_at, "reviewed-plan")
    assert calls[0] == ("identity", (module.factory, module.APPROVER_USER, module.APPROVER_ROLE))
    assert calls[1] == (
        "approve",
        (module.factory, gate, plan, "reviewed-plan", module.BUCKET, "prod"),
    )
    output = capsys.readouterr().out
    assert plan.sha256 in output
    assert all(copy.locator not in output for copy in plan.copies)


@pytest.mark.parametrize("change", ["hash", "missing", "extra", "identity"])
def test_failure_before_approval_never_reaches_approval_write(monkeypatch, change):
    gate = snapshot()
    plan = synthetic_plan(gate, "2026-09-30T23:59:59Z")
    monkeypatch.setattr(module, "identity", lambda *args: None)
    monkeypatch.setattr(module, "gate_for", lambda *args: gate)
    monkeypatch.setattr(module, "approve", lambda *args: pytest.fail("approval write occurred"))
    checksum = plan.sha256
    copies = gate.copies()
    if change == "hash":
        checksum = "0" * 64
    elif change == "missing":
        gate.copies = lambda: copies[:1]
    elif change == "extra":
        gate.copies = lambda: (
            copies
            + (replace(copies[0], locator=copies[0].locator.replace(SYNTHETIC_RUN, "other-run")),)
        )
    else:

        def deny(*args):
            raise PermissionError("wrong service")

        monkeypatch.setattr(module, "identity", deny)
    with pytest.raises(PermissionError):
        module.approve_exact_plan(checksum, plan.planned_at, "reviewed-plan")


def test_invalid_request_never_opens_service_connection(monkeypatch):
    inputs, _ = request()
    monkeypatch.setenv("CLEANUP_APPROVAL_INPUTS", json.dumps(inputs))
    monkeypatch.setenv("GITHUB_REF", "refs/heads/not-main")
    monkeypatch.setattr(module, "identity", lambda *args: pytest.fail("service connection opened"))
    with pytest.raises(PermissionError):
        module.main()


def test_actual_workflow_module_entry_point_imports_and_rejects_invalid_context():
    environment = os.environ.copy()
    environment["CLEANUP_APPROVAL_INPUTS"] = "{}"
    result = subprocess.run(
        [sys.executable, "-m", "scripts.approve_intelligence_raw_cleanup_prod"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip() == "INTELLIGENCE_RAW_PLAN_APPROVAL_FAILED"


def test_workflow_lane_cannot_reach_migration_deployment_or_secret_export():
    workflow = yaml.safe_load((ROOT / ".github/workflows/promote-prod.yml").read_text())
    jobs = workflow["jobs"]
    lane = jobs["approve-intelligence-cleanup"]
    assert lane["environment"] == "production"
    assert lane["permissions"] == {"contents": "read", "checks": "read"}
    for name, job in jobs.items():
        if name != "approve-intelligence-cleanup":
            assert "inputs.approve_intelligence_cleanup_only != true &&" in job["if"]
    runs = "\n".join(step.get("run", "") for step in lane["steps"])
    for forbidden in ("apply-migrations", "doctl", "execute --", "upload-artifact", "gh secret"):
        assert forbidden not in runs
    assert "check-runs" in runs and 'test "$GITHUB_REF" = refs/heads/main' in runs
    credential_steps = [step for step in lane["steps"] if "SNOWFLAKE_USER" in step.get("env", {})]
    assert len(credential_steps) == 1
    step = credential_steps[0]
    assert step["env"]["SNOWFLAKE_USER"] == "${{ secrets.SNOWFLAKE_USER }}"
    assert "RUNTIME_PRIVATE_KEY" not in str(step)
    assert "python -m scripts.approve_intelligence_raw_cleanup_prod" in step["run"]
    assert "trap 'rm -f" in step["run"] and "umask 077" in step["run"]


def test_all_existing_job_conditions_remain_isolated_for_every_mode_combination():
    workflow = yaml.safe_load((ROOT / ".github/workflows/promote-prod.yml").read_text())
    jobs = workflow["jobs"]

    def evaluate(expression, values):
        source = expression.removeprefix("${{").removesuffix("}}")
        source = source.replace("&&", "and").replace("||", "or")
        source = re.sub(r"\btrue\b", "True", source).strip()

        def visit(node):
            if isinstance(node, ast.Expression):
                return visit(node.body)
            if isinstance(node, ast.BoolOp):
                results = [visit(value) for value in node.values]
                return all(results) if isinstance(node.op, ast.And) else any(results)
            assert isinstance(node, ast.Compare) and len(node.ops) == 1
            assert isinstance(node.left, ast.Attribute) and node.left.value.id == "inputs"
            assert isinstance(node.comparators[0], ast.Constant)
            left, right = values[node.left.attr], node.comparators[0].value
            assert isinstance(node.ops[0], (ast.Eq, ast.NotEq))
            return left == right if isinstance(node.ops[0], ast.Eq) else left != right

        return visit(ast.parse(source, mode="eval"))

    for flags in itertools.product((False, True), repeat=len(module.OTHER_MODES)):
        values = dict(zip(module.OTHER_MODES, flags, strict=True))
        retained = values["retained_lineage_only"] or values["retained_human_lineage_only"]
        january = any(
            values[name]
            for name in (
                "january_climate_only",
                "january_bulk_recovery_only",
                "january_point_query_only",
                "county_context_only",
            )
        )
        integrity = values["release_integrity_only"]
        old = {
            "promote": not retained and (integrity or not january),
            "january-climate": not retained
            and not integrity
            and not values["cdc_admission_only"]
            and january,
            "retained-lineage": retained,
        }
        for approval_only, validation_only in itertools.product((False, True), repeat=2):
            values["approve_intelligence_cleanup_only"] = approval_only
            values["intelligence_daily_validate_only"] = validation_only
            for name, previously_enabled in old.items():
                assert evaluate(jobs[name]["if"], values) is (
                    previously_enabled
                    and not approval_only
                    and not values["intelligence_daily_only"]
                    and not validation_only
                )
