"""Guard the label-driven Cursor Cloud Agent dispatcher for data tickets.

The dispatcher is a port of the web repository's ``cursor-dispatch`` workflow.
It only launches agents and records labels/comments on the issue; it must
never merge, deploy, or touch DEV/PROD systems. The bash harness runs the real
script against fake ``gh`` and ``curl`` binaries, so no network or key is used.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github" / "workflows" / "cursor-dispatch.yml"
_SCRIPT = _ROOT / ".github" / "scripts" / "cursor-dispatch.sh"
_HARNESS = _ROOT / ".github" / "scripts" / "cursor-dispatch.test.sh"
_CLOSING = re.compile(r"(?i)\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\b[\s:]*#\d")


def test_dispatcher_files_exist() -> None:
    assert _WORKFLOW.is_file()
    assert _SCRIPT.is_file()
    assert _HARNESS.is_file()


def test_workflow_runs_the_committed_script() -> None:
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    assert "run: bash .github/scripts/cursor-dispatch.sh" in workflow
    assert "group: cursor-cloud-agent-dispatch" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "github.event.label.name == 'cursor:ready'" in workflow


def test_dispatcher_never_merges_or_dispatches_workflows() -> None:
    text = _SCRIPT.read_text(encoding="utf-8") + _WORKFLOW.read_text(encoding="utf-8")
    for forbidden in ("gh pr merge", "/merge", "gh workflow run", "/dispatches", "gh run rerun"):
        assert forbidden not in text


def test_script_has_no_closing_keyword_before_an_issue_number() -> None:
    assert _CLOSING.search(_SCRIPT.read_text(encoding="utf-8")) is None


@pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("jq") is None,
    reason="dispatcher harness needs bash and jq",
)
def test_dispatcher_harness_passes() -> None:
    env = {key: value for key, value in os.environ.items() if not key.startswith("CURSOR_")}
    result = subprocess.run(
        ["bash", str(_HARNESS)],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    assert "all dispatcher checks passed" in result.stdout
