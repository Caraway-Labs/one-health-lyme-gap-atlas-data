"""Scoped cleanup drivers. No CLI, schedule, default approval or live execution."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from .intelligence_items import TOKEN, canonical_json, identity_hash
from .intelligence_raw_runtime import FeedRawRetention, SnowflakeRawLedger
from .intelligence_retention import (
    CleanupPlan,
    CleanupReceipt,
    CopyKind,
    RawCopy,
    canonical_object_uri,
    execute_cleanup,
)


class FileRawDelete:
    """Only raw checkpoint/replay files inside an explicitly owned root."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)

    def path(self, copy: RawCopy) -> Path:
        parsed = urlsplit(copy.locator)
        if (
            copy.kind not in {"local_checkpoint", "binary_replay", "artifact_member"}
            or parsed.scheme != "file"
            or parsed.netloc
            or parsed.query
            or parsed.fragment
        ):
            raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")
        path = Path(url2pathname(parsed.path))
        if (
            not path.is_absolute()
            or not path.resolve().is_relative_to(self.root)
            or path.resolve() == self.root
        ):
            raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")
        for parent in (path, *path.parents):
            if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
                raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")
            if parent == self.root:
                break
        suffix = {
            "local_checkpoint": r"[A-Za-z0-9_-]+\.payload\.json",
            "binary_replay": r"[A-Za-z0-9_-]+\.artifact\.bin",
            "artifact_member": r"[A-Za-z0-9_-]+\.member-[a-f0-9]{64}\.bin",
        }[copy.kind]
        if re.fullmatch(suffix + r"(?:\.raw-[a-f0-9]{32}\.tmp)?", path.name) is None:
            raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")
        return path

    def __call__(self, copy: RawCopy) -> bool:
        path = self.path(copy)
        if not path.exists():
            return False
        if not path.is_file():
            raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")
        path.unlink()
        return True


class ObjectRawDelete:
    """No bucket lifecycle rule; exact claimed feed object key only."""

    def __init__(self, gate: FeedRawRetention, client: Any, *, bucket: str, prefix: str) -> None:
        self.gate, self.client, self.bucket, self.prefix = gate, client, bucket, prefix.strip("/")
        if (
            not bucket
            or not self.prefix
            or any(part in {"", ".", ".."} for part in self.prefix.split("/"))
        ):
            raise ValueError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")

    def key(self, copy: RawCopy) -> str:
        if not canonical_object_uri(copy.locator):
            raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")
        parsed = urlsplit(copy.locator)
        lease = self.gate.lease(copy.lease_sha256)
        if (
            copy.kind != "raw_object"
            or parsed.scheme != "s3"
            or parsed.netloc != self.bucket
            or parsed.query
            or parsed.fragment
            or unquote(parsed.path) != parsed.path
        ):
            raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")
        key = parsed.path.lstrip("/")
        expected = f"{self.prefix}/{self.gate.environment.lower()}/{lease.source_id}/"
        remainder = key.removeprefix(expected).split("/")
        if (
            not key.startswith(expected)
            or len(remainder) != 2
            or not TOKEN.fullmatch(remainder[0])
            or remainder[1] != lease.artifact_sha256 + ".bin"
        ):
            raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")
        return key

    def __call__(self, copy: RawCopy) -> bool:
        key = self.key(copy)
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as error:
            response = getattr(error, "response", {})
            if response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        self.client.delete_object(Bucket=self.bucket, Key=key)
        return True


