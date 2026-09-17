"""Tests for the Story #299 completion-comment detector.

Fixture strings below are the real (lightly truncated) comment bodies
captured from the Epic #252 story chain during the Story #299 time/motion
audit, used to verify the detector matches exactly the comments that should
have triggered a closure prompt and none of the ones that should not.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "detect_story_complete_comment.py"
)
_SPEC = importlib.util.spec_from_file_location("detect_story_complete_comment", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
detect_story_complete_comment = importlib.util.module_from_spec(_SPEC)
sys.modules["detect_story_complete_comment"] = detect_story_complete_comment
_SPEC.loader.exec_module(detect_story_complete_comment)

is_story_complete_comment = detect_story_complete_comment.is_story_complete_comment

# Real comment bodies (truncated) that sat open for ~28 hours after this
# comment was posted, until an unrelated later batch closed them.
STORY_254_COMPLETION_COMMENT = (
    "Story #254 complete. `config/sources/cdc_qtbi_xd4i.yml` defines the "
    "historical 2008-2021 CDC source for the shared Socrata adapter/orchestrator "
    "with explicit era and value-state semantics."
)
STORY_255_COMPLETION_COMMENT = (
    "Story #255 complete. `run-ingestion.yml` is the single generic normal-path "
    "entry point and no longer forces dry-run."
)

# Real comment body on a still-in-progress story; must NOT match.
STORY_256_STATUS_COMMENT = (
    "Implemented and pushed the first restricted-pathogen increment in PR #287 "
    "(commit 845fc7f): separate DEV-only source profile, `PATHOGEN_PRESENCE_STATUS` "
    "contract, private-by-default parser, ADR 0029, and synthetic-only tests."
)
STORY_256_NOT_READY_COMMENT = (
    "## Status update - restricted CDC pathogen path (2026-09-17)\n\n"
    "**Story status: In Progress.** The work has advanced through protected DEV "
    "evidence capture, but it is not ready to close because the steward-review "
    "console migration has not yet installed successfully in DEV."
)


def test_matches_real_story_254_completion_comment() -> None:
    assert is_story_complete_comment(254, STORY_254_COMPLETION_COMMENT) is True


def test_matches_real_story_255_completion_comment() -> None:
    assert is_story_complete_comment(255, STORY_255_COMPLETION_COMMENT) is True


def test_does_not_match_in_progress_status_comment() -> None:
    assert is_story_complete_comment(256, STORY_256_STATUS_COMMENT) is False
    assert is_story_complete_comment(256, STORY_256_NOT_READY_COMMENT) is False


def test_does_not_match_when_issue_number_differs_from_comment() -> None:
    # Posted on the wrong issue (e.g. cross-linked mention) must not match.
    assert is_story_complete_comment(999, STORY_254_COMPLETION_COMMENT) is False


def test_does_not_match_mid_sentence_mention_of_another_story() -> None:
    body = "See Story #254 complete details in the epic tracker for context."
    assert is_story_complete_comment(254, body) is False


def test_case_insensitive_and_period_optional() -> None:
    assert is_story_complete_comment(300, "story #300 COMPLETE") is True
    assert is_story_complete_comment(300, "Story #300 complete") is True


def test_requires_matching_issue_number_not_just_any_number() -> None:
    assert is_story_complete_comment(297, "Story #298 complete.") is False


def test_cli_exit_codes(capsys: object) -> None:
    argv_match = ["--issue-number", "254", "--comment-body", STORY_254_COMPLETION_COMMENT]
    assert detect_story_complete_comment._main(argv_match) == 0

    argv_no_match = ["--issue-number", "256", "--comment-body", STORY_256_STATUS_COMMENT]
    assert detect_story_complete_comment._main(argv_no_match) == 1
