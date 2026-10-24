"""Workflow script references must exist at the same commit."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
CHECKER = ROOT / "scripts" / "check_workflow_script_paths.py"


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(root)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_missing_workflow_script_path_fails(tmp_path: Path) -> None:
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "example.yml").write_text(
        "jobs:\n  check:\n    steps:\n      - run: python scripts/missing_tool.py\n",
        encoding="utf-8",
    )
    result = _run(tmp_path)
    assert result.returncode == 1
    assert result.stdout.strip() == "example.yml: scripts/missing_tool.py"


def test_script_under_another_checkout_is_not_this_repo(tmp_path: Path) -> None:
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "handoff.yml").write_text(
        "run: python "
        '"$RUNNER_TEMP/ri706-handoff/scripts/assemble_138_surveillance_situation_batch.py"\n',
        encoding="utf-8",
    )
    result = _run(tmp_path)
    assert result.returncode == 0
    assert "assemble_138" not in result.stdout


def test_repository_workflow_scripts_exist() -> None:
    result = _run(ROOT)
    assert result.returncode == 0, result.stdout
    assert result.stdout.strip() == "workflow script paths: ok"
