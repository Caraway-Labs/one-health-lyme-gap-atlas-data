"""Review records come from GitHub; fixture tests are not release acceptance."""

import json
import os
import shutil
import subprocess
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from lyme_gap_atlas_data import climate_manifest_prep as prep


@pytest.fixture
def records(monkeypatch):
    head, merge = "a" * 40, "b" * 40
    pull = {
        "number": 693,
        "merged_at": "2026-10-15T00:00:00Z",
        "merge_commit_sha": merge,
        "base": {"ref": "main"},
        "head": {"sha": head},
        "user": {"login": "author"},
    }
    review = {
        "id": 1,
        "commit_id": head,
        "state": "APPROVED",
        "body": "Reviewed; approved.",
        "submitted_at": "2026-10-15T01:00:00Z",
        "user": {"login": "peer"},
        "html_url": "https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/pull/693#pullrequestreview-1",
    }
    reviews = [review]

    def fetch(request, timeout):
        assert timeout == 10
        return BytesIO(json.dumps(reviews if "/reviews?" in request.full_url else pull).encode())

    monkeypatch.setattr(prep, "urlopen", fetch)
    monkeypatch.setattr(prep.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))

    def validate():
        return prep.verified_review("fixture", merge, review_pr=693, exact_merge=True)

    return pull, reviews, validate


def test_real_approval_shape_does_not_require_magic_sentence(records):
    _, reviews, validate = records
    assert validate() == {"commit": "a" * 40, "url": reviews[0]["html_url"], "reviewer": "peer"}


def test_review_pagination_does_not_ignore_later_blocker(records, monkeypatch):
    pull, reviews, validate = records
    first_page = []
    for identifier in range(1, 101):
        review = deepcopy(reviews[0])
        review.update(id=identifier, state="DISMISSED")
        review["html_url"] = review["html_url"].replace("review-1", f"review-{identifier}")
        first_page.append(review)
    first_page[0]["state"] = "APPROVED"
    blocker = deepcopy(reviews[0])
    blocker.update(id=101, state="CHANGES_REQUESTED")
    blocker["html_url"] = blocker["html_url"].replace("review-1", "review-101")
    requested = []

    def fetch(request, timeout):
        requested.append(request.full_url)
        payload = pull
        if "/reviews?" in request.full_url:
            payload = [blocker] if "&page=2" in request.full_url else first_page
        return BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(prep, "urlopen", fetch)
    with pytest.raises(prep.ManifestPreparationBlocked, match="JANUARY_REVIEW_RECORD"):
        validate()
    assert requested[-1].endswith("&page=2")


@pytest.mark.parametrize("change", ["obsolete", "missing", "self_approval", "wrong_merge"])
def test_wrong_or_missing_binding_is_rejected(records, change):
    pull, reviews, validate = records
    if change == "obsolete":
        reviews[0]["commit_id"] = "c" * 40
    elif change == "missing":
        reviews.clear()
    elif change == "self_approval":
        reviews[0]["user"]["login"] = "author"
    else:
        pull["merge_commit_sha"] = "d" * 40
    with pytest.raises(prep.ManifestPreparationBlocked):
        validate()


@pytest.mark.parametrize("change", ["id", "url", "user", "date", "body", "commit", "duplicate"])
def test_malformed_or_forged_review_fails_closed(records, change):
    _, reviews, validate = records
    if change == "id":
        reviews[0]["id"] = True
    elif change == "url":
        reviews[0]["html_url"] += "2"
    elif change == "user":
        reviews[0]["user"] = "peer"
    elif change == "date":
        reviews[0]["submitted_at"] = "invalid"
    elif change == "body":
        reviews[0]["body"] = {"forged": "APPROVED"}
    elif change == "commit":
        reviews[0]["commit_id"] = "invalid"
    else:
        reviews.append(deepcopy(reviews[0]))
    with pytest.raises(prep.ManifestPreparationBlocked):
        validate()


def test_another_review_cannot_clear_unresolved_changes_requested(records):
    _, reviews, validate = records
    blocker = deepcopy(reviews[0])
    blocker.update(
        id=2,
        state="CHANGES_REQUESTED",
        commit_id="c" * 40,
        submitted_at="2026-10-14T01:00:00Z",
        user={"login": "other-peer"},
    )
    blocker["html_url"] = blocker["html_url"].replace("review-1", "review-2")
    reviews.append(blocker)
    with pytest.raises(prep.ManifestPreparationBlocked):
        validate()
    resolution = deepcopy(reviews[0])
    resolution.update(id=3, submitted_at="2026-10-15T02:00:00Z", user={"login": "other-peer"})
    resolution["html_url"] = resolution["html_url"].replace("review-1", "review-3")
    reviews.append(resolution)
    assert validate()["reviewer"] == "other-peer"


def test_commented_attestation_remains_exact_and_auditable(records):
    _, reviews, validate = records
    reviews[0].update(state="COMMENTED", body="Ordinary comment; not an approval")
    with pytest.raises(prep.ManifestPreparationBlocked):
        validate()
    reviews[0]["body"] = (
        f"Independent read-only review of exact head {'a' * 40}: no material findings."
    )
    assert validate()["reviewer"] == "peer"


@pytest.mark.parametrize("protected", [False, True])
def test_ordinary_promote_shell_never_reads_january_only_variables(tmp_path, protected):
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    bash = str(git_bash) if os.name == "nt" and git_bash.exists() else shutil.which("bash")
    if not bash:
        pytest.skip("bash unavailable")
    workflow = yaml.safe_load(Path(".github/workflows/promote-prod.yml").read_text())
    step = next(
        s
        for s in workflow["jobs"]["promote"]["steps"]
        if s.get("name") == "Apply checksum-validated PROD migrations before image promotion"
    )
    assert "JANUARY_BULK_RECOVERY_ONLY" not in step["run"]
    script = step["run"].replace("${{ inputs.release_commit }}", "a" * 40)
    # Stub all external actions. No credentials, network, Snowflake or DDL.
    stubs = """
snow() { echo identity-stub; }
uv() { echo "UV:$*"; }
base64() { echo fixture; }
fold() { cat; }
export -f snow uv base64 fold
"""
    env = os.environ.copy()
    env.pop("JANUARY_BULK_RECOVERY_ONLY", None)
    env.update(
        RUNNER_TEMP=tmp_path.as_posix(),
        SNOWFLAKE_ACCOUNT="fixture",
        SNOWFLAKE_USER="fixture",
        SNOWFLAKE_ROLE="fixture",
        SNOWFLAKE_WAREHOUSE="fixture",
        SNOWFLAKE_DATABASE="fixture",
        SNOWFLAKE_PRIVATE_KEY_B64="fixture",
        SNOWFLAKE_PRIVATE_KEY_PASSPHRASE="fixture",
        EXPECTED_PENDING_JSON=(
            '[{"version":"V150","filename":"V150__prod_intelligence_raw_cleanup_authority.sql",'
            '"sha256":"883be2e32a84a461bcd20a46216b2a188a443c98ed8d913b443821208c99b4cb"}]'
            if protected
            else ""
        ),
        PROTECTED_INTELLIGENCE_PREREQUISITE="true" if protected else "false",
        GITHUB_SHA="a" * 40,
    )
    result = subprocess.run(
        [bash, "-c", stubs + script], env=env, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    assert "migration-authority-preflight" in result.stdout
    assert "apply-migrations" in result.stdout
