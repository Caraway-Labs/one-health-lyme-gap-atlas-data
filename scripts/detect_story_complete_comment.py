"""Detect the repo's existing "Story #<N> complete." comment convention.

Epic #294 / Story #299 time-motion audit found that stories #254 and #255
(among others) had their completion evidence posted as a plain issue comment
using the phrase "Story #<N> complete." but sat open for roughly a day and a
half afterward, only closed later in an unrelated batch. Nothing in the repo
acted on that comment at the time it was posted.

This module implements the detection half of a narrow, additive fix: flag the
issue for a human closure decision the moment that comment lands, instead of
waiting for someone to notice it in a later, unrelated session. It does not
close the issue itself. Per Epic #252's own acceptance gate ("a story is not
marked Done solely because local tests or deployment succeeded"), closing a
story is a human governance decision this script must not make; it only
removes the "nobody noticed" delay from that decision.
"""

from __future__ import annotations

import argparse
import re
import sys

# Anchored to the start of the comment (ignoring leading whitespace) so that a
# comment that merely *mentions* another story in passing (e.g. "see #254 for
# context") does not false-positive. Matches the exact convention observed in
# closed-story comments across #254, #255, #297, and #298: "Story #NNN
# complete" with an optional trailing period, case-insensitive.
_STORY_COMPLETE_PATTERN = re.compile(r"^\s*story\s+#(\d+)\s+complete\.?", re.IGNORECASE)


def is_story_complete_comment(issue_number: int, comment_body: str) -> bool:
    """Return True if `comment_body` is a completion comment for `issue_number`.

    The comment must open with "Story #<issue_number> complete" (case
    insensitive, optional trailing period). A completion comment posted on a
    different issue number, or referencing a different story mid-sentence,
    does not match.
    """
    match = _STORY_COMPLETE_PATTERN.match(comment_body)
    if match is None:
        return False
    return int(match.group(1)) == issue_number


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument("--comment-body", required=True)
    args = parser.parse_args(argv)

    if is_story_complete_comment(args.issue_number, args.comment_body):
        print("match")
        return 0
    print("no-match")
    return 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
