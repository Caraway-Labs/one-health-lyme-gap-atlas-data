"""Guard the Story #299 completion-comment flag workflow's shape.

Story #299 (Epic #294) time/motion audit: this workflow surfaces the repo's
existing "Story #<N> complete." comment convention immediately via a label
and ping, instead of leaving it to be noticed in a later, unrelated batch
(the ~28-hour gap measured for stories #254 and #255). It must never close
an issue itself; closure stays a human decision per Epic #252's evidence
gate.
"""

from __future__ import annotations

from pathlib import Path

_WORKFLOW_PATH = Path("./.github/workflows/flag-completed-story-comment.yml")


def _read_workflow() -> str:
    return _WORKFLOW_PATH.read_text(encoding="utf-8")


def test_workflow_file_exists() -> None:
    assert _WORKFLOW_PATH.is_file()


def test_triggers_on_issue_comment_created() -> None:
    workflow = _read_workflow()
    assert "issue_comment:" in workflow
    assert "types: [created]" in workflow


def test_only_acts_on_open_issues() -> None:
    workflow = _read_workflow()
    assert "github.event.issue.state == 'open'" in workflow


def test_uses_the_detector_script() -> None:
    workflow = _read_workflow()
    assert "scripts/detect_story_complete_comment.py" in workflow


def test_never_closes_the_issue() -> None:
    """Closure must remain a human decision; the workflow may only label/comment."""
    workflow = _read_workflow()
    assert "issue close" not in workflow
    assert "gh issue edit" in workflow
    assert "gh issue comment" in workflow


def test_scopes_write_permission_to_issues_only() -> None:
    workflow = _read_workflow()
    assert "permissions:" in workflow
    assert "issues: write" in workflow
