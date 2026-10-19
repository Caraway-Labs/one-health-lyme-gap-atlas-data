"""Bind migration-only PROD installation to the successful isolated DEV image."""

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from prepare_release_integrity_dev_plan import render_fixture
from review_release_integrity_fixture_gate import (
    ENVIRONMENT,
    MECHANISM,
    OWNER,
    binding_digest,
    execution_binding,
    gh,
    validate_retained_authorization,
)

from lyme_gap_atlas_data.migrations import load_migrations

REPOSITORY = "Caraway-Labs/one-health-lyme-gap-atlas-data"
MARKER = "RI706_DEV_SYNTHETIC_TEST_ONLY_NOT_SCIENTIFIC_APPROVAL"


def validate(source, main, image, pr, run, receipt, review, *, same_tree, ancestor, artifacts):
    if (
        not re.fullmatch(r"[0-9a-f]{40}", source)
        or not re.fullmatch(r"[0-9a-f]{40}", main)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", image)
        or not same_tree
        or not ancestor
        or not isinstance(review.get("pull_request"), int)
        or review["pull_request"] < 1
        or pr.get("number") != review["pull_request"]
        or not pr.get("merged")
        or pr.get("merge_commit_sha") != main
        or pr.get("head", {}).get("sha") != source
        or pr.get("base", {}).get("ref") != "main"
    ):
        raise ValueError("INTEGRITY_REVIEWED_SOURCE_AND_IDENTICAL_MERGED_TREE_REQUIRED")
    if (
        run.get("head_sha") != source
        or run.get("event") != "workflow_dispatch"
        or run.get("path") != ".github/workflows/deploy-dev.yml"
        or run.get("conclusion") != "success"
        or run.get("status") != "completed"
    ):
        raise ValueError("INTEGRITY_SUCCESSFUL_EXACT_SOURCE_DEV_FIXTURE_RUN_REQUIRED")
    expected = {"marker": MARKER, "commit": source, "image_digest": image, "artifacts": artifacts}
    names = {row["case"] for row in receipt.get("cases", []) if row.get("status") == "PASS"}
    required = {
        "final_publication_membership",
        "complete_inventory_publish_and_rollback",
        "pointer_and_events_rolled_back",
        "one_concurrent_decision",
        "reader_publication_denied_after_valid_staging",
        "runtime_publication_denied_after_valid_staging",
    }
    if (
        receipt.get("binding") != expected
        or receipt.get("status") != "PASS"
        or receipt.get("installation") != "PASS"
        or receipt.get("live_unchanged") is not True
        or not required <= names
        or receipt.get("frozen_county_sha256")
        != "02b62d7a4cb8970b3cd2506f5206a386a9ceed7cb2253baea16299be2d06ec9b"
        or review.get("reviewed_commit") != source
        or review.get("scope") != MARKER
        or review.get("owner_authorization", {}).get("mechanism") != MECHANISM
        or review["owner_authorization"].get("owner") != OWNER
        or review["owner_authorization"].get("binding") != execution_binding(source, run, artifacts)
        or review["owner_authorization"].get("binding_sha256")
        != binding_digest(execution_binding(source, run, artifacts))
    ):
        raise ValueError("INTEGRITY_COMPLETE_DIGEST_BOUND_DEV_ACCEPTANCE_REQUIRED")
    return {"source_commit": source, "merged_main_commit": main, "image_digest": image}


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def document(root, name):
    paths = list(root.rglob(name))
    if len(paths) != 1:
        raise ValueError("INTEGRITY_UNIQUE_RETAINED_RECEIPT_REQUIRED")
    return json.loads(paths[0].read_text())


def main():
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
    ):
        raise ValueError("INTEGRITY_PROTECTED_MAIN_WORKFLOW_REQUIRED")
    source, main_sha = os.environ["FIXTURE_SOURCE_COMMIT"], os.environ["REVIEWED_COMMIT"]
    run_id = os.environ["FIXTURE_VALIDATION_RUN_ID"]
    if (
        not re.fullmatch(r"[0-9a-f]{40}", source)
        or main_sha != os.environ["GITHUB_SHA"]
        or not run_id.isdecimal()
    ):
        raise ValueError("INTEGRITY_EXACT_SOURCE_MAIN_AND_RUN_REQUIRED")
    artifacts = [
        {
            "version": m.version,
            "filename": m.filename,
            "source_sha256": m.sha256,
            "rendered_sha256": hashlib.sha256(render_fixture(m).encode()).hexdigest(),
        }
        for m in load_migrations()
        if m.version in {"V157", "V158"}
    ]
    run = gh(f"repos/{REPOSITORY}/actions/runs/{run_id}")
    with tempfile.TemporaryDirectory(prefix="ri706-dev-proof-") as directory:
        subprocess.run(
            [
                "gh",
                "run",
                "download",
                run_id,
                "--repo",
                REPOSITORY,
                "--name",
                f"ri706-dev-fixture-{source}-{run['run_attempt']}",
                "--dir",
                directory,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        root = Path(directory)
        review = document(root, "ri706-review.json")
        number = review.get("pull_request")
        if not isinstance(number, int) or number < 1:
            raise ValueError("INTEGRITY_RETAINED_REVIEW_PR_REQUIRED")
        validate_retained_authorization(
            review,
            run,
            artifacts,
            gh(f"repos/{REPOSITORY}/environments/{ENVIRONMENT}"),
            gh(f"repos/{REPOSITORY}/actions/runs/{run_id}/approvals"),
        )
        result = validate(
            source,
            main_sha,
            os.environ["IMAGE_DIGEST"],
            gh(f"repos/{REPOSITORY}/pulls/{number}"),
            run,
            document(root, "acceptance.json"),
            review,
            same_tree=git("rev-parse", source + "^{tree}")
            == git("rev-parse", main_sha + "^{tree}"),
            ancestor=subprocess.run(
                ["git", "merge-base", "--is-ancestor", source, main_sha],
                capture_output=True,
            ).returncode
            == 0,
            artifacts=artifacts,
        )
    with Path(os.environ["GITHUB_ENV"]).open("a") as handle:
        handle.write("RI706_VALIDATED_SOURCE_COMMIT=" + result["source_commit"] + "\n")
        handle.write("RI706_VALIDATED_MERGE_COMMIT=" + result["merged_main_commit"] + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
