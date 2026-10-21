"""Materialize the reviewed January DEV manifest inside the protected release job."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from .climate_membership import validate_donor
from .climate_publication import NOAA_ARTIFACT_ID, NOAA_SHA, RESOURCE_KEY, RUN_ID, TIGER_SHA
from .climate_release import (
    CANDIDATE_SHA,
    CONTRACT,
    ROW_COUNT,
    reconstruct_capture_ids,
    validate_extension,
)
from .climate_semantics import PERIOD
from .climate_source_review import INPUTS, TIGER_ARTIFACT_ID
from .sql_sessions import connect

INPUT_CONTRACT = "atlas-january-climate-dev-release-input-v1"
MEMBERSHIP_SHA = "03f4ac5245e4d3006cbf3bf0948c4ef03862de838936ebd4df9c8448fed45ed8"
DEV_DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
OPERATOR = ("OH_LYME_DEV_MIGRATION_DEPLOY_SVC", "OH_LYME_DEV_MIGRATION_DEPLOYER")
REVIEW_PR = 657
REVIEW_API = "https://api.github.com/repos/Caraway-Labs/one-health-lyme-gap-atlas-data/pulls/657"


class ManifestPreparationBlocked(ValueError):
    """Sanitized, fixed-code preparation failure."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ManifestPreparationBlocked(code)


def verified_review(
    token: str, release_commit: str, *, review_pr: int = REVIEW_PR, exact_merge: bool = False
) -> dict[str, str]:
    """Bind recorded review to this exact merged release checkout."""
    require(bool(re.fullmatch(r"[0-9a-f]{40}", release_commit)), "JANUARY_REVIEW_COMMIT")
    require(bool(token), "JANUARY_REVIEW_TOKEN")

    def fetch(url: str) -> Any:
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "atlas-january-release",
            },
        )
        with urlopen(request, timeout=10) as response:
            return json.load(response)

    review_api = REVIEW_API.rsplit("/", 1)[0] + f"/{review_pr}"
    pull = fetch(review_api)
    require(
        isinstance(pull, dict)
        and pull.get("number") == review_pr
        and bool(pull.get("merged_at"))
        and bool(re.fullmatch(r"[0-9a-f]{40}", pull.get("merge_commit_sha", "")))
        and pull.get("base", {}).get("ref") == "main"
        and isinstance(pull.get("head", {}).get("sha"), str),
        "JANUARY_REVIEW_RELEASE_BINDING",
    )
    require(
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", pull["merge_commit_sha"], release_commit],
            check=False,
            capture_output=True,
        ).returncode
        == 0,
        "JANUARY_REVIEW_RELEASE_BINDING",
    )
    if exact_merge:
        require(pull["merge_commit_sha"] == release_commit, "JANUARY_EXACT_REVIEW_MERGE")
    reviewed_commit = pull["head"]["sha"]
    require(bool(re.fullmatch(r"[0-9a-f]{40}", reviewed_commit)), "JANUARY_REVIEW_RECORD")
    reviews: list[dict[str, Any]] = []
    for page in range(1, 11):
        suffix = "" if page == 1 else f"&page={page}"
        batch = fetch(review_api + "/reviews?per_page=100" + suffix)
        require(isinstance(batch, list), "JANUARY_REVIEW_RECORD")
        reviews.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ManifestPreparationBlocked("JANUARY_REVIEW_LIMIT")
    submitted = []
    seen: set[int] = set()
    for review in reviews:
        require(isinstance(review, dict), "JANUARY_REVIEW_RECORD")
        if review.get("state") == "PENDING":
            continue
        identifier = review.get("id")
        user = review.get("user")
        require(
            type(identifier) is int
            and identifier > 0
            and identifier not in seen
            and isinstance(user, dict)
            and isinstance(user.get("login"), str)
            and bool(user["login"])
            and review.get("state") in {"APPROVED", "COMMENTED", "CHANGES_REQUESTED", "DISMISSED"}
            and isinstance(review.get("commit_id"), str)
            and bool(re.fullmatch(r"[0-9a-f]{40}", review["commit_id"]))
            and isinstance(review.get("submitted_at"), str)
            and (review.get("body") is None or isinstance(review.get("body"), str))
            and review.get("html_url")
            == (
                "https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/"
                f"pull/{review_pr}#pullrequestreview-{identifier}"
            ),
            "JANUARY_REVIEW_RECORD",
        )
        assert isinstance(identifier, int)  # Established by the fail-closed check above.
        seen.add(identifier)
        try:
            timestamp = datetime.fromisoformat(review["submitted_at"].replace("Z", "+00:00"))
        except ValueError as error:
            raise ManifestPreparationBlocked("JANUARY_REVIEW_RECORD") from error
        require(timestamp.tzinfo is not None, "JANUARY_REVIEW_RECORD")
        submitted.append((timestamp, identifier, review))

    marker = f"Independent read-only review of exact head {reviewed_commit}: no material findings."
    pull_user = pull.get("user")
    author = pull_user.get("login") if isinstance(pull_user, dict) else None

    def approved(review: dict[str, Any]) -> bool:
        if review["commit_id"] != reviewed_commit:
            return False
        if review["state"] == "APPROVED":
            return (
                isinstance(author, str) and review["user"]["login"].casefold() != author.casefold()
            )
        return review["state"] == "COMMENTED" and (review.get("body") or "").strip() == marker

    # A different reviewer or a plain comment cannot clear an unresolved request.
    blockers: set[str] = set()
    for _, _, review in sorted(submitted, key=lambda item: item[:2]):
        actor = review["user"]["login"].casefold()
        if review["state"] == "CHANGES_REQUESTED":
            blockers.add(actor)
        elif approved(review):
            blockers.discard(actor)
    require(not blockers, "JANUARY_REVIEW_RECORD")
    matching = [
        item
        for item in submitted
        if item[2]["commit_id"] == reviewed_commit and item[2]["state"] != "DISMISSED"
    ]
    require(bool(matching), "JANUARY_REVIEW_RECORD")
    selected = max(matching, key=lambda item: item[:2])[2]
    require(approved(selected), "JANUARY_REVIEW_RECORD")
    return {
        "commit": reviewed_commit,
        "url": selected["html_url"],
        "reviewer": selected["user"]["login"],
    }


