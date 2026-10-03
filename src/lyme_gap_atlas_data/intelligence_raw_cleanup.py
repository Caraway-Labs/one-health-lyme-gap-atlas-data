"""Scoped cleanup drivers. No CLI, schedule, default approval or live execution."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from .intelligence_items import TOKEN
from .intelligence_raw_runtime import FeedRawRetention, SnowflakeRawLedger
from .intelligence_retention import CleanupPlan, CleanupReceipt, CopyKind, RawCopy, execute_cleanup


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


def cleanup(
    gate: FeedRawRetention,
    plan: CleanupPlan,
    *,
    approved: Callable[[str], bool] | None = None,
    scope: Callable[[RawCopy], bool],
    delete: Mapping[CopyKind, Callable[[RawCopy], bool]],
) -> tuple[CleanupReceipt, ...]:
    """Hold the same durable guard as claim registration and all raw I/O."""
    if plan.environment != gate.environment:
        raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")

    def audit(receipt: CleanupReceipt) -> None:
        document = asdict(receipt)
        gate.ledger.append_audit(document)

    with gate.ledger.guard():
        return execute_cleanup(
            plan, gate, now=gate.clock(), approved=approved, scope=scope, delete=delete, audit=audit
        )
