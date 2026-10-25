"""Per-source daily-once outcomes and restoration verdicts.

The story's ``error_code X`` is the allowlisted code carried on the outcome
line. These tests use ``MALFORMED_FEED`` for that code and ``NORMALIZE`` for
the stage.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from runpy import run_path

import pytest
import yaml

from lyme_gap_atlas_data.ingestion.intelligence_runtime import DAILY_OPERATOR_STAGE_NAMES
from lyme_gap_atlas_data.intelligence_polling import (
    DAILY_OUTCOME_LOG_PREFIX,
    published_error_code,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPT = ROOT / "scripts" / "prod_intelligence_daily_job_spec.py"
WORKFLOW = ROOT / ".github" / "workflows" / "run-prod-intelligence-daily-once.yml"
_MODULE = run_path(str(SCRIPT))
DEPLOYMENT_ID = "33333333-3333-3333-3333-333333333333"
APP_ID = "11111111-1111-1111-1111-111111111111"
SECRET = "super-secret-value"


def _outcome_line(**fields: object) -> str:
    payload = {
        "source_id": "cdc-mmwr",
        "status": "FAILED",
        "error_code": "MALFORMED_FEED",
        "failed_stage": "NORMALIZE",
        "stage_timings_ms": {"NORMALIZE": 12000},
    }
    payload.update(fields)
    return str(_MODULE["OUTCOME_LOG_PREFIX"]) + json.dumps(payload, separators=(",", ":"))


def test_operator_stages_and_codes_match_the_daily_runner() -> None:
    assert _MODULE["OPERATOR_STAGES"] == DAILY_OPERATOR_STAGE_NAMES
    assert _MODULE["OUTCOME_LOG_PREFIX"] == DAILY_OUTCOME_LOG_PREFIX
    samples = [
        "MALFORMED_FEED",
        "INTELLIGENCE_DAILY_HARD_KILL",
        "UNCLASSIFIED_ValueError",
        "X",
        SECRET,
        "",
    ]
    for sample in samples:
        assert (_MODULE["published_outcome_code"](sample) is not None) == (
            published_error_code(sample) is not None
        )
        if published_error_code(sample) is not None:
            assert _MODULE["published_outcome_code"](sample) == published_error_code(sample)


def test_outcome_table_names_source_status_code_and_stage() -> None:
    table = _MODULE["format_outcome_table"](_MODULE["parse_daily_outcomes"](_outcome_line()))
    assert "cdc-mmwr | FAILED | MALFORMED_FEED | NORMALIZE | 12" in table
    assert table.startswith("source | status | error_code | failed_stage | seconds\n")


def test_non_allowlisted_code_and_other_log_text_stay_out_of_the_table() -> None:
    text = "\n".join(
        (
            f"SNOWFLAKE_PRIVATE_KEY={SECRET}",
            _outcome_line(error_code=SECRET, failed_stage="not a stage"),
        )
    )
    table = _MODULE["format_outcome_table"](_MODULE["parse_daily_outcomes"](text))
    assert SECRET not in table
    assert "cdc-mmwr | FAILED | UNCLASSIFIED_EXCEPTION | - | 12" in table


def test_later_outcome_for_the_same_source_replaces_the_earlier_one() -> None:
    text = "\n".join(
        (
            _outcome_line(status="COMPLETED", error_code=None, failed_stage=None),
            _outcome_line(),
        )
    )
    rows = _MODULE["parse_daily_outcomes"](text)
    assert [row["status"] for row in rows] == ["FAILED"]


def test_matching_digest_omits_the_restoration_failure_phrase() -> None:
    rows = _MODULE["parse_daily_outcomes"](_outcome_line())
    lines = _MODULE["result_lines"](operation_status=1, rows=rows, restored=True)
    assert lines == [
        "Daily operation FAILED: MALFORMED_FEED. "
        "Baseline topology restored: yes (verified by spec digest compare)."
    ]
    assert all("topology restoration failed" not in line for line in lines)
    assert _MODULE["result_exit_code"](operation_status=1, rows=rows, restored=True) == 1


def test_digest_mismatch_fails_with_the_restore_code() -> None:
    lines = _MODULE["result_lines"](operation_status=0, rows=[], restored=False)
    assert lines[-1] == (
        "INTELLIGENCE_DAILY_TOPOLOGY_RESTORE_MISMATCH: topology restoration failed"
    )
    assert _MODULE["result_exit_code"](operation_status=0, rows=[], restored=False) == 1


def test_failed_sources_keep_each_allowlisted_code_in_order() -> None:
    text = "\n".join(
        (
            _outcome_line(),
            _outcome_line(
                source_id="cdc-outbreaks",
                error_code="INTELLIGENCE_DAILY_HARD_KILL",
                failed_stage="FETCH",
            ),
        )
    )
    rows = _MODULE["parse_daily_outcomes"](text)
    message = _MODULE["daily_operation_message"](
        failed=True,
        codes=_MODULE["failure_codes"](1, rows),
        restored=True,
    )
    assert message.startswith(
        "Daily operation FAILED: MALFORMED_FEED, INTELLIGENCE_DAILY_HARD_KILL. "
    )


def test_reason_is_required_and_capped_at_200_characters(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    env = dict(os.environ, GITHUB_STEP_SUMMARY=str(summary))
    accepted = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "validate-reason",
            "--reason",
            "a" * 200,
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert accepted.returncode == 0
    assert "Dispatch reason: " + ("a" * 200) in summary.read_text(encoding="utf-8")

    rejected = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "validate-reason",
            "--reason",
            "b" * 201,
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert rejected.returncode == 1
    assert "INTELLIGENCE_DAILY_REASON_REQUIRED" in rejected.stderr
    assert "b" * 201 not in rejected.stdout
    assert "b" * 201 not in rejected.stderr
    assert "b" * 201 not in summary.read_text(encoding="utf-8")


def test_reason_cannot_inject_a_workflow_command(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "validate-reason",
            "--reason=::error::injected",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ, GITHUB_STEP_SUMMARY=str(summary)),
        check=False,
    )
    assert result.returncode == 0
    assert "::" not in result.stdout
    assert "::" not in summary.read_text(encoding="utf-8")
    assert "injected" in summary.read_text(encoding="utf-8")


def test_spec_compare_ignores_key_order_and_does_not_echo_the_spec(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    restored = tmp_path / "restored.json"
    baseline.write_text(
        json.dumps({"b": 1, "a": {"token": SECRET}}),
        encoding="utf-8",
    )
    restored.write_text(
        json.dumps({"a": {"token": SECRET}, "b": 1}),
        encoding="utf-8",
    )
    matched = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "compare-specs",
            "--baseline",
            str(baseline),
            "--restored",
            str(restored),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert matched.returncode == 0
    assert SECRET not in matched.stdout + matched.stderr
    restored.write_text("{", encoding="utf-8")
    mismatched = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "compare-specs",
            "--baseline",
            str(baseline),
            "--restored",
            str(restored),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert mismatched.returncode == 1
    assert SECRET not in mismatched.stdout + mismatched.stderr


def test_labeled_deployment_id_is_preferred_and_not_echoed_with_secrets(tmp_path: Path) -> None:
    output = tmp_path / "update.txt"
    output.write_text(
        "\n".join(
            (
                f"{APP_ID} 44444444-4444-4444-4444-444444444444",
                f"token={SECRET}",
                f"error deploying app (deployment ID: {DEPLOYMENT_ID}):",
                "progress",
            )
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "deployment-id",
            "--deployment-output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == DEPLOYMENT_ID
    assert SECRET not in result.stdout + result.stderr


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(name: str) -> dict:
    steps = _workflow()["jobs"]["run"]["steps"]
    return next(step for step in steps if step.get("name") == name)


def test_workflow_exposes_reason_concurrency_and_outcome_steps() -> None:
    document = _workflow()
    assert document["concurrency"] == {
        "group": "prod-app-topology",
        "cancel-in-progress": False,
    }
    reason = document[True]["workflow_dispatch"]["inputs"]["reason"]
    assert reason["required"] is True
    assert reason["type"] == "string"
    assert document["jobs"]["run"]["environment"] == "production"
    names = [step.get("name") for step in document["jobs"]["run"]["steps"]]
    assert "Validate dispatch reason" in names
    assert "Report per-source daily outcomes" in names
    assert "Restore baseline topology" in names
    assert "Verify restored spec digest" in names
    report = _step("Report per-source daily outcomes")
    restore = _step("Restore baseline topology")
    verify = _step("Verify restored spec digest")
    assert report["if"] == "always()"
    assert restore["if"] == "always()"
    assert verify["if"] == "always()"
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("doctl apps logs") == 1
    assert "timeout 120 doctl apps logs" in report["run"]
    assert "intelligence-daily-manual-once" in report["run"]
    assert "--type run" in report["run"]
    assert "--tail 2000" in report["run"]
    assert "--deployment" in report["run"]
    assert "render-outcomes" in report["run"]
    assert "compare-specs" in verify["run"]
    assert "render-result" in verify["run"]
    assert "validate-reason" in _step("Validate dispatch reason")["run"]
    assert "topology restoration failed" not in text


def _bash() -> str:
    if Path("/bin/bash").exists():
        return "/bin/bash"
    pytest.skip("workflow script requires bash")
    return ""


def _install_tool(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _tool_env(bin_dir: Path, work: Path, summary: Path, **extra: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["INTEL_DAILY_WORK"] = str(work)
    env["PROD_APP_ID"] = APP_ID
    env["GITHUB_STEP_SUMMARY"] = str(summary)
    env.update(extra)
    return env


def _run_step(name: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_bash(), "-c", _step(name)["run"]],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_ingestion_failure_is_reported_without_a_false_topology_message(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "ready").write_text("", encoding="utf-8")
    (work / "deployment_id").write_text(DEPLOYMENT_ID + "\n", encoding="utf-8")
    (work / "operation_status").write_text("1\n", encoding="utf-8")
    baseline = {"jobs": [{"name": "intelligence-feed-daily"}], "token": SECRET}
    (work / "baseline.json").write_text(json.dumps(baseline), encoding="utf-8")
    restored = tmp_path / "restored.json"
    restored.write_text(json.dumps({"token": SECRET, "jobs": baseline["jobs"]}), encoding="utf-8")
    calls = tmp_path / "doctl-calls"
    summary = tmp_path / "summary.md"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _install_tool(
        bin_dir,
        "python",
        f'#!/bin/bash\nexec {sys.executable} "$@"\n',
    )
    _install_tool(
        bin_dir,
        "doctl",
        """#!/bin/bash
