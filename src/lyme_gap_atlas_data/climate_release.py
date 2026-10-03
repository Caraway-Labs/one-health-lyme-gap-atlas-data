"""Fail-closed January extension for the existing immutable semantic release.

Only existing ledgers are read. No release pointer, grants, or approval is created
here. Review evidence is supplied by the protected, reviewed release manifest.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections.abc import Iterator, Mapping
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from .climate_publication import (
    NOAA_ARTIFACT_ID,
    NOAA_SHA,
    RESOURCE_KEY,
    RUN_ID,
    TIGER_SHA,
    project_verified_partitions,
)
from .climate_semantics import PERIOD, january_measure_definitions
from .climate_source_review import DRAFT_METADATA_REVISIONS, INPUTS, TIGER_ARTIFACT_ID
from .ingestion.checkpoints import _partition_from_document
from .ingestion.partitioning import NormalizedPartition
from .semantic_metadata import metadata_revision_id, validate_metadata

CONTRACT = "atlas-january-climate-release-extension-v1"
CANDIDATE_SHA = "1e6b9809a5266d7cb3b4851f861835fdfddcf0d4f136a02d14e7e436806f5618"
ROW_COUNT = 389856
# Date in the original four accepted draft hashes; never the enriched revision date.
ACCEPTED_DRAFT_METADATA_REVISED_AT = "2026-10-01"
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
    "capture_ids",
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
    capture_ids = extension["capture_ids"]
    _require(
        isinstance(capture_ids, list)
        and len(capture_ids) == ROW_COUNT
        and all(isinstance(item, str) and _SHA.fullmatch(item) is not None for item in capture_ids)
        and capture_ids == sorted(set(capture_ids)),
        "CLIMATE_CAPTURE_IDS",
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
            and set(source) == {"source_version_id", "artifact_id", "sha256", "resource_key"}
            and isinstance(source["resource_key"], str)
            and bool(source["resource_key"])
            and isinstance(source["source_version_id"], str)
            and bool(source["source_version_id"])
            and not source["source_version_id"].startswith("REPLACE_WITH_")
            and isinstance(source["artifact_id"], str)
            and bool(source["artifact_id"])
            and source["sha256"] == expected_hash,
            "CLIMATE_SOURCE_PIN",
        )
    _require(sources["noaa"]["artifact_id"] == NOAA_ARTIFACT_ID, "CLIMATE_NOAA_ARTIFACT")
    _require(sources["noaa"]["resource_key"] == RESOURCE_KEY, "CLIMATE_NOAA_RESOURCE")
    _require(sources["tiger"]["artifact_id"] == TIGER_ARTIFACT_ID, "CLIMATE_TIGER_ARTIFACT")
    _require(
        sources["tiger"]["resource_key"] == INPUTS[1]["resource_key"], "CLIMATE_TIGER_RESOURCE"
    )
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
            and item["quality_evidence"]["evidence_basis"]
            == {"state": "KNOWN", "value": "CURRENT_CODE_SOURCE_BACKED_REPLAY"},
            "CLIMATE_REVIEWED_METADATA",
        )
        provenance = item["provenance"]
        _require(
            provenance["source_id"]["value"] == "noaa_nclimgrid_daily"
            and provenance["dataset_id"]["value"] == "nclimgrid-daily-v1.0.0-scaled"
            and provenance["source_version_id"]["value"] == sources["noaa"]["source_version_id"]
            and provenance["source_vintage"]["value"] == "v1.0.0-scaled-202501"
            and item["freshness"]["observation_period"]["value"] == PERIOD,
            "CLIMATE_METADATA_SOURCE",
        )


def verify_recorded_acceptance(cursor: Any, extension: Any) -> None:
    """Bind recording-time metadata to actual owner decisions and accepted content.

    Original review time stays unknown. This does not turn a recording timestamp
    into a scientific review or authorize any source beyond the fixed January pins.
    """
    metadata = extension["metadata"]
    recorded = ["acceptance_recorded_at" in item["steward_review"] for item in metadata]
    if not any(recorded):
        return
    _require(all(recorded), "CLIMATE_MIXED_ACCEPTANCE")
    accepted = set()
    stamps = set()
    for item in metadata:
        original = deepcopy(item)
        original["visibility"] = "INTERNAL"
        original["metadata_revision"] = 1
        original["steward_review"] = {
            "state": "PENDING",
            "reviewed_at": {"state": "UNKNOWN", "value": None},
        }
        original["provenance"]["source_version_id"] = {"state": "UNKNOWN", "value": None}
        original["freshness"]["metadata_revised_at"] = {
            "state": "KNOWN",
            "value": ACCEPTED_DRAFT_METADATA_REVISED_AT,
        }
        accepted.add(metadata_revision_id(original))
        stamps.add(item["steward_review"]["acceptance_recorded_at"]["value"])
    _require(accepted == DRAFT_METADATA_REVISIONS and len(stamps) == 1, "CLIMATE_ACCEPTED_CONTENT")
    stamp = datetime.fromisoformat(next(iter(stamps)))
    for source in extension["sources"].values():
        cursor.execute(
            "SELECT d.reviewer_username,d.decided_at,d.conditions,d.data_source_version_id,"
            "d.decision,d.resource_key FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS d "
            "JOIN GOVERNANCE.DATA_SOURCE_VERSIONS v "
            "ON v.approved_decision_id=d.manual_review_decision_id "
            "AND d.resource_key=v.resource_key "
            "WHERE v.data_source_version_id=%s AND v.resource_key=%s "
            "AND v.ingestion_run_id=%s AND v.artifact_id=%s",
            (source["source_version_id"], source["resource_key"], RUN_ID, source["artifact_id"]),
        )
        rows = cursor.fetchall()
        _require(len(rows) == 1, "CLIMATE_ACCEPTANCE_DECISION")
        reviewer, decided_at, conditions, version, decision, decision_resource = rows[0]
        conditions = json.loads(conditions) if isinstance(conditions, str) else conditions
        _require(isinstance(conditions, Mapping), "CLIMATE_ACCEPTANCE_CONDITIONS")
        provenance = conditions.get("acceptance_provenance", {})
        _require(
            reviewer == "MATTHEWCARAWAY"
            and decided_at == stamp
            and version == source["source_version_id"]
            and decision_resource == source["resource_key"]
            and decision == "APPROVED_WITH_CONDITIONS"
            and set(conditions.get("accepted_metadata_revisions", [])) == accepted
            and provenance.get("original_decision_at") == {"state": "UNKNOWN", "value": None}
            and provenance.get("timestamp_basis")
            == "LEDGER_RECORDING_ACTION_NOT_ORIGINAL_ACCEPTANCE"
            and datetime.fromisoformat(provenance.get("ledger_recorded_at", "")) == stamp,
            "CLIMATE_ACCEPTANCE_PROVENANCE",
        )


def verify_extension(cursor: Any, extension: Any) -> None:
    """Revalidate source approval and exact immutable revision membership at activation."""
    validate_extension(extension)
    verify_recorded_acceptance(cursor, extension)
    for source in extension["sources"].values():
        cursor.execute(
            """SELECT v.status, v.approved_decision_id, v.retired_at
            FROM GOVERNANCE.DATA_SOURCE_VERSIONS v
            JOIN GOVERNANCE.RAW_ARTIFACTS a ON a.artifact_id=v.artifact_id
              AND a.ingestion_run_id=v.ingestion_run_id
            WHERE v.data_source_version_id=%s AND v.ingestion_run_id=%s
              AND v.artifact_id=%s AND a.sha256=%s AND v.resource_key=%s""",
            (
                source["source_version_id"],
                RUN_ID,
                source["artifact_id"],
                source["sha256"],
                source["resource_key"],
            ),
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
            _require(
                count < len(extension["capture_ids"]) and extension["capture_ids"][count] == row[0],
                "CLIMATE_CAPTURE_IDS",
            )
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
          COALESCE(source_id,'')<>'noaa_nclimgrid_daily'
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
    verify_payload_candidate(cursor, extension["candidate_sha256"])


def canonical_partitions(cursor: Any) -> Iterator[NormalizedPartition]:
    """Bounded reads using the same publication session; no hidden role/connection switch."""
    for ordinal in range(1560):
        cursor.execute(
            """SELECT partition_id, value_sha256, row_count, byte_count, records
            FROM GOVERNANCE.INGESTION_RUN_NORMALIZED_PARTITIONS
            WHERE ingestion_run_id=%s AND partition_ordinal=%s""",
            (RUN_ID, ordinal),
        )
        rows = cursor.fetchall()
        _require(len(rows) == 1, "CLIMATE_CANONICAL_PARTITION")
        partition_id, digest, row_count, byte_count, records = rows[0]
        records = json.loads(records) if isinstance(records, str) else records
        _require(
            isinstance(records, Mapping)
            and records.get("format") == "canonical-json-v1"
            and isinstance(records.get("canonical_json"), str),
            "CLIMATE_CANONICAL_BYTES",
        )
        partition = _partition_from_document(
            {
                "ordinal": ordinal,
                "sha256": digest,
                "byte_count": byte_count,
                "records": json.loads(records["canonical_json"]),
            }
        )
        _require(
            partition_id == partition.partition_id and row_count == len(partition.records),
            "CLIMATE_CANONICAL_PARTITION",
        )
        yield partition


def verify_payload_candidate(cursor: Any, expected_digest: str) -> None:
    """Rebuild the complete target candidate through PR549's strict reconciliation.

    All seven numeric fields retain native DOUBLE recovery, exact canonical
    payload/hash checks and scientific projection validation. Temporary outputs
    are removed. Missing canonical-partition SELECT fails closed; no grant is made.
    """
    with tempfile.TemporaryDirectory(prefix="climate-activation-") as directory:
        report = project_verified_partitions(
            cursor, canonical_partitions(cursor), Path(directory) / "candidate.ndjson"
        )
        _require(
            report["rows"] == ROW_COUNT and report["projection_sha256"] == expected_digest,
            "CLIMATE_TARGET_CANDIDATE_DIGEST",
        )


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


def verified_climate_metadata_revisions(cursor: Any, extension: Any) -> set[str]:
    """Return bounded revision authority only after full target/source verification."""
    verify_extension(cursor, extension)
    return {item["revision_id"] for item in extension["metadata"]}
