"""Verify native, run-bound sole-owner DEV authorization; never submit approvals."""

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPOSITORY = "Caraway-Labs/one-health-lyme-gap-atlas-data"
OWNER = {"login": "CarawayLabs", "id": 5505084, "type": "User"}
ENVIRONMENT = "ri706-dev-fixture"
MARKER = "RI706_DEV_SYNTHETIC_TEST_ONLY_NOT_SCIENTIFIC_APPROVAL"
MECHANISM = "single-maintainer-environment-v1"
SCHEMAS = ["RI706_FEATURE_STORE", "RI706_PRESENTATION", "RI706_GOVERNANCE"]


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def binding_digest(binding):
    return hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def authorization_comment(binding):
    return "AUTHORIZE RI706 DEV ONLY sha256:" + binding_digest(binding)


def validate_source(head, pr, checks):
    if not re.fullmatch(r"[0-9a-f]{40}", head) or pr["head"]["sha"] != head:
        raise ValueError("FIXTURE_EXACT_HEAD_REQUIRED")
    if pr.get("base", {}).get("ref") != "main" or not (
        pr["state"] == "open" or (pr["state"] == "closed" and pr.get("merged") is True)
    ):
        raise ValueError("FIXTURE_OPEN_OR_MERGED_MAIN_PR_REQUIRED")
    if not any(
        c["name"] == "checks" and c["conclusion"] == "success" and c["head_sha"] == head
        for c in checks
    ):
        raise ValueError("FIXTURE_GREEN_EXACT_HEAD_REQUIRED")


def execution_binding(head, run, artifacts, recovery=None):
    if (
        run.get("head_sha") != head
        or run.get("event") != "workflow_dispatch"
        or run.get("path") != ".github/workflows/deploy-dev.yml"
        or run.get("repository", {}).get("full_name") != REPOSITORY
    ):
        raise ValueError("FIXTURE_AUTHENTICATED_EXACT_SOURCE_RUN_REQUIRED")
    created = timestamp(run["created_at"])
    result = {
        "mechanism": MECHANISM,
        "repository": REPOSITORY,
        "commit": head,
        "run_id": run["id"],
        "run_attempt": run["run_attempt"],
        "scope": MARKER,
        "environment": ENVIRONMENT,
        "database": "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
        "schemas": SCHEMAS,
        "artifacts": artifacts,
        "issued_at": created.isoformat(),
        "expires_at": (created + timedelta(hours=2)).isoformat(),
    }
    if recovery is not None:
        result["recovery"] = recovery
    return result


def validate_environment(environment):
    rules = [
        r for r in environment.get("protection_rules", []) if r["type"] == "required_reviewers"
    ]
    if (
        environment.get("name") != ENVIRONMENT
        or environment.get("can_admins_bypass") is not False
        or len(rules) != 1
        or rules[0].get("prevent_self_review") is not False
    ):
        raise ValueError("FIXTURE_NATIVE_OWNER_ENVIRONMENT_PROTECTION_REQUIRED")
    reviewers = rules[0].get("reviewers", [])
    if (
        len(reviewers) != 1
        or reviewers[0].get("type") != "User"
        or any(reviewers[0].get("reviewer", {}).get(key) != value for key, value in OWNER.items())
    ):
        raise ValueError("FIXTURE_VERIFIED_CARAWAYLABS_OWNER_REQUIRED")


def validate_owner_authorization(binding, environment, approvals, now):
    validate_environment(environment)
    if not timestamp(binding["issued_at"]) <= now < timestamp(binding["expires_at"]):
        raise ValueError("FIXTURE_OWNER_AUTHORIZATION_EXPIRED_OR_FUTURE")
    comment = authorization_comment(binding)
    matching = [
        r
        for r in approvals
        if r.get("comment") == comment
        and any(
            e.get("id") == environment["id"] and e.get("name") == ENVIRONMENT
            for e in r.get("environments", [])
        )
    ]
    if (
        len(matching) != 1
        or matching[0].get("state") != "approved"
        or any(matching[0].get("user", {}).get(key) != value for key, value in OWNER.items())
    ):
        raise ValueError("FIXTURE_NATIVE_EXACT_RUN_OWNER_AUTHORIZATION_REQUIRED")
    return {
        "mechanism": MECHANISM,
        "binding": binding,
        "binding_sha256": binding_digest(binding),
        "environment_id": environment["id"],
        "owner": OWNER,
        "native_approval": matching[0],
        "verified_at": now.isoformat(),
    }


def validate_retained_authorization(review, run, artifacts, environment, approvals):
    """A completed DEV receipt is evidence, not authorization for a new execution."""
    auth = review.get("owner_authorization", {})
    binding = execution_binding(
        review["reviewed_commit"], run, artifacts, auth.get("binding", {}).get("recovery")
    )
    verified = timestamp(auth.get("verified_at", "1970-01-01T00:00:00+00:00"))
    if auth != validate_owner_authorization(
        binding, environment, approvals, verified
    ) or verified > timestamp(run["updated_at"]):
        raise ValueError("INTEGRITY_NATIVE_OWNER_RECEIPT_BINDING_REQUIRED")


