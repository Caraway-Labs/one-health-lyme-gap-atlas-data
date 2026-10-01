"""Fail-closed January extension for the existing immutable semantic release.

Only existing ledgers are read. No release pointer, grants, or approval is created
here. Review evidence is supplied by the protected, reviewed release manifest.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from .climate_publication import NOAA_ARTIFACT_ID, NOAA_SHA, RESOURCE_KEY, RUN_ID, TIGER_SHA
from .climate_semantics import PERIOD, january_measure_definitions
from .semantic_metadata import validate_metadata

CONTRACT = "atlas-january-climate-release-extension-v1"
CANDIDATE_SHA = "1e6b9809a5266d7cb3b4851f861835fdfddcf0d4f136a02d14e7e436806f5618"
ROW_COUNT = 389856
_SHA = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = {
    "contract_version",
    "period",
    "ingestion_run_id",
    "candidate_sha256",
    "capture_membership_sha256",
    "row_count",
    "metadata",
    "sources",
    "review_evidence",
}


class ClimateReleaseBlocked(ValueError):
    """Finite diagnostics without untrusted manifest or ledger content."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ClimateReleaseBlocked(code)


def validate_extension(extension: Any) -> None:
    """Validate persisted structure; pending metadata never grants exposure."""
    _require(isinstance(extension, Mapping) and set(extension) == _FIELDS, "CLIMATE_EXTENSION")
    _require(extension["contract_version"] == CONTRACT, "CLIMATE_CONTRACT")
    _require(extension["period"] == PERIOD, "CLIMATE_PERIOD")
    _require(extension["ingestion_run_id"] == RUN_ID, "CLIMATE_RUN")
    _require(extension["candidate_sha256"] == CANDIDATE_SHA, "CLIMATE_CANDIDATE_DIGEST")
    _require(
        type(extension["row_count"]) is int and extension["row_count"] == ROW_COUNT, "CLIMATE_COUNT"
    )
    _require(
        isinstance(extension["capture_membership_sha256"], str)
        and _SHA.fullmatch(extension["capture_membership_sha256"]) is not None,
        "CLIMATE_MEMBERSHIP_DIGEST",
    )
    review = extension["review_evidence"]
    _require(
        isinstance(review, Mapping) and set(review) == {"commit", "url", "reviewer"},
        "CLIMATE_REVIEW_EVIDENCE",
    )
    _require(
        isinstance(review["commit"], str)
        and re.fullmatch(r"[0-9a-f]{40}", review["commit"]) is not None
        and isinstance(review["reviewer"], str)
        and bool(review["reviewer"].strip())
        and isinstance(review["url"], str)
        and re.fullmatch(
            r"https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/"
            r"pull/[0-9]+(?:#pullrequestreview-[0-9]+)",
            review["url"],
        )
        is not None,
        "CLIMATE_REVIEW_EVIDENCE",
    )
    sources = extension["sources"]
    _require(isinstance(sources, Mapping) and set(sources) == {"noaa", "tiger"}, "CLIMATE_SOURCES")
    for key, expected_hash in (("noaa", NOAA_SHA), ("tiger", TIGER_SHA)):
        source = sources[key]
        _require(
            isinstance(source, Mapping)
            and set(source) == {"source_version_id", "artifact_id", "sha256"}
            and isinstance(source["source_version_id"], str)
            and bool(source["source_version_id"])
            and not source["source_version_id"].startswith("REPLACE_WITH_")
            and isinstance(source["artifact_id"], str)
            and bool(source["artifact_id"])
            and source["sha256"] == expected_hash,
            "CLIMATE_SOURCE_PIN",
        )
    _require(sources["noaa"]["artifact_id"] == NOAA_ARTIFACT_ID, "CLIMATE_NOAA_ARTIFACT")
    _require(
        sources["noaa"]["source_version_id"] != sources["tiger"]["source_version_id"],
        "CLIMATE_SOURCE_IDENTITIES",
    )
    metadata = extension["metadata"]
    definitions = january_measure_definitions()
    _require(isinstance(metadata, list) and len(metadata) == 4, "CLIMATE_METADATA")
    by_id = {
        item.get("measure", {}).get("measure_id"): item
        for item in metadata
        if isinstance(item, Mapping) and isinstance(item.get("measure"), Mapping)
    }
    _require(set(by_id) == {item["measure_id"] for item in definitions}, "CLIMATE_METADATA")
    for measure in definitions:
        item = by_id[measure["measure_id"]]
        _require(item["measure"] == measure, "CLIMATE_MEANING")
        validate_metadata(item, approved_climate_metadata_revisions={item["revision_id"]})
        _require(
            item["visibility"] == "CONSUMER_SAFE"
            and item["steward_review"]["state"] == "REVIEWED"
            and item["steward_review"]["reviewed_at"]["state"] == "KNOWN"
            and item["quality_evidence"]["evidence_basis"]
            == {"state": "KNOWN", "value": "CURRENT_CODE_SOURCE_BACKED_REPLAY"},
            "CLIMATE_REVIEWED_METADATA",
        )
        provenance = item["provenance"]
        _require(
            provenance["source_id"]["value"] == "source_noaa_nclimgrid_daily"
            and provenance["dataset_id"]["value"] == "nclimgrid-daily-v1.0.0-scaled"
            and provenance["source_version_id"]["value"] == sources["noaa"]["source_version_id"]
            and provenance["source_vintage"]["value"] == "v1.0.0-scaled-202501"
            and item["freshness"]["observation_period"]["value"] == PERIOD,
            "CLIMATE_METADATA_SOURCE",
        )