def prepare(
    cursor: Any,
    spec: dict[str, Any],
    metadata_packet: dict[str, Any],
    *,
    review_commit: str,
    review_url: str,
    reviewer: str,
) -> dict[str, Any]:
    """Read retained DEV evidence and return an existing semantic-release manifest."""
    require(
        spec
        == {
            "contract_version": INPUT_CONTRACT,
            "release_id": "governed-2026-10-09-january-climate-dev",
            "annual_release_id": "governed-2026-09-17-unknown-coverage",
            "annual_bundle_sha256": (
                "55192e53b0b046cfe5148c13ffe5c570f615ec233e2b5c1103247f00b1a51233"
            ),
            "ingestion_run_id": RUN_ID,
            "capture_membership_sha256": MEMBERSHIP_SHA,
            "row_count": ROW_COUNT,
        },
        "JANUARY_RELEASE_INPUT",
    )
    cursor.execute("SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()")
    identity = cursor.fetchone()
    require(
        isinstance(identity, tuple)
        and identity[:3] == (*OPERATOR, DEV_DATABASE)
        and identity[3] == "OH_LYME_DEV_INGEST_XS_WH",
        "JANUARY_RELEASE_IDENTITY",
    )
    cursor.execute(
        "SELECT p.current_release_id,r.status,r.bundle_sha256,r.source_manifest "
        "FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p "
        "JOIN PRESENTATION.SEMANTIC_RELEASES r ON r.release_id=p.current_release_id "
        "WHERE p.pointer_key='ATLAS' LIMIT 2"
    )
    rows = cursor.fetchall()
    require(
        len(rows) == 1
        and rows[0][:3] == (spec["annual_release_id"], "PUBLISHED", spec["annual_bundle_sha256"]),
        "JANUARY_ANNUAL_RELEASE_BINDING",
    )
    annual = json.loads(rows[0][3]) if isinstance(rows[0][3], str) else rows[0][3]
    validate_donor(annual, spec["annual_release_id"])
    cursor.execute(
        "SELECT COUNT(*),COALESCE(SUM(row_count),0),MIN(partition_ordinal),"
        "MAX(partition_ordinal) FROM GOVERNANCE.INGESTION_RUN_NORMALIZED_PARTITIONS "
        "WHERE ingestion_run_id=%s",
        (RUN_ID,),
    )
    require(cursor.fetchone() == (1560, ROW_COUNT, 0, 1559), "JANUARY_PARTITIONS")
    capture_ids = reconstruct_capture_ids(cursor, MEMBERSHIP_SHA)
    require(
        metadata_packet.get("status") == "DEV_OBSERVED_RECEIPT_METADATA_CANDIDATE_NOT_PUBLICATION"
        and metadata_packet.get("sources", {}).get("noaa", {}).get("source_version_id")
        == "a7a7c7af61c848fde98080feb7fdc7507516343f7b29580e710faa59db9f2f79"
        and metadata_packet.get("sources", {}).get("tiger", {}).get("source_version_id")
        == "ff75f53ed023a2abe96b1eabdbbe4ea7f7a6ebe9154dfd476301b639c925049b",
        "JANUARY_REVIEWED_SOURCES",
    )
    sources = {
        "noaa": {
            "source_version_id": metadata_packet["sources"]["noaa"]["source_version_id"],
            "artifact_id": NOAA_ARTIFACT_ID,
            "sha256": NOAA_SHA,
            "resource_key": RESOURCE_KEY,
        },
        "tiger": {
            "source_version_id": metadata_packet["sources"]["tiger"]["source_version_id"],
            "artifact_id": TIGER_ARTIFACT_ID,
            "sha256": TIGER_SHA,
            "resource_key": INPUTS[1]["resource_key"],
        },
    }
    extension = {
        "contract_version": CONTRACT,
        "period": PERIOD,
        "ingestion_run_id": RUN_ID,
        "candidate_sha256": CANDIDATE_SHA,
        "capture_membership_sha256": MEMBERSHIP_SHA,
        "row_count": ROW_COUNT,
        "metadata": metadata_packet["metadata_candidates"],
        "sources": sources,
        "review_evidence": {"commit": review_commit, "url": review_url, "reviewer": reviewer},
        "capture_ids": capture_ids,
    }
    validate_extension(extension)
    manifest = dict(annual)
    manifest.update(
        release_id=spec["release_id"],
        schema_version="2.0.0",
        methodology_version="semantic-2.0.0",
        generated_at=datetime.now(UTC).isoformat(),
        climate_extension=extension,
    )
    return manifest


