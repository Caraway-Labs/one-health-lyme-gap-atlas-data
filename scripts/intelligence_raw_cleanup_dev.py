"""Bounded, exact-plan DEV EID raw expiry; never a feed acquisition command."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import boto3
from lyme_gap_atlas_shared.settings import SnowflakeSettings

from lyme_gap_atlas_data.ingestion.intelligence_runtime import pilot_watchdog
from lyme_gap_atlas_data.intelligence_items import TOKEN, canonical_json
from lyme_gap_atlas_data.intelligence_raw_cleanup import (
    ObjectRawDelete,
    dev_cleanup_scope,
    execute_reviewed_dev_plan,
    load_exact_plan,
)
from lyme_gap_atlas_data.intelligence_raw_runtime import FeedRawRetention, SnowflakeRawLedger
from lyme_gap_atlas_data.intelligence_retention import CleanupPlan, plan_cleanup
from lyme_gap_atlas_data.settings import PipelineSettings
from lyme_gap_atlas_data.sql_sessions import connect

DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
WAREHOUSE = "OH_LYME_DEV_INGEST_XS_WH"
EXECUTOR_USER = "OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP_SVC"
EXECUTOR_ROLE = "OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP"
APPROVER_USER = "OH_LYME_DEV_MIGRATION_DEPLOY_SVC"
APPROVER_ROLE = "OH_LYME_DEV_MIGRATION_DEPLOYER"


def identity(factory: Any, user: str, role: str) -> None:
    with factory() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()"
        )
        if cursor.fetchall() != [(user, role, DATABASE, WAREHOUSE)]:
            raise PermissionError("INTELLIGENCE_RAW_CLEANUP_IDENTITY_REQUIRED")


def gate_for(factory: Any, role: str) -> FeedRawRetention:
    return FeedRawRetention(
        SnowflakeRawLedger(factory, "DEV", expected_role=role),
        environment="DEV",
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
            environment="DEV",
            source_ids=("cdc-eid-expedited",),
            now=plan.planned_at,
            scope=lambda copy: dev_cleanup_scope(copy, object_delete),
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
    parser.add_argument("action", choices=("plan", "approve", "execute"))
    parser.add_argument("--plan-file", type=Path, required=True)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--approval-ref")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if args.action != "plan" and (not args.confirm or not args.plan_sha256):
        raise PermissionError("INTELLIGENCE_RAW_EXPLICIT_CONFIRMATION_REQUIRED")
    if args.action == "approve" and not args.approval_ref:
        raise PermissionError("INTELLIGENCE_RAW_APPROVAL_REF_REQUIRED")
    os.environ["ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS"] = "10"
    with pilot_watchdog(seconds=300):
        settings = PipelineSettings()
        endpoint = urlsplit(settings.spaces_endpoint)
        if (
            settings.topx_env != "dev"
            or settings.snowflake_database != DATABASE
            or settings.spaces_bucket != "one-health-lyme-gap-atlas-data-dev"
            or settings.spaces_prefix != "dev"
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
                    environment="DEV",
                    source_ids=("cdc-eid-expedited",),
                    now=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    scope=lambda copy: dev_cleanup_scope(copy, object_delete),
                )
            descriptor = os.open(args.plan_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(canonical_json(asdict(plan)))
            print(json.dumps({"plan_sha256": plan.sha256, "copy_count": len(plan.copies)}))
            return
        plan = load_exact_plan(args.plan_file, args.plan_sha256)
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
        receipts = execute_reviewed_dev_plan(
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