def verify_extension(cursor: Any, extension: Any) -> None:
    """Revalidate source approval and exact immutable revision membership at activation."""
    validate_extension(extension)
    for source in extension["sources"].values():
        cursor.execute(
            """SELECT v.status, v.approved_decision_id, v.retired_at
            FROM GOVERNANCE.DATA_SOURCE_VERSIONS v
            JOIN GOVERNANCE.RAW_ARTIFACTS a ON a.artifact_id=v.artifact_id
              AND a.ingestion_run_id=v.ingestion_run_id
            WHERE v.data_source_version_id=%s AND v.ingestion_run_id=%s
              AND v.artifact_id=%s AND a.sha256=%s""",
            (source["source_version_id"], RUN_ID, source["artifact_id"], source["sha256"]),
        )
        rows = cursor.fetchall()
        _require(
            len(rows) == 1
            and rows[0][0] in {"APPROVED", "CONDITIONAL"}
            and rows[0][1] is not None
            and rows[0][2] is None,
            "CLIMATE_SOURCE_APPROVAL",
        )
    cursor.execute(
        "SELECT resource_key, status FROM GOVERNANCE.INGESTION_RUNS WHERE ingestion_run_id=%s",
        (RUN_ID,),
    )
    _require(cursor.fetchall() == [(RESOURCE_KEY, "COMPLETED")], "CLIMATE_RUN_STATUS")
    cursor.execute(
        """SELECT COUNT(*), COUNT_IF(severity='BLOCKING' AND status='FAILED')
        FROM GOVERNANCE.DATA_QUALITY_RESULTS WHERE ingestion_run_id=%s""",
        (RUN_ID,),
    )
    quality = cursor.fetchone()
    _require(quality is not None and quality[0] > 0 and quality[1] == 0, "CLIMATE_QUALITY")
    cursor.execute(
        """SELECT capture_record_id, record_revision, record_id, source_row_hash, normalized_sha256
        FROM GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS WHERE ingestion_run_id=%s
          AND resource_key=%s AND source_definition_version=2 AND artifact_id=%s
          AND artifact_sha256=%s ORDER BY capture_record_id""",
        (RUN_ID, RESOURCE_KEY, NOAA_ARTIFACT_ID, NOAA_SHA),
    )
    digest = hashlib.sha256()
    count = 0
    previous = None
    while rows := cursor.fetchmany(250):
        for row in rows:
            _require(
                len(row) == 5 and all(isinstance(value, str) and value for value in row),
                "CLIMATE_MEMBERSHIP",
            )
            _require(previous is None or row[0] > previous, "CLIMATE_MEMBERSHIP_ORDER")
            _require(
                all(_SHA.fullmatch(value) is not None for value in row[3:]),
                "CLIMATE_MEMBERSHIP_HASH",
            )
            previous = row[0]
            digest.update((json.dumps(list(row), separators=(",", ":")) + "\n").encode())
            count += 1
    _require(
        count == ROW_COUNT and digest.hexdigest() == extension["capture_membership_sha256"],
        "CLIMATE_MEMBERSHIP_DIGEST",
    )
    cursor.execute(
        "SELECT COUNT(*) FROM GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS "
        "WHERE ingestion_run_id=%s",
        (RUN_ID,),
    )
    _require(cursor.fetchone() == (ROW_COUNT,), "CLIMATE_UNSELECTED_REVISIONS")
    cursor.execute(
        """SELECT COUNT(DISTINCT record_id), COUNT_IF(
          COALESCE(source_id,'')<>'source_noaa_nclimgrid_daily'
          OR COALESCE(dataset_id,'')<>'nclimgrid-daily-v1.0.0-scaled'
          OR COALESCE(payload:record:transformation_version::VARCHAR,'')<>
              'atlas-nclimgrid-county-day/2'
          OR COALESCE(payload:record:noaa_sha256::VARCHAR,'')<>%s
          OR COALESCE(payload:record:tiger_sha256::VARCHAR,'')<>%s
          OR COALESCE(payload:record:observation_date::VARCHAR,'') NOT BETWEEN
              '2025-01-01' AND '2025-01-31'
          OR COALESCE(payload:record:measure::VARCHAR,'') NOT IN ('PRCP','TMIN','TMAX','TAVG'))
        FROM GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS WHERE ingestion_run_id=%s""",
        (NOAA_SHA, TIGER_SHA, RUN_ID),
    )
    _require(cursor.fetchone() == (ROW_COUNT, 0), "CLIMATE_NATIVE_SCOPE")


def verify_persisted_extension(cursor: Any, release_id: str) -> None:
    """Both publication and rollback validate the retained target before pointer mutation."""
    cursor.execute(
        "SELECT source_manifest FROM PRESENTATION.SEMANTIC_RELEASES WHERE release_id=%s",
        (release_id,),
    )
    row = cursor.fetchone()
    _require(row is not None, "CLIMATE_RELEASE_MANIFEST")
    manifest = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    _require(isinstance(manifest, Mapping), "CLIMATE_RELEASE_MANIFEST")
    if "climate_extension" in manifest:
        verify_extension(cursor, manifest["climate_extension"])