class WarehouseRawDelete:
    """Calls a reviewed owner-rights procedure; runtime never gets broad DELETE.

    Procedure/approval-table DDL and intended-role proof are release gates. The
    exact-plan callback below alone cannot substitute for warehouse approval.
    """

    def __init__(
        self, gate: FeedRawRetention, factory: Callable[[], Any], plan: CleanupPlan
    ) -> None:
        self.gate, self.factory, self.plan = gate, factory, plan

    def __call__(self, copy: RawCopy) -> bool:
        prefix = f"snowflake://ONE_HEALTH_LYME_GAP_ATLAS_{self.gate.environment}/GOVERNANCE/INGESTION_RUN_PAYLOADS/"
        run_id = copy.locator.removeprefix(prefix)
        if (
            copy.kind != "checkpoint_payload"
            or not copy.locator.startswith(prefix)
            or not TOKEN.fullmatch(run_id)
        ):
            raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")
        if isinstance(self.gate.ledger, SnowflakeRawLedger):
            return self.gate.ledger.purge_checkpoint(self.plan.sha256, run_id, copy.lease_sha256)
        with self.factory() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT CURRENT_ROLE(), CURRENT_DATABASE()")
            if cursor.fetchall() != [
                (
                    f"OH_LYME_{self.gate.environment}_RUNTIME",
                    f"ONE_HEALTH_LYME_GAP_ATLAS_{self.gate.environment}",
                )
            ]:
                raise PermissionError("INTELLIGENCE_RAW_WRITER_CONTEXT_REQUIRED")
            cursor.execute(
                "CALL GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(%s,%s,%s)",
                (self.plan.sha256, run_id, copy.lease_sha256),
            )
            rows = cursor.fetchall()
            if len(rows) != 1 or rows[0][0] not in {"deleted", "already_absent"}:
                raise PermissionError("INTELLIGENCE_RAW_DELETE_RESULT_INVALID")
            return bool(rows[0][0] == "deleted")


def approved_dev_plan(factory: Callable[[], Any], plan: CleanupPlan) -> bool:
    """Read one separately recorded approval under the dedicated DEV executor."""
    if plan.environment != "DEV" or len(plan.copies) > 1000:
        raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")
    with factory() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()"
        )
        if cursor.fetchall() != [
            (
                "OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP_SVC",
                "OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP",
                "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
                "OH_LYME_DEV_INGEST_XS_WH",
            )
        ]:
            raise PermissionError("INTELLIGENCE_RAW_CLEANUP_IDENTITY_REQUIRED")
        cursor.execute(
            "SELECT PLAN_CANONICAL_JSON,APPROVED_BY,APPROVAL_REF,APPROVED_AT "
            "FROM GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_APPROVALS "
            "WHERE PLAN_SHA256=%s LIMIT 2",
            (plan.sha256,),
        )
        rows = cursor.fetchall()
    if len(rows) != 1:
        return False
    document, approver, approval_ref, approved_at = rows[0]
    expected = canonical_json(asdict(plan))
    if (
        not isinstance(document, str)
        or document != expected
        or identity_hash(json.loads(document)) != plan.sha256
        or not isinstance(approver, str)
        or not approver
        or not isinstance(approval_ref, str)
        or not approval_ref
        or approved_at is None
    ):
        raise PermissionError("INTELLIGENCE_RAW_PLAN_CHANGED")
    return True


def load_exact_plan(path: Path, checksum: str) -> CleanupPlan:
    """Parse one private reviewed plan; no extra fields or targets are inferred."""
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise PermissionError("INTELLIGENCE_RAW_PLAN_INVALID")
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or set(document)
        != {"environment", "source_ids", "planned_at", "copies", "inventory_sha256"}
        or not isinstance(document["copies"], list)
        or len(document["copies"]) > 1000
    ):
        raise PermissionError("INTELLIGENCE_RAW_PLAN_INVALID")
    copies = tuple(RawCopy(**copy) for copy in document["copies"])
    plan = CleanupPlan(
        document["environment"],
        tuple(document["source_ids"]),
        document["planned_at"],
        copies,
        document["inventory_sha256"],
    )
    if (
        plan.environment != "DEV"
        or plan.source_ids != ("cdc-eid-expedited",)
        or checksum != plan.sha256
        or canonical_json(asdict(plan)) != path.read_text(encoding="utf-8")
    ):
        raise PermissionError("INTELLIGENCE_RAW_PLAN_CHANGED")
    return plan


