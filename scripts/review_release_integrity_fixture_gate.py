"""Verify independently configured human approvals before any fixture credentials."""

import json
import os
import re
import subprocess
from pathlib import Path


def validate_review_gate(head, pr, reviews, policy, checks):
    if not re.fullmatch(r"[0-9a-f]{40}", head) or pr["head"]["sha"] != head:
        raise ValueError("FIXTURE_EXACT_HEAD_REQUIRED")
    if pr["number"] != 706 or pr["state"] != "open" or not pr["draft"]:
        raise ValueError("FIXTURE_OPEN_DRAFT706_REQUIRED")
    if not any(
        c["name"] == "checks" and c["conclusion"] == "success" and c["head_sha"] == head
        for c in checks
    ):
        raise ValueError("FIXTURE_GREEN_EXACT_HEAD_REQUIRED")
    latest = {}
    for review in sorted(reviews, key=lambda r: r.get("submitted_at") or ""):
        latest[review["user"]["login"]] = review
    accepted = {}
    for discipline in ("engineering", "security"):
        allowed = policy.get(discipline)
        if (
            not isinstance(allowed, list)
            or not allowed
            or any(not isinstance(n, str) for n in allowed)
        ):
            raise ValueError("FIXTURE_CONFIGURED_HUMAN_REVIEW_POLICY_REQUIRED")
        matches = []
        for login in allowed:
            review = latest.get(login, {})
            if (
                login != pr["user"]["login"]
                and review.get("commit_id") == head
                and review.get("state") == "APPROVED"
                and review.get("user", {}).get("type") == "User"
                and review.get("author_association") in {"MEMBER", "OWNER"}
            ):
                matches.append({"login": login, "review_id": review["id"]})
        if not matches:
            raise ValueError("FIXTURE_EXACT_HEAD_HUMAN_" + discipline.upper() + "_REVIEW_REQUIRED")
        accepted[discipline] = matches
    return {
        "reviewed_commit": head,
        "human_reviews": accepted,
        "scope": "RI706_DEV_SYNTHETIC_TEST_ONLY_NOT_SCIENTIFIC_APPROVAL",
    }


def gh(path):
    pages = json.loads(
        subprocess.run(
            ["gh", "api", "--paginate", "--slurp", path], check=True, capture_output=True, text=True
        ).stdout
    )
    if isinstance(pages[0], list):
        return [row for page in pages for row in page]
    if "check_runs" in pages[0]:
        return {"check_runs": [row for page in pages for row in page["check_runs"]]}
    return pages[0]


def main():
    head = os.environ.get("REVIEWED_COMMIT", "")
    if head != os.environ.get("GITHUB_SHA"):
        raise ValueError("FIXTURE_DISPATCH_SHA_REQUIRED")
    repository = os.environ["GITHUB_REPOSITORY"]
    if repository != "Caraway-Labs/one-health-lyme-gap-atlas-data":
        raise ValueError("FIXTURE_REPOSITORY_REQUIRED")
    for name, value in os.environ.items():
        if name.startswith("LEGACY_INPUT_") and value not in {"", "false", "[]"}:
            raise ValueError("FIXTURE_CANNOT_COMBINE_LEGACY_MODE")
    inputs = json.loads(os.environ["RI706_DISPATCH_INPUTS"])
    allowed = {
        "release_integrity_fixture",
        "ri706_expected_artifacts",
        "ri706_synthetic_authorization",
        "reviewed_commit",
    }
    if any(
        value not in (False, "", "[]", None)
        for name, value in inputs.items()
        if name not in allowed
    ):
        raise ValueError("FIXTURE_CANNOT_COMBINE_LEGACY_MODE")
    if (
        inputs.get("ri706_synthetic_authorization")
        != "RI706_DEV_SYNTHETIC_TEST_ONLY_NOT_SCIENTIFIC_APPROVAL"
    ):
        raise ValueError("FIXTURE_EXPLICIT_SYNTHETIC_SCOPE_REQUIRED")
    policy = json.loads(os.environ.get("RI706_REVIEW_POLICY", "{}"))
    result = validate_review_gate(
        head,
        gh(f"repos/{repository}/pulls/706"),
        gh(f"repos/{repository}/pulls/706/reviews?per_page=100"),
        policy,
        gh(f"repos/{repository}/commits/{head}/check-runs?per_page=100")["check_runs"],
    )
    Path(os.environ["RI706_REVIEW_RECEIPT"]).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