set -u
printf '%s\\n' "$*" >> "$DOCTL_CALLS"
if [[ "$1" == "apps" && "$2" == "logs" ]]; then
  printf '%s\\n' "$LOG_SECRET"
  printf '%s\\n' "$LOG_LINE"
  exit 1
fi
if [[ "$1" == "apps" && "$2" == "update" ]]; then
  printf '%s\\n' "$LOG_SECRET" >&2
  exit 1
fi
if [[ "$1" == "apps" && "$2" == "spec" && "$3" == "get" ]]; then
  cat "$RESTORED_SPEC"
  exit 0
fi
printf 'unexpected doctl %s\\n' "$*" >&2
exit 1
""",
    )
    env = _tool_env(
        bin_dir,
        work,
        summary,
        DOCTL_CALLS=str(calls),
        RESTORED_SPEC=str(restored),
        LOG_SECRET=f"SNOWFLAKE_PRIVATE_KEY={SECRET}",
        LOG_LINE=_outcome_line(),
    )
    report = _run_step("Report per-source daily outcomes", env)
    restore = _run_step("Restore baseline topology", env)
    verify = _run_step("Verify restored spec digest", env)
    combined = "\n".join(
        (
            report.stdout,
            report.stderr,
            restore.stdout,
            restore.stderr,
            verify.stdout,
            verify.stderr,
        )
    )
    summary_text = summary.read_text(encoding="utf-8")
    assert report.returncode == 0, combined
    assert restore.returncode == 0, combined
    assert verify.returncode == 1, combined
    assert "cdc-mmwr | FAILED | MALFORMED_FEED | NORMALIZE" in summary_text
    assert "topology restoration failed" not in combined
    assert "topology restoration failed" not in summary_text
    assert "Daily operation FAILED: MALFORMED_FEED." in summary_text
    assert "Baseline topology restored: yes (verified by spec digest compare)." in summary_text
    assert SECRET not in combined
    assert SECRET not in summary_text
    log_calls = [
        line for line in calls.read_text(encoding="utf-8").splitlines() if " logs " in line
    ]
    assert len(log_calls) == 1
    assert "--tail 2000" in log_calls[0]
    assert "--type run" in log_calls[0]
    assert DEPLOYMENT_ID in log_calls[0]
    assert "restore_cli_status=1" in restore.stdout


def test_spec_digest_mismatch_fails_the_workflow_with_the_restore_code(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "ready").write_text("", encoding="utf-8")
    (work / "operation_status").write_text("0\n", encoding="utf-8")
    (work / "rows.json").write_text('{"logs_missing":false,"rows":[]}\n', encoding="utf-8")
    (work / "baseline.json").write_text(json.dumps({"jobs": ["baseline"]}), encoding="utf-8")
    restored = tmp_path / "restored.json"
    restored.write_text(json.dumps({"jobs": ["changed"]}), encoding="utf-8")
    summary = tmp_path / "summary.md"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _install_tool(bin_dir, "python", f'#!/bin/bash\nexec {sys.executable} "$@"\n')
    _install_tool(
        bin_dir,
        "doctl",
        """#!/bin/bash
