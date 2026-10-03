"""Bounded retained-input reconciliation, separate from source activation.

Catalog registration belongs to the existing runtime registration boundary.
Steward recording requires the existing DEV owner and a genuine reviewed decision.
This module never changes grants, V075, release pointers, or prior decisions.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .climate_publication import NOAA_ARTIFACT_ID, NOAA_SHA, RESOURCE_KEY, RUN_ID, TIGER_SHA
from .semantic_metadata import metadata_revision_id

TIGER_ARTIFACT_ID = f"{RESOURCE_KEY}:{RUN_ID}:510b7bc9e094d24e9094b19ba3b961ab"
DRAFT_METADATA_REVISIONS = frozenset(
    "metadata-revision:v1:" + digest
    for digest in (
        "ed0be9096896cdc96fb6eb7cd96e94b5aaa68cd3a09665cbcdffe141f55b5bc1",
        "451be4277a13388e095f025f2a2d0732077ea0709c0f17f24ebb6ff290b3b9c9",
        "f9dc471c056a240e9e232ec9820aec2d46d83b972ead9c298ea0656ff1e54553",
        "eeca19e48561852fe1fc38184cc67fc89bbfdc0a896d8a1d489b0c003027a7ca",
    )
)
INPUTS = (
    {
        "resource_key": RESOURCE_KEY,
        "dataset_key": "nclimgrid-daily-v1.0.0-scaled",
        "publisher": "NOAA NCEI",
        "url": "https://www.ncei.noaa.gov/data/nclimgrid-daily/access/grids/2025/ncdd-202501-grd-scaled.nc",
        "artifact_id": NOAA_ARTIFACT_ID,
        "sha256": NOAA_SHA,
        "byte_count": 61013299,
        "vintage": "v1.0.0-scaled-202501",
    },
    {
        "resource_key": "census_tiger_2025_us_county_analysis",
        "dataset_key": "census-tiger-line-2025-us-county",
        "publisher": "US Census Bureau",
        "url": "https://www2.census.gov/geo/tiger/TIGER2025/COUNTY/tl_2025_us_county.zip",
        "artifact_id": TIGER_ARTIFACT_ID,
        "sha256": TIGER_SHA,
        "byte_count": 83989800,
        "vintage": "2025",
    },
)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _id(kind: str, value: str) -> str:
    return hashlib.sha256(f"january-climate:{kind}:{value}".encode()).hexdigest()


def _identity(cursor: Any, role: str) -> str:
    cursor.execute("SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE()")
    user, actual_role, database = cursor.fetchone()
    _require(actual_role == role and database == "ONE_HEALTH_LYME_GAP_ATLAS_DEV", "REVIEW_IDENTITY")
    return str(user)


def inspect_retained_inputs(cursor: Any) -> list[dict[str, Any]]:
    """Fixed SELECTs: conflicting identities fail instead of being overwritten."""
    cursor.execute(
        "SELECT resource_key, status FROM GOVERNANCE.INGESTION_RUNS WHERE ingestion_run_id=%s",
        (RUN_ID,),
    )
    _require(cursor.fetchall() == [(RESOURCE_KEY, "COMPLETED")], "RETAINED_RUN")
    result = []
    for source in INPUTS:
        cursor.execute(
            "SELECT sha256, byte_count FROM GOVERNANCE.RAW_ARTIFACTS "
            "WHERE artifact_id=%s AND ingestion_run_id=%s",
            (source["artifact_id"], RUN_ID),
        )
        _require(
            cursor.fetchall() == [(source["sha256"], source["byte_count"])], "RETAINED_ARTIFACT"
        )
        cursor.execute(
            "SELECT r.resource_key, r.catalog_dataset_id, r.is_active, r.resource_url, "
            "r.canonical_source_url, d.dataset_key FROM GOVERNANCE.CATALOG_RESOURCES r "
            "LEFT JOIN GOVERNANCE.CATALOG_DATASETS d "
            "ON d.catalog_dataset_id=r.catalog_dataset_id "
            "WHERE r.resource_key=%s OR r.resource_url=%s OR r.canonical_source_url=%s",
            (source["resource_key"], source["url"], source["url"]),
        )
        resources = cursor.fetchall()
        _require(len(resources) <= 1, "AMBIGUOUS_CATALOG_RESOURCE")
        if resources:
            _require(resources[0][0] == source["resource_key"], "CATALOG_RESOURCE_CONFLICT")
            _require(
                resources[0][3:5] == (source["url"], source["url"]),
                "CATALOG_RESOURCE_URL_CONFLICT",
            )
            _require(
                resources[0][1] is not None and resources[0][5] == source["dataset_key"],
                "CATALOG_RESOURCE_DATASET_CONFLICT",
            )
        cursor.execute(
            "SELECT data_source_version_id, resource_key, artifact_id, status, "
            "approved_decision_id "
            "FROM GOVERNANCE.DATA_SOURCE_VERSIONS WHERE ingestion_run_id=%s AND artifact_id=%s",
            (RUN_ID, source["artifact_id"]),
        )
        versions = cursor.fetchall()
        _require(len(versions) <= 2, "AMBIGUOUS_SOURCE_VERSION")
        for version in versions:
            _require(
                version[1:3] == (source["resource_key"], source["artifact_id"]),
                "SOURCE_VERSION_CONFLICT",
            )
        _require(len({v[0] for v in versions}) == len(versions), "DUPLICATE_SOURCE_VERSION")
        _require(sum(v[3] == "PENDING" for v in versions) <= 1, "DUPLICATE_PENDING_VERSION")
        result.append({**source, "resources": resources, "versions": versions})
    return result


def register_pending_inputs(cursor: Any) -> list[str]:
    """Existing runtime INSERT authority only; no approval or activation.

    Caller owns the transaction and must roll back on failure. Run only after
    independent review through the existing protected runtime, without recapture.
    """
    _identity(cursor, "OH_LYME_DEV_RUNTIME")
    sources = inspect_retained_inputs(cursor)
    versions = []
    for source in sources:
        dataset_id = _id("dataset", source["dataset_key"])
        if not source["resources"]:
            cursor.execute(
                "SELECT catalog_dataset_id FROM GOVERNANCE.CATALOG_DATASETS WHERE dataset_key=%s",
                (source["dataset_key"],),
            )
            datasets = cursor.fetchall()
            _require(len(datasets) <= 1, "AMBIGUOUS_CATALOG_DATASET")
            if datasets:
                dataset_id = datasets[0][0]
            else:
                metadata = json.dumps(
                    {k: source[k] for k in ("publisher", "url", "vintage")}, sort_keys=True
                )
                cursor.execute(
                    "INSERT INTO GOVERNANCE.CATALOG_DATASETS (catalog_dataset_id, dataset_key, "
                    "catalog_name, "
                    "catalog_record_id, metadata_payload, metadata_sha256, discovered_at, "
                    "is_current) "
                    "SELECT %s,%s,'MANUAL',%s,PARSE_JSON(%s),%s,CURRENT_TIMESTAMP(),TRUE",
                    (
                        dataset_id,
                        source["dataset_key"],
                        source["dataset_key"],
                        metadata,
                        hashlib.sha256(metadata.encode()).hexdigest(),
                    ),
                )
            cursor.execute(
                "INSERT INTO GOVERNANCE.CATALOG_RESOURCES "
                "(catalog_resource_id,catalog_dataset_id,resource_key,"
                "resource_type,resource_url,canonical_source_url,api_dataset_id,resource_payload,"
                "registered_at,is_active) "
                "SELECT "
                "%s,%s,%s,'RETAINED_ANALYTICAL_INPUT',%s,%s,%s,PARSE_JSON(%s),"
                "CURRENT_TIMESTAMP(),FALSE",
                (
                    _id("resource", source["resource_key"]),
                    dataset_id,
                    source["resource_key"],
                    source["url"],
                    source["url"],
                    source["dataset_key"],
                    json.dumps(
                        {
                            "purpose": "retained January input reconciliation",
                            "ingestion_run_id": RUN_ID,
                        }
                    ),
                ),
            )
        if source["versions"]:
            versions.append(source["versions"][0][0])
            continue
        version_id = _id("version", source["artifact_id"])
        cursor.execute(
            "INSERT INTO GOVERNANCE.DATA_SOURCE_VERSIONS (data_source_version_id,resource_key,"
            "ingestion_run_id,artifact_id,status,approved_decision_id,created_at) "
            "SELECT %s,%s,%s,%s,'PENDING',NULL,CURRENT_TIMESTAMP()",
            (version_id, source["resource_key"], RUN_ID, source["artifact_id"]),
        )
        versions.append(version_id)
    return versions


def prepare_recorded_acceptance(
    packet: Mapping[str, Any], acceptance: Mapping[str, Any], *, recorded_at: str
) -> dict[str, Any]:
    """Prepare an auditable recording action without inventing the acceptance time.

    This performs no database operation. The recording action timestamp is distinct
    from the unknown original decision time. Every accepted content hash is recomputed.
    """
    proposals = packet.get("metadata_proposals")
    if not isinstance(proposals, list) or len(proposals) != 4:
        raise ValueError("ACCEPTANCE_PACKET")
    revisions = [metadata_revision_id(item) for item in proposals]
    _require(
        all(
            item.get("revision_id") == digest
            for item, digest in zip(proposals, revisions, strict=True)
        )
        and set(revisions) == DRAFT_METADATA_REVISIONS,
        "ACCEPTANCE_CONTENT_HASHES",
    )
    context = acceptance.get("acceptance_context", {})
    scope = acceptance.get("scope", {})
    _require(
        acceptance.get("approver") == "Matthew"
        and context.get("source_and_metadata_acceptance")
        == "ACCEPTED_WITH_THE_EXPLAINED_JANUARY_LIMITATIONS"
        and context.get("decision_timestamp") is None
        and scope.get("selected_run_id") == RUN_ID
        and scope.get("period") == "2025-01-01/2025-01-31"
        and scope.get("historical_expansion") == "DEFERRED"
        and scope.get("measures") == ["PRCP", "TMIN", "TMAX", "NOAA-native TAVG"]
        and packet.get("selected_run_id") == RUN_ID
        and acceptance.get("technical_or_scientific_approval") is False,
        "RECORDED_ACCEPTANCE_SCOPE",
    )
    return {
        "reviewer": "MATTHEWCARAWAY",
        "reviewed_at": recorded_at,
        "evidence": "https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/"
        "issues/443#issuecomment-5964172065",
        "rationale": "Persist Matthew's already supplied acceptance of the retained January "
        "NOAA/Census inputs and exact four definitions. The timestamp denotes this ledger "
        "recording action; the original acceptance time remains unknown. Descriptive county "
        "weather only with accepted coverage and labeled-day limitations. No scientific "
        "certification, historical expansion, activation, grants or PROD publication approval.",
        "accepted_metadata_revisions": sorted(revisions),
        "acceptance_provenance": {
            "original_decision_at": {"state": "UNKNOWN", "value": None},
            "ledger_recorded_at": recorded_at,
            "timestamp_basis": "LEDGER_RECORDING_ACTION_NOT_ORIGINAL_ACCEPTANCE",
        },
    }


def record_steward_decision(cursor: Any, decision: Mapping[str, Any]) -> list[str]:
    """Append reviewed owner decisions and new approved versions; preserve PENDING.

    Exact source/definition acceptance and technical binding checks are distinct.
    Recorded acceptance preserves its unknown original time in conditions; the
    ledger timestamp denotes the current recording action. Caller owns rollback.
    No runtime can use this path, and no UPDATE reclassifies prior versions.
    """
    user = _identity(cursor, "OH_LYME_DEV_OWNER")
    required = {"reviewer", "reviewed_at", "evidence", "rationale", "accepted_metadata_revisions"}
    _require(
        set(decision) in (required, required | {"acceptance_provenance"}), "STEWARD_DECISION_FIELDS"
    )
    _require(decision["reviewer"] == user, "STEWARD_REVIEWER")
    stamp = datetime.fromisoformat(decision["reviewed_at"])
    _require(stamp.tzinfo is not None and stamp.utcoffset() is not None, "STEWARD_TIME")
    _require(stamp <= datetime.now(UTC), "STEWARD_FUTURE_TIME")
    _require(
        isinstance(decision["evidence"], str)
        and re.fullmatch(
            r"https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/"
            r"(?:issues/[0-9]+#issuecomment-[0-9]+|pull/[0-9]+#pullrequestreview-[0-9]+)",
            decision["evidence"],
        )
        is not None,
        "STEWARD_EVIDENCE",
    )
    _require(
        isinstance(decision["rationale"], str) and 10 <= len(decision["rationale"]) <= 10000,
        "STEWARD_RATIONALE",
    )
    revisions = decision["accepted_metadata_revisions"]
    _require(
        isinstance(revisions, list)
        and len(revisions) == 4
        and all(
            isinstance(r, str) and r.startswith("metadata-revision:v1:") and len(r) == 85
            for r in revisions
        ),
        "STEWARD_METADATA_REVISIONS",
    )
    _require(set(revisions) == DRAFT_METADATA_REVISIONS, "STEWARD_EXACT_DEFINITIONS")
    provenance = decision.get("acceptance_provenance")
    if "acceptance_provenance" in decision:
        _require(
            provenance
            == {
                "original_decision_at": {"state": "UNKNOWN", "value": None},
                "ledger_recorded_at": decision["reviewed_at"],
                "timestamp_basis": "LEDGER_RECORDING_ACTION_NOT_ORIGINAL_ACCEPTANCE",
            },
            "ACCEPTANCE_PROVENANCE",
        )
    cursor.execute(
        "SELECT COUNT(*) FROM GOVERNANCE.APPROVAL_STEWARDS WHERE username=%s AND is_active=TRUE "
        "AND authorization_scope='GLOBAL'",
        (user,),
    )
    _require(cursor.fetchone() == (1,), "STEWARD_AUTHORITY")
    sources = inspect_retained_inputs(cursor)
    _require(all(s["resources"] and s["versions"] for s in sources), "REGISTER_INPUTS_FIRST")
    _require(
        all(len(s["versions"]) == 1 and s["versions"][0][3:] == ("PENDING", None) for s in sources),
        "EXISTING_REVIEW_REQUIRES_RECONCILIATION",
    )
    # Deterministic request identity makes retries observable; no UUID implies approval.
    request = _id("decision", json.dumps(dict(decision), sort_keys=True))
    versions = []
    for source in sources:
        version_id = _id("reviewed-version", request + source["artifact_id"])
        decision_id = _id("review", request + source["resource_key"])
        cursor.execute(
            "SELECT manual_review_decision_id FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS WHERE "
            "correlation_id=%s AND resource_key=%s",
            (request, source["resource_key"]),
        )
        _require(not cursor.fetchall(), "REVIEW_ALREADY_RECORDED_RECONCILE")
        cursor.execute(
            "INSERT INTO GOVERNANCE.MANUAL_REVIEW_DECISIONS "
            "(manual_review_decision_id,resource_key,"
            "decision,rationale,conditions,reviewer_username,decided_at,data_source_version_id,"
            "app_version,correlation_id) "
            "SELECT "
            "%s,%s,'APPROVED_WITH_CONDITIONS',%s,PARSE_JSON(%s),%s,%s,%s,"
            "'january-climate-review-v1',%s",
            (
                decision_id,
                source["resource_key"],
                decision["rationale"],
                json.dumps(
                    {
                        "scope": "January 2025 descriptive county weather only",
                        "evidence": decision["evidence"],
                        "accepted_metadata_revisions": revisions,
                        "acceptance_provenance": provenance,
                    }
                ),
                user,
                decision["reviewed_at"],
                version_id,
                request,
            ),
        )
        cursor.execute(
            "INSERT INTO GOVERNANCE.DATA_SOURCE_VERSIONS "
            "(data_source_version_id,resource_key,ingestion_run_id,"
            "artifact_id,status,approved_decision_id,created_at) SELECT "
            "%s,%s,%s,%s,'CONDITIONAL',%s,CURRENT_TIMESTAMP()",
            (version_id, source["resource_key"], RUN_ID, source["artifact_id"], decision_id),
        )
        versions.append(version_id)
    return versions


def reconcile(connection: Any, *, phase: str, decision: Mapping[str, Any] | None = None) -> Any:
    """Atomic bounded action: no partial registration/review on any failed gate."""
    _require(phase in {"inspect", "register-pending", "record-steward"}, "RECONCILIATION_PHASE")
    connection.autocommit(False)
    result: Any
    try:
        with connection.cursor() as cursor:
            if phase == "register-pending":
                result = register_pending_inputs(cursor)
            elif phase == "record-steward":
                _require(decision is not None, "STEWARD_DECISION_REQUIRED")
                result = record_steward_decision(cursor, decision or {})
            else:
                cursor.execute("SELECT CURRENT_DATABASE()")
                _require(cursor.fetchone() == ("ONE_HEALTH_LYME_GAP_ATLAS_DEV",), "REVIEW_DATABASE")
                result = inspect_retained_inputs(cursor)
        if phase == "inspect":
            connection.rollback()
        else:
            connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
