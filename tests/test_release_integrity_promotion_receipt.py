"""Isolated DEV proof replaces only the unrelated live-App prerequisite."""

import copy
import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


@pytest.fixture
def verifier(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "promotion_proof", ROOT / "scripts/verify_release_integrity_promotion.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def evidence(verifier):
    source, main, image = "a" * 40, "b" * 40, "sha256:" + "c" * 64
    artifacts = [{"version": "V157"}, {"version": "V158"}]
    pr = {
        "number": 706,
        "merged": True,
        "merge_commit_sha": main,
        "head": {"sha": source},
        "base": {"ref": "main"},
    }
    run = {
        "id": 123,
        "run_attempt": 1,
        "created_at": "2026-10-18T00:00:00Z",
        "updated_at": "2026-10-18T00:40:00Z",
        "repository": {"full_name": verifier.REPOSITORY},
        "head_sha": source,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "path": ".github/workflows/deploy-dev.yml",
    }
    cases = [
        "final_publication_membership",
        "complete_inventory_publish_and_rollback",
        "pointer_and_events_rolled_back",
        "one_concurrent_decision",
        "reader_publication_denied_after_valid_staging",
        "runtime_publication_denied_after_valid_staging",
    ]
    receipt = {
        "status": "PASS",
        "installation": "PASS",
        "live_unchanged": True,
        "binding": {
            "marker": verifier.MARKER,
            "commit": source,
            "image_digest": image,
            "artifacts": artifacts,
        },
        "cases": [{"case": case, "status": "PASS"} for case in cases],
        "frozen_county_sha256": "02b62d7a4cb8970b3cd2506f5206a386a9ceed7cb2253baea16299be2d06ec9b",
    }
    review = {
        "reviewed_commit": source,
        "pull_request": 706,
        "scope": verifier.MARKER,
        "owner_authorization": {
            "mechanism": verifier.MECHANISM,
            "owner": verifier.OWNER,
            "binding": verifier.execution_binding(source, run, artifacts),
            "binding_sha256": verifier.binding_digest(
                verifier.execution_binding(source, run, artifacts)
            ),
        },
    }
    return source, main, image, pr, run, receipt, review, artifacts


def test_identical_merge_tree_preserves_the_exact_tested_source_and_digest(verifier):
    source, main, image, pr, run, receipt, review, artifacts = evidence(verifier)
    result = verifier.validate(
        source,
        main,
        image,
        pr,
        run,
        receipt,
        review,
        same_tree=True,
        ancestor=True,
        artifacts=artifacts,
    )
    assert result == {"source_commit": source, "merged_main_commit": main, "image_digest": image}


def test_followup_review_identity_is_retained_and_cannot_be_substituted(verifier):
    source, main, image, pr, run, receipt, review, artifacts = evidence(verifier)
    pr["number"] = review["pull_request"] = 707
    verifier.validate(
        source,
        main,
        image,
        pr,
        run,
        receipt,
        review,
        same_tree=True,
        ancestor=True,
        artifacts=artifacts,
    )
    review["pull_request"] = 706
    with pytest.raises(ValueError, match="REVIEWED_SOURCE"):
        verifier.validate(
            source,
            main,
            image,
            pr,
            run,
            receipt,
            review,
            same_tree=True,
            ancestor=True,
            artifacts=artifacts,
        )


@pytest.mark.parametrize(
    "change",
    [
        "tree",
        "ancestry",
        "merge",
        "head",
        "workflow",
        "run",
        "digest",
        "checksum",
        "live",
        "partial",
        "permission",
        "review",
        "county",
    ],
)
def test_incomplete_or_substituted_proof_never_authorizes_installation(verifier, change):
    source, main, image, pr, run, receipt, review, artifacts = copy.deepcopy(evidence(verifier))
    if change == "merge":
        pr["merged"] = False
    elif change == "head":
        pr["head"]["sha"] = "d" * 40
    elif change == "workflow":
        run["path"] = ".github/workflows/quality.yml"
    elif change == "run":
        run["conclusion"] = "failure"
    elif change == "digest":
        receipt["binding"]["image_digest"] = "sha256:" + "d" * 64
    elif change == "checksum":
        receipt["binding"]["artifacts"] = []
    elif change == "live":
        receipt["live_unchanged"] = False
    elif change == "partial":
        receipt["status"] = "PLANNED_PARTIAL_INSTALL_TEST"
    elif change == "permission":
        receipt["cases"] = receipt["cases"][:-1]
    elif change == "review":
        review["owner_authorization"]["owner"] = {"login": "other"}
    elif change == "county":
        receipt["frozen_county_sha256"] = "wrong"
    with pytest.raises(ValueError, match="INTEGRITY_"):
        verifier.validate(
            source,
            main,
            image,
            pr,
            run,
            receipt,
            review,
            same_tree=change != "tree",
            ancestor=change != "ancestry",
            artifacts=artifacts,
        )


def test_download_layout_is_supported_but_duplicate_receipts_are_rejected(verifier, tmp_path):
    nested = tmp_path / "_temp" / "ri706-receipts"
    nested.mkdir(parents=True)
    (nested / "acceptance.json").write_text('{"status":"PASS"}')
    assert verifier.document(tmp_path, "acceptance.json") == {"status": "PASS"}
    (tmp_path / "acceptance.json").write_text("{}")
    with pytest.raises(ValueError, match="UNIQUE_RETAINED"):
        verifier.document(tmp_path, "acceptance.json")


def test_pair_install_never_requires_or_mutates_either_app_deployment():
    workflow = yaml.safe_load((ROOT / ".github/workflows/promote-prod.yml").read_text())
    steps = workflow["jobs"]["promote"]["steps"]
    for step in steps:
        if step.get("name") in {
            "Verify digest is currently deployed and approved in DEV",
            "Verify PROD target has been explicitly provisioned",
            "Promote the immutable image across the existing operational topology "
            "without exposing secrets",
        }:
            assert "inputs.release_integrity_only != true" in step["if"]
    assert workflow["jobs"]["promote"]["environment"] == "production"
    assert any("verify_release_integrity_promotion.py" in step.get("run", "") for step in steps)
