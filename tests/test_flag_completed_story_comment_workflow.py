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

from semantic_contracts import load_workflow, trigger_map, workflow_runs

_WORKFLOW_PATH = Path("./.github/workflows/flag-completed-story-comment.yml")


def test_workflow_file_exists() -> None:
    assert _WORKFLOW_PATH.is_file()


def test_triggers_on_issue_comment_created() -> None:
    triggers = trigger_map(load_workflow(_WORKFLOW_PATH))
    assert triggers["issue_comment"]["types"] == ["created"]
    assert "pull_request_target" not in triggers


def test_only_acts_on_open_issues() -> None:
    document = load_workflow(_WORKFLOW_PATH)
    assert document["jobs"]["flag-if-complete"]["if"] == "github.event.issue.state == 'open'"


def test_uses_the_detector_script() -> None:
    runs = "\n".join(workflow_runs(load_workflow(_WORKFLOW_PATH)))
    assert "scripts/detect_story_complete_comment.py" in runs


def test_never_closes_the_issue() -> None:
    """Closure must remain a human decision; the workflow may only label/comment."""
    runs = "\n".join(workflow_runs(load_workflow(_WORKFLOW_PATH)))
    assert "gh issue close" not in runs
    assert "issue close" not in runs
    assert "gh issue edit" in runs
    assert "gh issue comment" in runs


def test_scopes_write_permission_to_issues_only() -> None:
    document = load_workflow(_WORKFLOW_PATH)
    assert document["permissions"] == {"issues": "write"}
