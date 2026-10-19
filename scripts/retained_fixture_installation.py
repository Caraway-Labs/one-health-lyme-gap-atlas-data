"""Read an authenticated failed-run receipt to reuse identical installed fixture SQL."""

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from review_release_integrity_fixture_gate import (
    ENVIRONMENT,
    MARKER,
    REPOSITORY,
    gh,
    validate_retained_authorization,
)


def document(root, name):
    paths = list(root.rglob(name))
    if len(paths) != 1:
        raise ValueError("FIXTURE_UNIQUE_RETAINED_INSTALL_RECEIPT_REQUIRED")
    raw = paths[0].read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def validate_installation(run, receipt, artifacts):
    binding = receipt.get("installation_binding", receipt.get("binding", {}))
    if (
        run.get("status") != "completed"
        or run.get("conclusion") != "failure"
        or receipt.get("binding", {}).get("commit") != run.get("head_sha")
        or receipt.get("status") != "FAIL"
        or receipt.get("installation") != "PASS"
        or receipt.get("live_unchanged") is not True
        or binding.get("marker") != MARKER
        or binding.get("artifacts")
        != [
            a
            for a in artifacts
            if a["version"] in {x["version"] for x in binding.get("artifacts", [])}
        ]
        or {a["version"] for a in binding.get("artifacts", [])}
        not in ({"V157", "V158"}, {"V157", "V158", "V159"})
        or not re.fullmatch(r"[0-9a-f]{40}", binding.get("commit", ""))
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", binding.get("image_digest", ""))
    ):
        raise ValueError("FIXTURE_VERIFIED_IDENTICAL_INSTALLED_PAIR_REQUIRED")
    return binding


def load_recovery_proof(run_id, artifacts):
    if not run_id.isdecimal():
        raise ValueError("FIXTURE_RECOVERY_RUN_ID_REQUIRED")
    run = gh(f"repos/{REPOSITORY}/actions/runs/{run_id}")
    with tempfile.TemporaryDirectory(prefix="ri706-retained-install-") as directory:
        subprocess.run(
            [
                "gh",
                "run",
                "download",
                run_id,
                "--repo",
                REPOSITORY,
                "--name",
                f"ri706-dev-fixture-{run['head_sha']}-{run['run_attempt']}",
                "--dir",
                directory,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        root = Path(directory)
        receipt, receipt_hash = document(root, "acceptance.json")
        owner, owner_hash = document(root, "ri706-review.json")
        prior_artifacts = receipt.get("binding", {}).get("artifacts", [])
        if prior_artifacts != [
            a for a in artifacts if a["version"] in {x["version"] for x in prior_artifacts}
        ] or {a["version"] for a in prior_artifacts} not in (
            {"V157", "V158"},
            {"V157", "V158", "V159"},
        ):
            raise ValueError("FIXTURE_RETAINED_SQL_DRIFT")
        validate_retained_authorization(
            owner,
            run,
            prior_artifacts,
            gh(f"repos/{REPOSITORY}/environments/{ENVIRONMENT}"),
            gh(f"repos/{REPOSITORY}/actions/runs/{run_id}/approvals"),
        )
        if owner.get("reviewed_commit") != receipt.get("binding", {}).get("commit"):
            raise ValueError("FIXTURE_RETAINED_OWNER_SOURCE_MISMATCH")
        binding = validate_installation(run, receipt, artifacts)
        retained_cases = receipt.get("retained_cases", [])
        if retained_cases != owner.get("owner_authorization", {}).get("binding", {}).get(
            "recovery", {}
        ).get("atomic_publication_cases", []):
            raise ValueError("FIXTURE_RETAINED_ATOMIC_CASE_BINDING_MISMATCH")
        atomic_cases = {
            row["case"]: row
            for row in receipt.get("cases", []) + retained_cases
            if row.get("status") == "PASS"
            and row.get("case")
            in {
                "atomic_publication_failure",
                "assignment_insert_rolled_back",
                "batch_insert_rolled_back",
                "pointer_and_events_rolled_back",
            }
        }

        partial = list(root.rglob("partial-install.json"))
        partial_hash = (
            hashlib.sha256(partial[0].read_bytes()).hexdigest()
            if len(partial) == 1
            else owner.get("owner_authorization", {})
            .get("binding", {})
            .get("recovery", {})
            .get("partial_install_sha256")
        )
    result = {
        "run_id": run["id"],
        "run_attempt": run["run_attempt"],
        "acceptance_sha256": receipt_hash,
        "owner_receipt_sha256": owner_hash,
        "partial_install_sha256": partial_hash,
        "installation_binding": binding,
        "atomic_publication_cases": list(atomic_cases.values()),
    }

    if "correction_binding" in receipt:
        correction = receipt["correction_binding"]
        if (
            correction.get("artifacts") != artifacts
            or correction.get("marker") != MARKER
            or not re.fullmatch(r"[0-9a-f]{40}", correction.get("commit", ""))
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", correction.get("image_digest", ""))
        ):
            raise ValueError("FIXTURE_RETAINED_CORRECTION_BINDING_REQUIRED")
        result["correction_binding"] = correction
    return result
