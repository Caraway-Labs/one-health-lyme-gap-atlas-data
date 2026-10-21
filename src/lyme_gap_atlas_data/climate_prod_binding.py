"""Explicit native PROD binding; never substitutes the frozen DEV capture."""

import hashlib
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from .climate_publication import RUN_ID

CONTRACT = "atlas-january-climate-release-extension-v2"
PROD = "ONE_HEALTH_LYME_GAP_ATLAS_PROD"


def validate_binding(extension: Mapping[str, Any]) -> None:
    if extension.get("target_environment") != "prod":
        raise ValueError("CLIMATE_PROD_ENVIRONMENT")
    run_id = extension.get("ingestion_run_id")
    if not isinstance(run_id, str) or run_id == RUN_ID or str(UUID(run_id)) != run_id:
        raise ValueError("CLIMATE_PROD_CAPTURE")
    if re.fullmatch(r"[0-9a-f]{64}", str(extension.get("candidate_sha256"))) is None:
        raise ValueError("CLIMATE_PROD_CANDIDATE")
    sources = extension.get("sources")
    evidence = extension.get("source_evidence")
    if (
        not isinstance(sources, Mapping)
        or not isinstance(evidence, Mapping)
        or set(evidence) != {"noaa", "tiger"}
    ):
        raise ValueError("CLIMATE_PROD_SOURCES")
    from .ingestion.nclimgrid_daily import NOAA_MEMBER, TIGER_MEMBER

    for key, member in (("noaa", NOAA_MEMBER), ("tiger", TIGER_MEMBER)):
        source = sources.get(key, {})
        retained = evidence[key]
        if (
            not isinstance(source, Mapping)
            or not isinstance(retained, Mapping)
            or set(retained) != {"ingestion_run_id", "artifact_id"}
            or retained["ingestion_run_id"] in {run_id, RUN_ID}
            or str(UUID(retained["ingestion_run_id"])) != retained["ingestion_run_id"]
            or not isinstance(retained["artifact_id"], str)
            or not retained["artifact_id"]
            or source.get("artifact_id")
            != (
                f"noaa_nclimgrid_daily_202501:{run_id}:"
                + hashlib.sha256(member.encode()).hexdigest()[:32]
            )
            or RUN_ID in str(source)
            or str(UUID(str(source.get("source_version_id", ""))))
            != source.get("source_version_id")
        ):
            raise ValueError("CLIMATE_PROD_SOURCE_BINDING")
    if sources["noaa"]["artifact_id"] == sources["tiger"]["artifact_id"]:
        raise ValueError("CLIMATE_PROD_SOURCE_BINDING")


def source_anchor(extension: Mapping[str, Any], key: str) -> tuple[str, str]:
    if extension.get("contract_version") == CONTRACT:
        retained = extension["source_evidence"][key]
        return retained["ingestion_run_id"], retained["artifact_id"]
    return RUN_ID, extension["sources"][key]["artifact_id"]


def approved_capture_binding(
    cursor: Any, version_id: str, decision_id: str, *, recovery_run_id: str | None = None
) -> dict[str, Any]:
    """Freeze both real source approvals in publication lineage."""
    from .climate_publication import NOAA_SHA, TIGER_SHA

    verify_execution_resource(cursor, "OH_LYME_PROD_RUNTIME", "OH_LYME_PROD_PIPELINE_SVC")
    cursor.execute("SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE()")
    if cursor.fetchone() != ("OH_LYME_PROD_PIPELINE_SVC", "OH_LYME_PROD_RUNTIME", PROD):
        raise ValueError("CLIMATE_PROD_CAPTURE_IDENTITY")
    cursor.execute(
        "SELECT ingestion_run_id,status FROM GOVERNANCE.INGESTION_RUNS "
        "WHERE resource_key='noaa_nclimgrid_daily_202501' AND run_mode='SOURCE_INGESTION' "
        "LIMIT 2"
    )
    retained = cursor.fetchall()
    if recovery_run_id is None:
        if retained:
            raise ValueError("CLIMATE_PROD_CAPTURE_ALREADY_RETAINED")
    else:
        from .climate_prod_manifest import PLANNED_RUN

        if recovery_run_id != PLANNED_RUN or retained != [(PLANNED_RUN, "FAILED")]:
            raise ValueError("CLIMATE_PROD_RECOVERY_RETAINED_RUN")
    result = {}
    for key, resource, digest in (
        ("noaa", "noaa_nclimgrid_daily_202501", NOAA_SHA),
        ("tiger", "census_tiger_2025_us_county_analysis", TIGER_SHA),
    ):
        cursor.execute(
            "SELECT v.data_source_version_id,v.approved_decision_id,"
            "v.ingestion_run_id,v.artifact_id "
            "FROM GOVERNANCE.DATA_SOURCE_VERSIONS v JOIN GOVERNANCE.RAW_ARTIFACTS a "
            "ON a.artifact_id=v.artifact_id AND a.ingestion_run_id=v.ingestion_run_id "
            "WHERE v.resource_key=%s AND v.status='CONDITIONAL' AND v.retired_at IS NULL "
            "AND v.approved_decision_id IS NOT NULL AND a.sha256=%s",
            (resource, digest),
        )
        rows = cursor.fetchall()
        if len(rows) != 1:
            raise ValueError("CLIMATE_PROD_CAPTURE_APPROVAL")
        version, decision, run, artifact = rows[0]
        if key == "noaa" and (version, decision) != (version_id, decision_id):
            raise ValueError("CLIMATE_PROD_CAPTURE_APPROVAL")
        result[key] = {
            "source_version_id": version,
            "decision_id": decision,
            "ingestion_run_id": run,
            "artifact_id": artifact,
        }
    if result["noaa"]["ingestion_run_id"] != result["tiger"]["ingestion_run_id"]:
        raise ValueError("CLIMATE_PROD_CAPTURE_PACKAGE")
    return result