set -u
if [[ "$1" == "apps" && "$2" == "spec" && "$3" == "get" ]]; then
  cat "$RESTORED_SPEC"
  exit 0
fi
exit 0
""",
    )
    env = _tool_env(bin_dir, work, summary, RESTORED_SPEC=str(restored))
    verify = _run_step("Verify restored spec digest", env)
    combined = verify.stdout + verify.stderr
    assert verify.returncode == 1, combined
    assert "INTELLIGENCE_DAILY_TOPOLOGY_RESTORE_MISMATCH" in combined
    assert "topology restoration failed" in combined
    assert "INTELLIGENCE_DAILY_TOPOLOGY_RESTORE_MISMATCH: topology restoration failed" in (
        summary.read_text(encoding="utf-8")
    )


def test_apply_records_the_failed_deployment_without_printing_its_output(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "ready").write_text("", encoding="utf-8")
    (work / "operation.json").write_text("{}\n", encoding="utf-8")
    summary = tmp_path / "summary.md"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _install_tool(bin_dir, "python", f'#!/bin/bash\nexec {sys.executable} "$@"\n')
    _install_tool(
        bin_dir,
        "doctl",
        f"""#!/bin/bash
printf '%s\\n' "{SECRET}"
printf '%s\\n' "error deploying app (deployment ID: {DEPLOYMENT_ID}):"
exit 1
""",
    )
    result = _run_step("Apply one-shot intelligence-daily job", _tool_env(bin_dir, work, summary))
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert SECRET not in combined
    assert (work / "operation_status").read_text(encoding="utf-8").strip() == "1"
    assert (work / "deployment_id").read_text(encoding="utf-8").strip() == DEPLOYMENT_ID
    assert not (work / "update-output.txt").exists()
    assert "operation_status=1" in result.stdout
    assert f"deployment_id={DEPLOYMENT_ID}" in result.stdout