def execute_reviewed_dev_plan(
    gate: FeedRawRetention,
    plan: CleanupPlan,
    *,
    factory: Callable[[], Any],
    spaces_client: Any,
    bucket: str,
    prefix: str,
) -> tuple[CleanupReceipt, ...]:
    """Only DEV's actual Snowflake, Spaces and owned process-buffer surfaces."""
    if (
        plan.environment != "DEV"
        or gate.environment != "DEV"
        or not isinstance(gate.ledger, SnowflakeRawLedger)
        or gate.ledger.expected_role != "OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP"
        or not plan.source_ids
        or set(plan.source_ids) != {"cdc-eid-expedited"}
        or len(plan.copies) > 1000
    ):
        raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")
    object_delete = ObjectRawDelete(gate, spaces_client, bucket=bucket, prefix=prefix)
    warehouse_delete = WarehouseRawDelete(gate, factory, plan)

    return cleanup(
        gate,
        plan,
        approved=lambda sha: sha == plan.sha256 and approved_dev_plan(factory, plan),
        scope=lambda copy: dev_cleanup_scope(copy, object_delete),
        delete={
            "raw_object": object_delete,
            "checkpoint_payload": warehouse_delete,
            "conditional_cache": gate.discard_buffer,
            "process_payload": gate.discard_buffer,
        },
    )


def dev_cleanup_scope(copy: RawCopy, object_delete: ObjectRawDelete) -> bool:
    """Allow only persistence surfaces composed by the DEV EID pilot."""
    if copy.environment != "DEV" or copy.source_id != "cdc-eid-expedited":
        return False
    if copy.kind == "raw_object":
        try:
            object_delete.key(copy)
        except PermissionError:
            return False
        return True
    if copy.kind == "checkpoint_payload":
        return copy.locator.startswith(
            "snowflake://ONE_HEALTH_LYME_GAP_ATLAS_DEV/GOVERNANCE/INGESTION_RUN_PAYLOADS/"
        ) and bool(TOKEN.fullmatch(copy.locator.rsplit("/", 1)[-1]))
    return copy.kind in {"conditional_cache", "process_payload"} and copy.locator.startswith(
        {"conditional_cache": "cache://", "process_payload": "process://"}[copy.kind]
    )


def cleanup(
    gate: FeedRawRetention,
    plan: CleanupPlan,
    *,
    approved: Callable[[str], bool] | None = None,
    scope: Callable[[RawCopy], bool],
    delete: Mapping[CopyKind, Callable[[RawCopy], bool]],
) -> tuple[CleanupReceipt, ...]:
    """Hold the same durable guard as claim registration and all raw I/O."""
    if gate.ledger.in_guard():
        raise PermissionError("INTELLIGENCE_RAW_CLEANUP_TRANSACTION_REQUIRED")
    if plan.environment != gate.environment:
        raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")
    warehouse = {
        copy.sha256
        for copy in plan.copies
        if isinstance(gate.ledger, SnowflakeRawLedger)
        and copy.kind == "checkpoint_payload"
        and copy.locator.startswith("snowflake://")
    }
    deferred: list[CleanupReceipt] = []

    def audit(receipt: CleanupReceipt) -> None:
        if receipt.copy_sha256 in warehouse and receipt.outcome != "pending":
            deferred.append(receipt)
            if receipt.outcome == "failed":
                raise PermissionError("INTELLIGENCE_RAW_WAREHOUSE_DELETE_ABORTED")
            return
        gate.ledger.append_audit(asdict(receipt))

    with gate.ledger.guard():
        receipts = execute_cleanup(
            plan, gate, now=gate.clock(), approved=approved, scope=scope, delete=delete, audit=audit
        )
    # Warehouse DELETE is durable only after the outer transaction commits.
    # Commit failure/uncertainty leaves independently committed pending intent.
    # Post-commit audit failure also leaves pending intent for safe readback/retry.
    for receipt in deferred:
        gate.ledger.append_audit(asdict(receipt))
    return receipts