def verify_capture_binding(cursor: Any, extension: Mapping[str, Any]) -> None:
    cursor.execute(
        "SELECT lineage FROM GOVERNANCE.INGESTION_PUBLICATIONS "
        "WHERE ingestion_run_id=%s AND resource_key='noaa_nclimgrid_daily_202501' "
        "AND status='STAGED' AND record_count=389856",
        (extension["ingestion_run_id"],),
    )
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise ValueError("CLIMATE_PROD_CAPTURE_LINEAGE")
    import json

    lineage = json.loads(rows[0][0]) if isinstance(rows[0][0], str) else rows[0][0]
    approvals = lineage.get("source_approvals", {})
    if set(approvals) != {"noaa", "tiger"}:
        raise ValueError("CLIMATE_PROD_CAPTURE_LINEAGE")
    for key in ("noaa", "tiger"):
        if approvals[key].get("source_version_id") != extension["sources"][key][
            "source_version_id"
        ] or any(
            approvals[key].get(field) != extension["source_evidence"][key][field]
            for field in ("ingestion_run_id", "artifact_id")
        ):
            raise ValueError("CLIMATE_PROD_CAPTURE_LINEAGE")
        cursor.execute(
            "SELECT approved_decision_id FROM GOVERNANCE.DATA_SOURCE_VERSIONS "
            "WHERE data_source_version_id=%s",
            (approvals[key]["source_version_id"],),
        )
        if cursor.fetchall() != [(approvals[key].get("decision_id"),)]:
            raise ValueError("CLIMATE_PROD_CAPTURE_LINEAGE")


ACCOUNT_LOCATOR_SHA256 = "9d740b2d2d7445285e80aea51237b1159401d6f6e29e49b996932c74f55df328"
WAREHOUSE = "OH_LYME_PROD_APPROVAL_XS_WH"
IDENTITY_SQL = (
    "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),"
    "CURRENT_WAREHOUSE(),CURRENT_REGION(),CURRENT_ACCOUNT()"
)


def execution_identity(cursor: Any, role: str, user: str) -> dict[str, Any]:
    """One read, all six gates; no guesses from a compound exception."""
    cursor.execute(IDENTITY_SQL)
    row = cursor.fetchone()
    shape = isinstance(row, (tuple, list)) and len(row) == 6
    expected = (user, role, PROD, WAREHOUSE, "AWS_US_WEST_2")
    fields = ("user", "role", "database", "warehouse", "region")
    checks = {
        field: bool(shape and row[index] == expected[index]) for index, field in enumerate(fields)
    }
    locator_hash = (
        hashlib.sha256(row[5].upper().encode()).hexdigest()
        if shape and isinstance(row[5], str) and row[5]
        else None
    )
    checks["account_locator"] = locator_hash == ACCOUNT_LOCATOR_SHA256
    failed = [field for field, passed in checks.items() if not passed]
    query_id = getattr(cursor, "sfqid", None)
    if not isinstance(query_id, str) or re.fullmatch(r"[0-9a-f-]{36}", query_id) is None:
        query_id = None
    return {
        "status": "PASS" if shape and not failed else "BLOCKED",
        "shape_verified": shape,
        "checks": checks,
        "failed_fields": failed,
        "account_locator_sha256": locator_hash,
        "warehouse_state": (
            "MATCH"
            if checks["warehouse"]
            else "NO_CURRENT_WAREHOUSE"
            if shape and row[3] is None
            else "MISMATCH_OR_UNVERIFIED"
        ),
        "query_id": query_id,
    }


def verify_execution_resource(cursor: Any, role: str, user: str) -> None:
    """Keep strict identity/capacity gates and identify which field failed."""
    import json

    from .climate_membership_diagnostic import validate_warehouse_cost

    identity = execution_identity(cursor, role, user)
    if identity["status"] != "PASS":
        print(json.dumps({"january_execution_identity": identity}), flush=True)
        raise ValueError("CLIMATE_PROD_EXECUTION_RESOURCE:" + ",".join(identity["failed_fields"]))
    warehouse = WAREHOUSE
    cursor.execute("SHOW WAREHOUSES LIKE 'OH_LYME_PROD_APPROVAL_XS_WH'")
    columns = [str(item[0]).lower() for item in cursor.description]
    rows = [dict(zip(columns, item, strict=True)) for item in cursor.fetchall()]
    if len(rows) != 1 or rows[0].get("name") != warehouse:
        raise ValueError("CLIMATE_PROD_EXECUTION_RESOURCE")
    validate_warehouse_cost(
        rows[0],
        {"standard_capability_evidence": {"edition": "STANDARD", "cloud": "AWS"}},
        "AWS_US_WEST_2",
        {},
    )
