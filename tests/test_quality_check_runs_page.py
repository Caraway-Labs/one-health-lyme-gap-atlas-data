"""Quality check-run lookups must page past GitHub's default 30-item page."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_workflow_check_run_queries_request_a_full_page() -> None:
    offenders: list[str] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "gh api" not in line or "check-runs" not in line:
                continue
            if "check-runs?per_page=100" not in line:
                offenders.append(f"{path.name}:{line_no}")
    assert offenders == []
