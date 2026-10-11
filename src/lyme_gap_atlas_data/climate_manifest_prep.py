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


def verified_review(token: str, release_commit: str) -> dict[str, str]:
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

    pull = fetch(REVIEW_API)
    require(
        isinstance(pull, dict)
        and pull.get("number") == REVIEW_PR
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
    reviewed_commit = pull["head"]["sha"]
    reviews = fetch(REVIEW_API + "/reviews?per_page=100")
    require(isinstance(reviews, list), "JANUARY_REVIEW_RECORD")
    matching = [
        review
        for review in reviews
        if isinstance(review, dict)
        and review.get("commit_id") == reviewed_commit
        and review.get("state") in {"APPROVED", "COMMENTED", "CHANGES_REQUESTED"}
        and review.get("submitted_at")
        and isinstance(review.get("body"), str)
        and isinstance(review.get("user", {}).get("login"), str)
        and isinstance(review.get("html_url"), str)
        and re.fullmatch(
            r"https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/"
            r"pull/657#pullrequestreview-[0-9]+",
            review["html_url"],
        )
    ]
    require(bool(matching), "JANUARY_REVIEW_RECORD")
    selected = max(matching, key=lambda review: review["submitted_at"])
    require(
        selected["state"] in {"APPROVED", "COMMENTED"}
        and selected["body"].strip()
        == (f"Independent read-only review of exact head {reviewed_commit}: no material findings."),
        "JANUARY_REVIEW_RECORD",
    )
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
    require(settings.snowflake_database == DEV_DATABASE, "JANUARY_DEV_ONLY")
    release_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    review = verified_review(os.environ.get("GH_TOKEN", ""), release_commit)
    spec = json.loads(args.input.read_text(encoding="utf-8"))
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    with connect(settings) as connection, connection.cursor() as cursor:
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
                "membership_sha256": MEMBERSHIP_SHA,
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
