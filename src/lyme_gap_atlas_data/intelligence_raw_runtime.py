"""Durable metadata-only raw leases, shared read/write guard and feed gates."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

from .intelligence_items import TOKEN, canonical_json, identity_hash, validate_acquisition_context
from .intelligence_retention import CopyKind, RawCopy, RawLease, capture_lease, require_read


def buffer_namespace(scheme: str) -> str:
    host = hashlib.sha256(socket.gethostname().encode()).hexdigest()[:16]
    return f"{scheme}://{host}-{os.getpid()}.{uuid4().hex}"


class DocumentLedger(Protocol):
    def guard(self) -> Any: ...
    def get(self, kind: str, key: str) -> dict[str, Any] | None: ...
    def put(self, kind: str, key: str, document: dict[str, Any]) -> None: ...
    def documents(self, kind: str) -> tuple[dict[str, Any], ...]: ...
    def append_audit(self, document: dict[str, Any]) -> None: ...
    def in_guard(self) -> bool: ...


class SQLiteRawLedger:
    """Local durable metadata only. BEGIN IMMEDIATE also serializes raw I/O.

    A guard remains held while raw bytes are read/written; cleanup must hold the
    same guard. A copy claim commits before I/O and survives an ambiguous failure.
    No XML or base64 enters this database. Paths are explicitly caller-owned.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.local = threading.local()
        self.audit_path = path.with_name(path.name + ".audit")
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=5)) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS documents (kind TEXT NOT NULL, key TEXT NOT NULL, "
                "checksum TEXT NOT NULL, document TEXT NOT NULL, PRIMARY KEY(kind,key))"
            )
            connection.commit()
        with closing(sqlite3.connect(self.audit_path, timeout=5)) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS events "
                "(checksum TEXT PRIMARY KEY, document TEXT NOT NULL)"
            )
            connection.commit()

    def append_audit(self, document: dict[str, Any]) -> None:
        # Independent committed journal: a raw-delete crash must not roll back
        # its pending intent along with the held claim/IO transaction.
        with closing(sqlite3.connect(self.audit_path, timeout=5)) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO events VALUES(?,?)",
                (identity_hash(document), canonical_json(document)),
            )
            connection.commit()

    def in_guard(self) -> bool:
        return getattr(self.local, "connection", None) is not None

    @contextmanager
    def guard(self) -> Iterator[None]:
        if getattr(self.local, "connection", None) is not None:
            yield
            return
        with closing(sqlite3.connect(self.path, timeout=5)) as connection:
            self.local.connection = connection
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                self.local.connection = None

    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        with self.guard():
            row = self.local.connection.execute(
                "SELECT checksum,document FROM documents WHERE kind=? AND key=?", (kind, key)
            ).fetchone()
            return _verified(row) if row else None

    def put(self, kind: str, key: str, document: dict[str, Any]) -> None:
        with self.guard():
            old = self.get(kind, key)
            if old is not None:
                if old != document:
                    raise PermissionError("INTELLIGENCE_RAW_LEDGER_CONFLICT")
                return
            self.local.connection.execute(
                "INSERT INTO documents VALUES(?,?,?,?)",
                (kind, key, identity_hash(document), canonical_json(document)),
            )

    def documents(self, kind: str) -> tuple[dict[str, Any], ...]:
        with self.guard():
            rows = self.local.connection.execute(
                "SELECT checksum,document FROM documents WHERE kind=? ORDER BY key LIMIT 100001",
                (kind,),
            ).fetchall()
            if len(rows) > 100000:
                raise PermissionError("INTELLIGENCE_RAW_LEDGER_LIMIT")
            return tuple(_verified(row) for row in rows)


def _verified(row: Any) -> dict[str, Any]:
    document = json.loads(row[1])
    if not isinstance(document, dict) or identity_hash(document) != row[0]:
        raise PermissionError("INTELLIGENCE_RAW_LEDGER_INVALID")
    return document


