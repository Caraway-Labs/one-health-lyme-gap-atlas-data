"""Bounded, exact-plan PROD EID raw expiry; never a feed acquisition command."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
from lyme_gap_atlas_shared.settings import SnowflakeSettings

from lyme_gap_atlas_data.ingestion.intelligence_runtime import pilot_watchdog
from lyme_gap_atlas_data.intelligence_items import TOKEN, canonical_json, identity_hash
from lyme_gap_atlas_data.intelligence_raw_cleanup import (
    ObjectRawDelete,
    execute_reviewed_prod_plan,
    load_exact_plan,
    prod_cleanup_scope,
)
from lyme_gap_atlas_data.intelligence_raw_runtime import FeedRawRetention, SnowflakeRawLedger
from lyme_gap_atlas_data.intelligence_retention import CleanupPlan, RawCopy, RawLease, plan_cleanup
from lyme_gap_atlas_data.settings import PipelineSettings
from lyme_gap_atlas_data.sql_sessions import connect

DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_PROD"
WAREHOUSE = "OH_LYME_PROD_INGEST_XS_WH"
EXECUTOR_USER = "OH_LYME_PROD_INTELLIGENCE_RAW_CLEANUP_SVC"
EXECUTOR_ROLE = "OH_LYME_PROD_INTELLIGENCE_RAW_CLEANUP"
APPROVER_USER = "OH_LYME_PROD_MIGRATION_DEPLOY_SVC"
APPROVER_ROLE = "OH_LYME_PROD_MIGRATION_DEPLOYER"
SYNTHETIC_RUN = "synthetic-proof-680"
SYNTHETIC_SHA = "35347e7199b7892e7a0202ed72eafc0147f5a28d1042f27a59d595c9d45fa6b2"


def inspection_query(sql: str) -> list[dict[str, Any]]:
    """Fixed read-only SQL through the named PAT CLI; never echo provider errors."""
    try:
        result = subprocess.run(
            [
                "snow",
                "sql",
                "-c",
                "ATLAS_PROD_RUNTIME_AUDIT",
                "--role",
                "OH_LYME_PROD_RUNTIME",
                "--database",
                DATABASE,
                "--warehouse",
                WAREHOUSE,
                "--format",
                "JSON",
                "-q",
                sql,
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=True,
        )
        rows = json.loads(result.stdout)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError
        return rows
    except (OSError, subprocess.SubprocessError, ValueError):
        raise PermissionError("INTELLIGENCE_RAW_INSPECTION_UNAVAILABLE") from None


def inspection_snapshot() -> Any:
    """A bounded value-only snapshot, using existing lease/claim validation."""
    rows = inspection_query(
        "SELECT document_type AS KIND,document_key AS KEY,document_sha256 AS SHA,"
        "TO_JSON(document) AS DOCUMENT FROM GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS "
        "WHERE document_type IN ('lease','copy') ORDER BY document_type,document_key LIMIT 100001"
    )
    if len(rows) > 100000:
        raise PermissionError("INTELLIGENCE_RAW_LEDGER_LIMIT")
    documents: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        document = json.loads(row["DOCUMENT"])
        key = (row["KIND"], row["KEY"])
        if identity_hash(document) != row["SHA"] or key in documents:
            raise PermissionError("INTELLIGENCE_RAW_LEDGER_INVALID")
        documents[key] = document
    copies = tuple(RawCopy(**doc) for (kind, _), doc in documents.items() if kind == "copy")

    def lease(sha: str) -> RawLease:
        value = RawLease(**documents[("lease", sha)])
        if value.sha256 != sha:
            raise PermissionError("INTELLIGENCE_RAW_LEDGER_INVALID")
        return value

    return SimpleNamespace(
        environment="PROD",
        copies=lambda: copies,
        claims=lambda copy: tuple(c for c in copies if c.physical_key == copy.physical_key),
        lease=lease,
    )


def synthetic_plan(snapshot: Any, now: str) -> CleanupPlan:
    driver = ObjectRawDelete(
        snapshot, object(), bucket="one-health-lyme-gap-atlas-data-prod", prefix="prod"
    )
    plan = plan_cleanup(
        snapshot,
        environment="PROD",
        source_ids=("cdc-eid-expedited",),
        now=now,
        scope=lambda copy: prod_cleanup_scope(copy, driver),
    )
    expected = {
        (
            "checkpoint_payload",
            f"snowflake://{DATABASE}/GOVERNANCE/INGESTION_RUN_PAYLOADS/{SYNTHETIC_RUN}",
        ),
        (
            "raw_object",
            f"s3://one-health-lyme-gap-atlas-data-prod/prod/prod/cdc-eid-expedited/{SYNTHETIC_RUN}/{SYNTHETIC_SHA}.bin",
        ),
    }
    if len(plan.copies) != 2 or {(c.kind, c.locator) for c in plan.copies} != expected:
        raise PermissionError("INTELLIGENCE_RAW_EXACT_SYNTHETIC_PAIR_REQUIRED")
    if len({c.lease_sha256 for c in plan.copies}) != 1 or any(
        snapshot.lease(c.lease_sha256).artifact_sha256 != SYNTHETIC_SHA
        or snapshot.lease(c.lease_sha256).capture_id != SYNTHETIC_RUN
        for c in plan.copies
    ):
        raise PermissionError("INTELLIGENCE_RAW_EXACT_SYNTHETIC_PAIR_REQUIRED")
    return plan


def inspection_identity() -> None:
    rows = inspection_query(
        "SELECT CURRENT_USER() AS U,CURRENT_ROLE() AS R,CURRENT_DATABASE() AS D,"
        "CURRENT_WAREHOUSE() AS W"
    )
    if rows != [
        {"U": "MATTHEWCARAWAY", "R": "OH_LYME_PROD_RUNTIME", "D": DATABASE, "W": WAREHOUSE}
    ]:
        raise PermissionError("INTELLIGENCE_RAW_INSPECTION_IDENTITY_REQUIRED")


def dry_run(path: Path) -> None:
    """SELECT + HEAD only. A human runtime audit is not executor/handoff proof."""
    inspection_identity()
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    snapshot = inspection_snapshot()
    plan = synthetic_plan(snapshot, now)
    key_id = os.environ.get("INTELLIGENCE_CLEANUP_SPACES_ACCESS_KEY_ID")
    secret = os.environ.get("INTELLIGENCE_CLEANUP_SPACES_SECRET_ACCESS_KEY")
    if not key_id or not secret:
        raise PermissionError("INTELLIGENCE_RAW_OBJECT_INSPECTION_CREDENTIAL_REQUIRED")
    client = boto3.client(
        "s3",
        endpoint_url="https://sfo3.digitaloceanspaces.com",
        region_name="sfo3",
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        config=Config(connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 1}),
    )
    driver = ObjectRawDelete(
        snapshot, client, bucket="one-health-lyme-gap-atlas-data-prod", prefix="prod"
    )
    object_copy = next(c for c in plan.copies if c.kind == "raw_object")
    try:
        driver.require_unversioned(object_copy)
        object_present = driver.exists(object_copy)
    except PermissionError:
        raise
    except Exception:
        raise PermissionError("INTELLIGENCE_RAW_OBJECT_INSPECTION_UNAVAILABLE") from None
    payloads = inspection_query(
        "SELECT COUNT(*) AS N,COUNT_IF(payload:raw_lease_sha256::VARCHAR="
        f"'{object_copy.lease_sha256}') AS MATCHED,COUNT_IF("
        "OCTET_LENGTH(TRY_BASE64_DECODE_BINARY(payload:xml_base64::VARCHAR))>0 "
        f"AND payload:artifact_sha256::VARCHAR='{SYNTHETIC_SHA}') AS RAW_BYTES "
        "FROM GOVERNANCE.INGESTION_RUN_PAYLOADS "
        f"WHERE ingestion_run_id='{SYNTHETIC_RUN}'"
    )
    if payloads != [{"N": 1, "MATCHED": 1, "RAW_BYTES": 1}] or not object_present:
        raise PermissionError("INTELLIGENCE_RAW_SYNTHETIC_BYTES_REQUIRED")
    if synthetic_plan(inspection_snapshot(), now) != plan:
        raise PermissionError("INTELLIGENCE_RAW_PLAN_CHANGED")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(canonical_json(asdict(plan)))
    print(
        json.dumps(
            {
                "plan_sha256": plan.sha256,
                "copy_count": 2,
                "synthetic_targets": 1,
                "snowflake_present": True,
                "spaces_present": True,
                "writes": False,
                "deletes": False,
                "executor_identity_proven": False,
            }
        )
    )


def deadline_check() -> None:
    """Read-only physical-copy alarm; never equate expiry or a receipt with absence."""
    inspection_identity()
    now = datetime.now(UTC)
    snapshot = inspection_snapshot()
    key_id = os.environ.get("INTELLIGENCE_CLEANUP_SPACES_ACCESS_KEY_ID")
    secret = os.environ.get("INTELLIGENCE_CLEANUP_SPACES_SECRET_ACCESS_KEY")
    if not key_id or not secret:
        raise PermissionError("INTELLIGENCE_RAW_OBJECT_INSPECTION_CREDENTIAL_REQUIRED")
    client = boto3.client(
        "s3",
        endpoint_url="https://sfo3.digitaloceanspaces.com",
        region_name="sfo3",
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        config=Config(connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 1}),
    )
    driver = ObjectRawDelete(
        snapshot, client, bucket="one-health-lyme-gap-atlas-data-prod", prefix="prod"
    )
    # Validate all lease/claim relationships, not just targets with alarm deadlines.
    plan_cleanup(
        snapshot,
        environment="PROD",
        source_ids=("cdc-eid-expedited",),
        now=now.isoformat().replace("+00:00", "Z"),
        scope=lambda copy: prod_cleanup_scope(copy, driver),
    )
    seen = set()
    remaining = urgent = overdue = 0
    copies = snapshot.copies()
    if len(copies) > 1000:
        raise PermissionError("INTELLIGENCE_RAW_DEADLINE_LIMIT")
    for copy in copies:
        if copy.environment != "PROD" or copy.source_id != "cdc-eid-expedited":
            continue
        if copy.kind not in {"raw_object", "checkpoint_payload"}:
            continue  # Managed process/cache buffers have no persistent backend here.
        if not prod_cleanup_scope(copy, driver):
            raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")
        claims = snapshot.claims(copy)
        deadline = min(
            datetime.fromisoformat(snapshot.lease(c.lease_sha256).expires_at.replace("Z", "+00:00"))
            for c in claims
        )
        if deadline > now + timedelta(hours=48) or copy.physical_key in seen:
            continue
        seen.add(copy.physical_key)
        if copy.kind == "raw_object":
            try:
                driver.require_unversioned(copy)
                present = driver.exists(copy)
            except PermissionError:
                raise
            except Exception:
                raise PermissionError("INTELLIGENCE_RAW_OBJECT_INSPECTION_UNAVAILABLE") from None
        else:
            run_id = copy.locator.rsplit("/", 1)[-1]
            if not TOKEN.fullmatch(run_id):
                raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")
            rows = inspection_query(
                "SELECT COUNT(*) AS N FROM GOVERNANCE.INGESTION_RUN_PAYLOADS "
                f"WHERE ingestion_run_id='{run_id}'"
            )
            if len(rows) != 1 or type(rows[0].get("N")) is not int:
                raise PermissionError("INTELLIGENCE_RAW_INSPECTION_UNAVAILABLE")
            present = rows[0]["N"] > 0
        if present:
            remaining += 1
            urgent += int(deadline <= now + timedelta(hours=24))
            overdue += int(deadline <= now)
    if inspection_snapshot().copies() != copies:
        raise PermissionError("INTELLIGENCE_RAW_PLAN_CHANGED")
    print(
        json.dumps(
            {
                "remaining_due_copies": remaining,
                "urgent_copies": urgent,
                "overdue_copies": overdue,
                "writes": False,
                "deletes": False,
            }
        )
    )
    if remaining:
        raise SystemExit(2)  # Includes the full 48-hour recovery window, not just lateness.


def identity(factory: Any, user: str, role: str) -> None:
    with factory() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()"
        )
        if cursor.fetchall() != [(user, role, DATABASE, WAREHOUSE)]:
            raise PermissionError("INTELLIGENCE_RAW_CLEANUP_IDENTITY_REQUIRED")


def gate_for(factory: Any, role: str) -> FeedRawRetention:
    return FeedRawRetention(
        SnowflakeRawLedger(factory, "PROD", expected_role=role),
        environment="PROD",
        source_lookup=lambda *_: {},
        policy_lookup=lambda _: "",  # cleanup reads lease/claims only
    )


def verify_current_inventory(
    gate: FeedRawRetention, plan: CleanupPlan, bucket: str, prefix: str
) -> None:
    object_delete = ObjectRawDelete(gate, object(), bucket=bucket, prefix=prefix)
    with gate.ledger.guard():
        current = plan_cleanup(
            gate,
            environment="PROD",
            source_ids=("cdc-eid-expedited",),
            now=plan.planned_at,
            scope=lambda copy: prod_cleanup_scope(copy, object_delete),
        )
    if current != plan:
        raise PermissionError("INTELLIGENCE_RAW_PLAN_CHANGED")


def approve(
    factory: Any, gate: FeedRawRetention, plan: CleanupPlan, ref: str, bucket: str, prefix: str
) -> None:
    if not TOKEN.fullmatch(ref) or len(ref) > 128:
        raise PermissionError("INTELLIGENCE_RAW_APPROVAL_REF_INVALID")
    identity(factory, APPROVER_USER, APPROVER_ROLE)
    verify_current_inventory(gate, plan, bucket, prefix)
    with factory() as connection, connection.cursor() as cursor:
        connection.autocommit(False)
        cursor.execute("BEGIN TRANSACTION")
        cursor.execute(
            "UPDATE GOVERNANCE.INTELLIGENCE_WRITE_GUARD "
            "SET write_sequence=write_sequence+1 WHERE guard_id=1"
        )
        if cursor.rowcount != 1:
            raise PermissionError("INTELLIGENCE_RAW_WRITE_GUARD_REQUIRED")
        cursor.execute(
            "SELECT PLAN_CANONICAL_JSON,APPROVAL_REF FROM "
            "GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_APPROVALS WHERE PLAN_SHA256=%s LIMIT 2",
            (plan.sha256,),
        )
        rows = cursor.fetchall()
        if rows:
            if rows != [(canonical_json(asdict(plan)), ref)]:
                raise PermissionError("INTELLIGENCE_RAW_PLAN_CHANGED")
        else:
            cursor.execute(
                "INSERT INTO GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_APPROVALS "
                "(PLAN_SHA256,PLAN_CANONICAL_JSON,APPROVED_BY,APPROVAL_REF) "
                "VALUES (%s,%s,CURRENT_USER(),%s)",
                (plan.sha256, canonical_json(asdict(plan)), ref),
            )
        connection.commit()


@contextmanager
def factory() -> Iterator[Any]:
    with connect(SnowflakeSettings()) as connection:
        yield connection


def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("deadline-check", "dry-run", "plan", "approve", "execute")
    )
    parser.add_argument("--plan-file", type=Path)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--approval-ref")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if args.action == "deadline-check":
        with pilot_watchdog(seconds=300):
            deadline_check()
        return
    if args.plan_file is None:
        parser.error("--plan-file is required for this action")
    if args.action == "dry-run":
        with pilot_watchdog(seconds=300):
            dry_run(args.plan_file)
        return
    if args.action != "plan" and (not args.confirm or not args.plan_sha256):
        raise PermissionError("INTELLIGENCE_RAW_EXPLICIT_CONFIRMATION_REQUIRED")
    if args.action == "approve" and not args.approval_ref:
        raise PermissionError("INTELLIGENCE_RAW_APPROVAL_REF_REQUIRED")
    os.environ["ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS"] = "10"
    with pilot_watchdog(seconds=300):
        settings = PipelineSettings()
        endpoint = urlsplit(settings.spaces_endpoint)
        if (
            settings.topx_env != "prod"
            or settings.snowflake_database != DATABASE
            or settings.spaces_bucket != "one-health-lyme-gap-atlas-data-prod"
            or settings.spaces_prefix != "prod"
            or settings.spaces_region != "sfo3"
            or endpoint.scheme != "https"
            or endpoint.hostname != "sfo3.digitaloceanspaces.com"
            or endpoint.path not in {"", "/"}
            or endpoint.query
            or endpoint.fragment
        ):
            raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")
        role = APPROVER_ROLE if args.action == "approve" else EXECUTOR_ROLE
        user = APPROVER_USER if args.action == "approve" else EXECUTOR_USER
        identity(factory, user, role)
        gate = gate_for(factory, role)
        if args.action == "plan":
            object_delete = ObjectRawDelete(
                gate,
                object(),
                bucket=settings.spaces_bucket,
                prefix=settings.spaces_prefix,
            )
            with gate.ledger.guard():
                plan = plan_cleanup(
                    gate,
                    environment="PROD",
                    source_ids=("cdc-eid-expedited",),
                    now=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    scope=lambda copy: prod_cleanup_scope(copy, object_delete),
                )
            descriptor = os.open(args.plan_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(canonical_json(asdict(plan)))
            print(json.dumps({"plan_sha256": plan.sha256, "copy_count": len(plan.copies)}))
            return
        plan = load_exact_plan(args.plan_file, args.plan_sha256, environment="PROD")
        if args.action == "approve":
            approve(
                factory,
                gate,
                plan,
                args.approval_ref,
                settings.spaces_bucket,
                settings.spaces_prefix,
            )
            print(json.dumps({"approved_plan_sha256": plan.sha256}))
            return
        if settings.spaces_access_key_id is None or settings.spaces_secret_access_key is None:
            raise PermissionError("INTELLIGENCE_RAW_OBJECT_DELETE_CREDENTIAL_REQUIRED")
        client = boto3.client(
            "s3",
            endpoint_url=settings.spaces_endpoint,
            region_name=settings.spaces_region,
            aws_access_key_id=settings.spaces_access_key_id.get_secret_value(),
            aws_secret_access_key=settings.spaces_secret_access_key.get_secret_value(),
        )
        receipts = execute_reviewed_prod_plan(
            gate,
            plan,
            factory=factory,
            spaces_client=client,
            bucket=settings.spaces_bucket,
            prefix=settings.spaces_prefix,
        )
        outcomes = {
            outcome: sum(r.outcome == outcome for r in receipts)
            for outcome in ("deleted", "already_absent", "failed")
        }
        print(json.dumps({"plan_sha256": plan.sha256, "outcomes": outcomes}))
        if outcomes["failed"]:
            raise SystemExit(2)


if __name__ == "__main__":
    run()
