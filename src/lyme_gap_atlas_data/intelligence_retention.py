"""Feed-only raw-copy leases and exact-plan cleanup, with no runtime activation.

The authoritative ledger must register every copy before its write and serialize
claim/read/delete operations. Neither payload timestamps nor YAML can authorize
retention or deletion. Concrete warehouse/object adapters remain deployment work.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from urllib.parse import unquote, urlsplit

from .intelligence_items import TOKEN, canonical_timestamp, identity_hash

POLICY_VERSION = "intelligence-raw-30d-v1"
CopyKind = Literal[
    "raw_object",
    "checkpoint_payload",
    "local_checkpoint",
    "conditional_cache",
    "binary_replay",
    "artifact_member",
    "process_payload",
]
KINDS = frozenset(
    {
        "raw_object",
        "checkpoint_payload",
        "local_checkpoint",
        "conditional_cache",
        "binary_replay",
        "artifact_member",
        "process_payload",
    }
)


def canonical_object_uri(value: str) -> bool:
    """Canonical Atlas S3 locator: no alternate spelling of one physical key."""
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return bool(
        value.startswith("s3://")
        and parts.netloc
        and parts.hostname == parts.netloc
        and parts.netloc == parts.netloc.lower()
        and not parts.netloc.endswith(".")
        and parts.path.startswith("/")
        and all(part not in {"", ".", ".."} for part in parts.path[1:].split("/"))
        and unquote(parts.path) == parts.path
        and not parts.query
        and not parts.fragment
    )


def _time(value: str) -> datetime:
    canonical = canonical_timestamp(value)
    if "." in canonical and len(canonical.split(".")[1][:-1]) > 6:
        raise ValueError("INTELLIGENCE_RAW_CLOCK_PRECISION_INVALID")
    return datetime.fromisoformat(canonical.replace("Z", "+00:00"))


@dataclass(frozen=True)
class RawLease:
    """Immutable initial successful capture; a 304/retry reuses this exact lease."""

    source_id: str
    registry_version: int
    source_sha256: str
    capture_id: str
    artifact_sha256: str
    captured_at: str
    expires_at: str
    policy_ref: str
    policy_version: str = POLICY_VERSION

    def validate(self) -> None:
        for value in (self.source_id, self.capture_id, self.policy_ref):
            if not TOKEN.fullmatch(value):
                raise ValueError("INTELLIGENCE_RAW_LEASE_INVALID")
        for value in (self.source_sha256, self.artifact_sha256):
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("INTELLIGENCE_RAW_LEASE_INVALID")
        if (
            type(self.registry_version) is not int
            or self.registry_version < 1
            or self.policy_version != POLICY_VERSION
        ):
            raise ValueError("INTELLIGENCE_RAW_LEASE_INVALID")
        if _time(self.expires_at) != _time(self.captured_at) + timedelta(days=30):
            raise ValueError("INTELLIGENCE_RAW_LEASE_INVALID")

    @property
    def sha256(self) -> str:
        self.validate()
        return identity_hash(asdict(self))


def capture_lease(
    *,
    source_id: str,
    registry_version: int,
    source_sha256: str,
    capture_id: str,
    artifact_sha256: str,
    captured_at: str,
    policy_ref: str,
    permitted: Callable[[str, int, str, str], bool],
) -> RawLease:
    if not permitted(source_id, registry_version, source_sha256, policy_ref):
        raise PermissionError("INTELLIGENCE_RAW_RIGHTS_REQUIRED")
    start = canonical_timestamp(captured_at)
    expires = (_time(start) + timedelta(days=30)).astimezone(UTC).isoformat().replace("+00:00", "Z")
    lease = RawLease(
        source_id,
        registry_version,
        source_sha256,
        capture_id,
        artifact_sha256,
        start,
        expires,
        policy_ref,
    )
    lease.validate()
    return lease


@dataclass(frozen=True)
class RawCopy:
    """Opaque locator stays private; only hash identifiers belong in receipts."""

    environment: Literal["DEV", "PROD"]
    source_id: str
    kind: CopyKind
    locator: str
    lease_sha256: str

    def validate(self) -> None:
        try:
            scheme = urlsplit(self.locator).scheme
        except ValueError:
            raise ValueError("INTELLIGENCE_RAW_COPY_INVALID") from None
        if scheme == "s3" and not canonical_object_uri(self.locator):
            raise ValueError("INTELLIGENCE_RAW_COPY_INVALID")
        if (
            self.environment not in {"DEV", "PROD"}
            or self.kind not in KINDS
            or not self.locator
            or len(self.locator) > 2048
            or any(ord(c) < 32 for c in self.locator)
        ):
            raise ValueError("INTELLIGENCE_RAW_COPY_INVALID")
        if (
            not TOKEN.fullmatch(self.source_id)
            or len(self.lease_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.lease_sha256)
        ):
            raise ValueError("INTELLIGENCE_RAW_COPY_INVALID")

    @property
    def sha256(self) -> str:
        self.validate()
        return identity_hash(asdict(self))

    @property
    def physical_key(self) -> tuple[str, str]:
        # Locator includes its backend namespace. Logical copy roles can alias
        # the same bytes: a replay member must protect a raw object's live claim.
        return self.environment, self.locator


class RawLedger(Protocol):
    """Implementations must resolve immutable leases independently of raw bytes."""

    def lease(self, sha256: str) -> RawLease: ...
    def claims(self, copy: RawCopy) -> tuple[RawCopy, ...]: ...
    def copies(self) -> tuple[RawCopy, ...]: ...


def require_read(
    copy: RawCopy, ledger: RawLedger, *, now: str, permitted: Callable[[RawLease], bool]
) -> RawLease:
    """Must run before loading XML/base64, including every resume fallback."""
    copy.validate()
    lease = ledger.lease(copy.lease_sha256)
    if (
        lease.sha256 != copy.lease_sha256
        or lease.source_id != copy.source_id
        or copy not in ledger.claims(copy)
    ):
        raise PermissionError("INTELLIGENCE_RAW_CLAIM_REQUIRED")
    instant = _time(now)
    if instant < _time(lease.captured_at) or instant >= _time(lease.expires_at):
        raise PermissionError("INTELLIGENCE_RAW_EXPIRED")
    if not permitted(lease):
        raise PermissionError("INTELLIGENCE_RAW_RIGHTS_REQUIRED")
    return lease


@dataclass(frozen=True)
class CleanupPlan:
    environment: Literal["DEV", "PROD"]
    source_ids: tuple[str, ...]
    planned_at: str
    copies: tuple[RawCopy, ...]
    inventory_sha256: str

    @property
    def sha256(self) -> str:
        return identity_hash(asdict(self))


def plan_cleanup(
    ledger: RawLedger,
    *,
    environment: Literal["DEV", "PROD"],
    source_ids: tuple[str, ...],
    now: str,
    scope: Callable[[RawCopy], bool],
) -> CleanupPlan:
    if (
        environment not in {"DEV", "PROD"}
        or not source_ids
        or len(set(source_ids)) != len(source_ids)
        or any(not TOKEN.fullmatch(s) for s in source_ids)
    ):
        raise ValueError("INTELLIGENCE_RAW_SCOPE_INVALID")
    instant = _time(now)
    inventory = tuple(sorted(ledger.copies(), key=lambda copy: copy.sha256))
    selected: dict[tuple[str, str], RawCopy] = {}
    for copy in inventory:
        copy.validate()
        if copy.environment != environment or copy.source_id not in source_ids:
            continue
        claims = ledger.claims(copy)
        if copy not in claims:
            raise PermissionError("INTELLIGENCE_RAW_CLAIM_REQUIRED")
        expired = True
        for claim in claims:
            lease = ledger.lease(claim.lease_sha256)
            if (
                claim.physical_key != copy.physical_key
                or lease.sha256 != claim.lease_sha256
                or lease.source_id != claim.source_id
            ):
                raise PermissionError("INTELLIGENCE_RAW_CLAIM_REQUIRED")
            # A shared physical copy is protected by every live claim, including
            # claims from another source outside this exact cleanup scope.
            if instant < _time(lease.expires_at):
                expired = False
        if expired:
            if any(not scope(claim) or claim.source_id not in source_ids for claim in claims):
                raise PermissionError("INTELLIGENCE_RAW_SCOPE_INVALID")
            selected[copy.physical_key] = copy
    return CleanupPlan(
        environment,
        tuple(sorted(source_ids)),
        canonical_timestamp(now),
        tuple(sorted(selected.values(), key=lambda copy: copy.sha256)),
        identity_hash([asdict(copy) for copy in inventory]),
    )


@dataclass(frozen=True)
class CleanupReceipt:
    plan_sha256: str
    copy_sha256: str
    outcome: Literal["pending", "deleted", "already_absent", "failed"]
    attempted_at: str


def execute_cleanup(
    plan: CleanupPlan,
    ledger: RawLedger,
    *,
    now: str,
    approved: Callable[[str], bool] | None,
    scope: Callable[[RawCopy], bool],
    delete: Mapping[CopyKind, Callable[[RawCopy], bool]],
    audit: Callable[[CleanupReceipt], None],
) -> tuple[CleanupReceipt, ...]:
    """Exact-plan approval required; caller holds a ledger lock throughout.

    Audit intent is durable before each deletion, then outcome is appended. A
    retry must use the same exact plan; delete callbacks are idempotent. Failure
    receipts contain no raw contents, private locator, or provider exception.
    """
    if approved is None or not approved(plan.sha256):
        raise PermissionError("INTELLIGENCE_RAW_DELETE_APPROVAL_REQUIRED")
    if _time(now) < _time(plan.planned_at):
        raise PermissionError("INTELLIGENCE_RAW_PLAN_INVALID")
    current = plan_cleanup(
        ledger,
        environment=plan.environment,
        source_ids=plan.source_ids,
        now=plan.planned_at,
        scope=scope,
    )
    if current != plan:
        raise PermissionError("INTELLIGENCE_RAW_PLAN_CHANGED")
    receipts = []
    for copy in plan.copies:
        # Preflight all drivers before the first physical mutation.
        if copy.kind not in delete:
            raise PermissionError("INTELLIGENCE_RAW_DELETE_DRIVER_REQUIRED")
    for copy in plan.copies:
        intent = CleanupReceipt(plan.sha256, copy.sha256, "pending", canonical_timestamp(now))
        audit(intent)
        try:
            existed = delete[copy.kind](copy)
            if type(existed) is not bool:
                raise ValueError("INTELLIGENCE_RAW_DELETE_RESULT_INVALID")
        except Exception:
            failure = CleanupReceipt(plan.sha256, copy.sha256, "failed", canonical_timestamp(now))
            audit(failure)
            receipts.append(failure)
            continue
        receipt = CleanupReceipt(
            plan.sha256,
            copy.sha256,
            "deleted" if existed else "already_absent",
            canonical_timestamp(now),
        )
        audit(receipt)
        receipts.append(receipt)
    return tuple(receipts)