class SnowflakeRawLedger:
    """Private, append-only metadata table; same V135 write guard as storage.

    Schema/role rollout is intentionally not executed here. Exact runtime role
    and suffixed database are checked before SQL; no Alpha or owner connection.
    """

    def __init__(self, factory: Callable[[], Any], environment: Literal["DEV", "PROD"]) -> None:
        if environment not in {"DEV", "PROD"}:
            raise ValueError("INTELLIGENCE_RAW_ENVIRONMENT_INVALID")
        self.factory, self.environment = factory, environment
        self.local = threading.local()

    def in_guard(self) -> bool:
        return getattr(self.local, "cursor", None) is not None

    @contextmanager
    def guard(self) -> Iterator[None]:
        if getattr(self.local, "cursor", None) is not None:
            yield
            return
        with self.factory() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_TRANSACTION()")
            if cursor.fetchall() != [
                (
                    f"OH_LYME_{self.environment}_RUNTIME",
                    f"ONE_HEALTH_LYME_GAP_ATLAS_{self.environment}",
                    None,
                )
            ]:
                raise PermissionError("INTELLIGENCE_RAW_WRITER_CONTEXT_REQUIRED")
            connection.autocommit(False)
            cursor.execute("ALTER SESSION SET LOCK_TIMEOUT=5, STATEMENT_TIMEOUT_IN_SECONDS=120")
            cursor.execute("BEGIN TRANSACTION")
            cursor.execute(
                "UPDATE GOVERNANCE.INTELLIGENCE_WRITE_GUARD "
                "SET write_sequence=write_sequence+1 WHERE guard_id=1"
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise PermissionError("INTELLIGENCE_RAW_WRITE_GUARD_REQUIRED")
            self.local.cursor = cursor
            try:
                yield
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                self.local.cursor = None

    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        with self.guard():
            self.local.cursor.execute(
                "SELECT document_sha256,TO_JSON(document) "
                "FROM GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS "
                "WHERE document_type=%s AND document_key=%s LIMIT 2",
                (kind, key),
            )
            rows = self.local.cursor.fetchall()
            if len(rows) > 1:
                raise PermissionError("INTELLIGENCE_RAW_LEDGER_INVALID")
            return _verified(rows[0]) if rows else None

    def put(self, kind: str, key: str, document: dict[str, Any]) -> None:
        with self.guard():
            old = self.get(kind, key)
            if old is not None:
                if old != document:
                    raise PermissionError("INTELLIGENCE_RAW_LEDGER_CONFLICT")
                return
            self.local.cursor.execute(
                "INSERT INTO GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS"
                "(document_type,document_key,document_sha256,document) "
                "SELECT %s,%s,%s,PARSE_JSON(%s)",
                (kind, key, identity_hash(document), canonical_json(document)),
            )

    def documents(self, kind: str) -> tuple[dict[str, Any], ...]:
        with self.guard():
            self.local.cursor.execute(
                "SELECT document_sha256,TO_JSON(document) "
                "FROM GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS "
                "WHERE document_type=%s ORDER BY document_key LIMIT 100001",
                (kind,),
            )
            rows = self.local.cursor.fetchall()
            if len(rows) > 100000:
                raise PermissionError("INTELLIGENCE_RAW_LEDGER_LIMIT")
            return tuple(_verified(row) for row in rows)

    def append_audit(self, document: dict[str, Any]) -> None:
        # Separate append-only table/transaction; no attempt to acquire the
        # claim guard already held by the outer connection.
        with self.factory() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_TRANSACTION()")
            if cursor.fetchall() != [
                (
                    f"OH_LYME_{self.environment}_RUNTIME",
                    f"ONE_HEALTH_LYME_GAP_ATLAS_{self.environment}",
                    None,
                )
            ]:
                raise PermissionError("INTELLIGENCE_RAW_WRITER_CONTEXT_REQUIRED")
            cursor.execute(
                "INSERT INTO GOVERNANCE.INTELLIGENCE_RAW_RETENTION_AUDIT"
                "(receipt_sha256,document) SELECT %s,PARSE_JSON(%s)",
                (identity_hash(document), canonical_json(document)),
            )
            connection.commit()

    def purge_checkpoint(self, plan_sha256: str, run_id: str, lease_sha256: str) -> bool:
        with self.guard():
            self.local.cursor.execute(
                "CALL GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(%s,%s,%s)",
                (plan_sha256, run_id, lease_sha256),
            )
            rows = self.local.cursor.fetchall()
            if len(rows) != 1 or rows[0][0] not in {"deleted", "already_absent"}:
                raise PermissionError("INTELLIGENCE_RAW_DELETE_RESULT_INVALID")
            return bool(rows[0][0] == "deleted")


class FeedRawRetention:
    def __init__(
        self,
        ledger: DocumentLedger,
        *,
        environment: Literal["DEV", "PROD"],
        source_lookup: Callable[[str, int], dict[str, Any]],
        policy_lookup: Callable[[dict[str, Any]], str],
        clock: Callable[[], str] = lambda: datetime.now(UTC).isoformat(),
        allow_fixture: bool = False,
    ) -> None:
        if environment not in {"DEV", "PROD"} or (environment == "PROD" and allow_fixture):
            raise ValueError("INTELLIGENCE_RAW_ENVIRONMENT_INVALID")
        if isinstance(ledger, SnowflakeRawLedger) and ledger.environment != environment:
            raise ValueError("INTELLIGENCE_RAW_ENVIRONMENT_INVALID")
        if environment == "PROD" and not isinstance(ledger, SnowflakeRawLedger):
            raise ValueError("INTELLIGENCE_RAW_SHARED_LEDGER_REQUIRED")
        self.ledger, self.environment = ledger, environment
        self.source_lookup, self.policy_lookup, self.clock = source_lookup, policy_lookup, clock
        self.allow_fixture = allow_fixture
        self.buffers: dict[str, Callable[[], bool]] = {}

    def register_buffer(self, locator: str, discard: Callable[[], bool]) -> None:
        if len(self.buffers) >= 100000 and locator not in self.buffers:
            raise PermissionError("INTELLIGENCE_RAW_LEDGER_LIMIT")
        self.buffers[locator] = discard

    def discard_buffer(self, copy: RawCopy) -> bool:
        if self.ledger.get("buffer_release", copy.sha256) is not None:
            return False
        discard = self.buffers.get(copy.locator)
        if discard is not None:
            existed = discard()
            self.ledger.put("buffer_release", copy.sha256, {"released_at": self.clock()})
            return existed
        # Do not call os.kill(pid,0) on Windows: it may terminate a process.
        from urllib.parse import urlsplit

        parts = urlsplit(copy.locator)
        if parts.scheme not in {"memory", "process", "cache"}:
            raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID")
        try:
            host, pid_text = parts.netloc.split(".", 1)[0].split("-", 1)
            if host != hashlib.sha256(socket.gethostname().encode()).hexdigest()[:16]:
                raise PermissionError("INTELLIGENCE_RAW_BUFFER_OWNER_REQUIRED")
            pid = int(pid_text)
        except ValueError:
            raise PermissionError("INTELLIGENCE_RAW_DELETE_SCOPE_INVALID") from None
        if pid <= 0 or pid == os.getpid():
            raise PermissionError("INTELLIGENCE_RAW_BUFFER_OWNER_REQUIRED")
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x1000, False, pid)
            if handle:
                kernel.CloseHandle(handle)
                raise PermissionError("INTELLIGENCE_RAW_BUFFER_OWNER_REQUIRED")
            if ctypes.get_last_error() != 87:  # nonexistent PID only, not denied access
                raise PermissionError("INTELLIGENCE_RAW_BUFFER_OWNER_REQUIRED")
        else:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return False
            except PermissionError:
                raise PermissionError("INTELLIGENCE_RAW_BUFFER_OWNER_REQUIRED") from None
            raise PermissionError("INTELLIGENCE_RAW_BUFFER_OWNER_REQUIRED")
        return False

    def release_buffer(self, locator: str) -> None:
        # Release only this controller's managed buffers, then commit metadata
        # proof so a later worker can distinguish released from unknown owners.
        if locator not in self.buffers:
            return
        self.buffers[locator]()
        with self.ledger.guard():
            for copy in self.copies():
                if (
                    copy.locator == locator
                    and self.ledger.get("buffer_release", copy.sha256) is None
                ):
                    self.ledger.put("buffer_release", copy.sha256, {"released_at": self.clock()})

    def close(self) -> None:
        for locator in tuple(self.buffers):
            self.release_buffer(locator)

    def __enter__(self) -> FeedRawRetention:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def lease(self, sha256: str) -> RawLease:
        document = self.ledger.get("lease", sha256)
        if document is None:
            raise PermissionError("INTELLIGENCE_RAW_LEASE_REQUIRED")
        lease = RawLease(**document)
        if lease.sha256 != sha256:
            raise PermissionError("INTELLIGENCE_RAW_LEDGER_INVALID")
        return lease

    def copies(self) -> tuple[RawCopy, ...]:
        return tuple(RawCopy(**document) for document in self.ledger.documents("copy"))

    def claims(self, copy: RawCopy) -> tuple[RawCopy, ...]:
        return tuple(claim for claim in self.copies() if claim.physical_key == copy.physical_key)

    def _permitted(self, lease: RawLease) -> bool:
        source = self.source_lookup(lease.source_id, lease.registry_version)
        return (
            identity_hash(source) == lease.source_sha256
            and self.policy_lookup(source) == lease.policy_ref
        )

    def require_lease(self, sha256: str) -> RawLease:
        lease = self.lease(sha256)
        # No bytes are loaded to establish expiry/authority.
        from .intelligence_retention import _time

        if _time(self.clock()) < _time(lease.captured_at) or _time(self.clock()) >= _time(
            lease.expires_at
        ):
            raise PermissionError("INTELLIGENCE_RAW_EXPIRED")
        if not self._permitted(lease):
            raise PermissionError("INTELLIGENCE_RAW_RIGHTS_REQUIRED")
        return lease

    def capture(
        self, source: dict[str, Any], context: dict[str, Any], *, previous: str | None = None
    ) -> str:
        validate_acquisition_context(
            source,
            source["source_id"],
            source["fetch_location"],
            context,
            allow_fixture=self.allow_fixture,
        )
        if self.source_lookup(source["source_id"], source["registry_version"]) != source:
            raise PermissionError("INTELLIGENCE_RAW_RIGHTS_REQUIRED")
        with self.ledger.guard():
            if context["fetch_status"] == 304:
                if previous is None:
                    raise PermissionError("INTELLIGENCE_RAW_LEASE_REQUIRED")
                lease = self.require_lease(previous)
                if (
                    lease.source_sha256 != identity_hash(source)
                    or lease.artifact_sha256 != context["artifact_sha256"]
                ):
                    raise PermissionError("INTELLIGENCE_RAW_CAPTURE_MISMATCH")
                self.ledger.put(
                    "validation", identity_hash(context), {"lease_sha256": lease.sha256}
                )
                return lease.sha256
            if context["fetch_status"] != 200 or previous is not None:
                raise PermissionError("INTELLIGENCE_RAW_CAPTURE_MISMATCH")
            policy_ref = self.policy_lookup(source)
            lease = capture_lease(
                source_id=source["source_id"],
                registry_version=source["registry_version"],
                source_sha256=identity_hash(source),
                capture_id=context["attempt_id"],
                artifact_sha256=context["artifact_sha256"],
                captured_at=context["fetched_at"],
                policy_ref=policy_ref,
                permitted=lambda *args: True,
            )
            self.ledger.put("lease", lease.sha256, asdict(lease))
            self.ledger.put("capture", lease.sha256, context)
            self.ledger.put("validation", identity_hash(context), {"lease_sha256": lease.sha256})
            self.require_lease(lease.sha256)
            return lease.sha256

    def bind(self, run_id: str, payload: Any) -> None:
        if not TOKEN.fullmatch(run_id):
            raise PermissionError("INTELLIGENCE_RAW_CAPTURE_MISMATCH")
        with self.ledger.guard():
            lease = self.verify_payload(payload)
            key = identity_hash({"run_id": run_id, "context": payload["source_context"]})
            existing = self.ledger.get("run", key)
            if existing is not None:
                if (
                    existing["lease_sha256"] != lease.sha256
                    or self.require_run(run_id).sha256 != lease.sha256
                ):
                    raise PermissionError("INTELLIGENCE_RAW_CAPTURE_MISMATCH")
                return
            bindings = [doc for doc in self.ledger.documents("run") if doc["run_id"] == run_id]
            self.ledger.put(
                "run",
                key,
                {
                    "run_id": run_id,
                    "generation": len(bindings) + 1,
                    "lease_sha256": lease.sha256,
                    "context_sha256": identity_hash(payload["source_context"]),
                },
            )

    def verify_payload(self, payload: Any) -> RawLease:
        if not isinstance(payload, dict):
            raise PermissionError("INTELLIGENCE_RAW_CAPTURE_MISMATCH")
        with self.ledger.guard():
            lease = self.require_lease(payload.get("raw_lease_sha256", ""))
            context = payload.get("source_context")
            if not isinstance(context, dict):
                raise PermissionError("INTELLIGENCE_RAW_CAPTURE_MISMATCH")
            source = self.source_lookup(lease.source_id, lease.registry_version)
            validate_acquisition_context(
                source,
                lease.source_id,
                source["fetch_location"],
                context,
                allow_fixture=self.allow_fixture,
            )
            if (
                context["artifact_sha256"] != lease.artifact_sha256
                or payload.get("artifact_sha256") != lease.artifact_sha256
                or context["fetched_at"] != payload.get("fetched_at")
            ):
                raise PermissionError("INTELLIGENCE_RAW_CAPTURE_MISMATCH")
            if self.ledger.get("validation", identity_hash(context)) != {
                "lease_sha256": lease.sha256
            }:
                raise PermissionError("INTELLIGENCE_RAW_CAPTURE_MISMATCH")
            return lease

    def require_run(self, run_id: str) -> RawLease:
        bindings = [doc for doc in self.ledger.documents("run") if doc["run_id"] == run_id]
        if not bindings:
            raise PermissionError("INTELLIGENCE_RAW_LEASE_REQUIRED")
        document = max(bindings, key=lambda doc: doc["generation"])
        if sum(doc["generation"] == document["generation"] for doc in bindings) != 1:
            raise PermissionError("INTELLIGENCE_RAW_LEDGER_INVALID")
        return self.require_lease(document["lease_sha256"])

    @contextmanager
    def copy_access(
        self, run_id: str, kind: CopyKind, locator: str, *, write: bool = False
    ) -> Iterator[None]:
        lease = self.require_run(run_id)
        with self.lease_access(lease.sha256, kind, locator, write=write):
            yield

    @contextmanager
    def lease_access(
        self, sha256: str, kind: CopyKind, locator: str, *, write: bool = False
    ) -> Iterator[None]:
        if write:
            if self.ledger.in_guard():
                raise PermissionError("INTELLIGENCE_RAW_IO_NESTING_INVALID")
            with self.ledger.guard():
                lease = self.require_lease(sha256)
                copy = RawCopy(self.environment, lease.source_id, kind, locator, sha256)
                if self.ledger.get("buffer_release", copy.sha256) is not None:
                    raise PermissionError("INTELLIGENCE_RAW_BUFFER_RELEASED")
                self.ledger.put("copy", copy.sha256, asdict(copy))
            # Claim is durably committed BEFORE physical I/O. Cleanup sees the
            # unexpired claim even between transactions; expiry is rechecked
            # under the I/O guard. Ambiguous provider failures retain the claim.
        with self.ledger.guard():
            lease = self.require_lease(sha256)
            copy = RawCopy(self.environment, lease.source_id, kind, locator, sha256)
            require_read(copy, self, now=self.clock(), permitted=self._permitted)
            yield