def select_review_pr(head, candidates, repository):
    matches = [
        pr
        for pr in candidates
        if pr.get("head", {}).get("sha") == head
        and pr.get("head", {}).get("repo", {}).get("full_name") == repository
        and pr.get("base", {}).get("ref") == "main"
        and pr.get("base", {}).get("repo", {}).get("full_name") == repository
    ]
    if len(matches) != 1:
        raise ValueError("FIXTURE_UNIQUE_EXACT_SOURCE_REPOSITORY_PR_REQUIRED")
    return matches[0]["number"]


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    head = os.environ.get("REVIEWED_COMMIT", "")
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or head != os.environ.get("GITHUB_SHA")
        or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
    ):
        raise ValueError("FIXTURE_PROTECTED_EXACT_SOURCE_WORKFLOW_REQUIRED")
    inputs = json.loads(os.environ["RI706_DISPATCH_INPUTS"])
    allowed = {
        "release_integrity_fixture",
        "ri706_expected_artifacts",
        "ri706_synthetic_authorization",
        "reviewed_commit",
        "ri706_recovery_run_id",
    }
    if any(
        value not in (False, "", "[]", None)
        for name, value in inputs.items()
        if name not in allowed
    ):
        raise ValueError("FIXTURE_CANNOT_COMBINE_LEGACY_MODE")
    if (
        inputs.get("ri706_synthetic_authorization") != MARKER
        or inputs.get("release_integrity_fixture") is not True
        or inputs.get("reviewed_commit") != head
        or inputs.get("ri706_expected_artifacts") != os.environ["RI706_EXPECTED_ARTIFACTS"]
    ):
        raise ValueError("FIXTURE_EXPLICIT_SYNTHETIC_SCOPE_REQUIRED")
    from prepare_release_integrity_dev_plan import render_fixture

    from lyme_gap_atlas_data.migrations import load_migrations

    artifacts = [
        {
            "version": m.version,
            "filename": m.filename,
            "source_sha256": m.sha256,
            "rendered_sha256": hashlib.sha256(render_fixture(m).encode()).hexdigest(),
        }
        for m in load_migrations()
        if m.version in {"V157", "V158", "V159"}
    ]
    if {a["version"] for a in artifacts} != {"V157", "V158", "V159"} or artifacts != json.loads(
        os.environ["RI706_EXPECTED_ARTIFACTS"]
    ):
        raise ValueError("FIXTURE_EXACT_SOURCE_AND_RENDERED_CHECKSUMS_REQUIRED")
    number = select_review_pr(
        head, gh(f"repos/{REPOSITORY}/commits/{head}/pulls?per_page=100"), REPOSITORY
    )
    validate_source(
        head,
        gh(f"repos/{REPOSITORY}/pulls/{number}"),
        gh(f"repos/{REPOSITORY}/commits/{head}/check-runs?per_page=100")["check_runs"],
    )
    run_id, attempt = os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"]
    if not run_id.isdecimal() or not attempt.isdecimal():
        raise ValueError("FIXTURE_NATIVE_RUN_ID_REQUIRED")
    run = gh(f"repos/{REPOSITORY}/actions/runs/{run_id}")
    if str(run["id"]) != run_id or str(run["run_attempt"]) != attempt:
        raise ValueError("FIXTURE_CURRENT_RUN_ATTEMPT_REQUIRED")
    recovery_id = inputs.get("ri706_recovery_run_id", "")
    recovery = None
    if recovery_id:
        from retained_fixture_installation import load_recovery_proof

        if str(recovery_id) == run_id:
            raise ValueError("FIXTURE_RECOVERY_CANNOT_REFERENCE_CURRENT_RUN")
        recovery = load_recovery_proof(recovery_id, artifacts)
    binding = execution_binding(head, run, artifacts, recovery)
    environment = gh(f"repos/{REPOSITORY}/environments/{ENVIRONMENT}")
    validate_environment(environment)
    now = datetime.now(UTC)
    if not timestamp(binding["issued_at"]) <= now < timestamp(binding["expires_at"]):
        raise ValueError("FIXTURE_OWNER_AUTHORIZATION_EXPIRED_OR_FUTURE")
    if args.prepare:
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as summary:
            summary.write(
                "## RI706 sole-owner DEV authorization\n\n"
                "CarawayLabs: Review deployments, select ri706-dev-fixture, paste this exact "
                "authorization comment, then Approve and deploy. No PROD authorization.\n\n```\n"
                + authorization_comment(binding)
                + "\n```\n\n```json\n"
                + json.dumps(binding, indent=2)
                + "\n```\n"
            )
        print(
            json.dumps(
                {"authorization_comment": authorization_comment(binding), "binding": binding}
            )
        )
        return
    approval = validate_owner_authorization(
        binding, environment, gh(f"repos/{REPOSITORY}/actions/runs/{run_id}/approvals"), now
    )
    receipt = {
        "reviewed_commit": head,
        "pull_request": number,
        "scope": MARKER,
        "owner_authorization": approval,
    }
    Path(os.environ["RI706_REVIEW_RECEIPT"]).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