def _run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = SnowflakeSettings()
    spec = json.loads(args.input.read_text(encoding="utf-8"))
    is_prod = spec.get("contract_version") == "atlas-january-climate-prod-release-input-v1"
    require(
        settings.snowflake_database
        == ("ONE_HEALTH_LYME_GAP_ATLAS_PROD" if is_prod else DEV_DATABASE),
        "JANUARY_TARGET_DATABASE",
    )
    release_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if is_prod:
        pulls = json.loads(
            subprocess.check_output(
                [
                    "gh",
                    "api",
                    f"repos/Caraway-Labs/one-health-lyme-gap-atlas-data/commits/{release_commit}/pulls",
                ],
                text=True,
            )
        )
        exact = [
            p for p in pulls if p.get("merge_commit_sha") == release_commit and p.get("merged_at")
        ]
        require(len(exact) == 1, "JANUARY_EXACT_REVIEW_MERGE")
        review = verified_review(
            os.environ.get("GH_TOKEN", ""),
            release_commit,
            review_pr=exact[0]["number"],
            exact_merge=True,
        )
    else:
        review = verified_review(os.environ.get("GH_TOKEN", ""), release_commit)
    spec = json.loads(args.input.read_text(encoding="utf-8"))
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    with connect(settings) as connection, connection.cursor() as cursor:
        if is_prod:
            from .climate_prod_manifest import prepare as prepare_prod

            manifest = prepare_prod(cursor, spec, metadata, review)
        else:
            manifest = prepare(
                cursor,
                spec,
                metadata,
                review_commit=review["commit"],
                review_url=review["url"],
                reviewer=review["reviewer"],
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=args.output.parent, prefix="january-manifest-")
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, separators=(",", ":"))
        os.replace(temporary, args.output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print(
        json.dumps(
            {
                "release_id": manifest["release_id"],
                "capture_count": ROW_COUNT,
                "membership_sha256": manifest["climate_extension"]["capture_membership_sha256"],
            }
        )
    )


def main() -> None:
    try:
        _run()
    except ManifestPreparationBlocked as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print("JANUARY_PREPARATION_UNAVAILABLE", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
