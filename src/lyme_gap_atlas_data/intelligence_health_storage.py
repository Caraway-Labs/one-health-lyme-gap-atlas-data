"""Private durable health history; no schedule, alert sender or activation.

Checkpoint evidence and registry/context authority are explicit dependencies.
Only finite health metadata and revision/attempt hashes enter this journal.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Literal, Protocol

from .ingestion.types import RunState, Stage, StageStatus
from .intelligence_health import (
    AcquisitionFailure,
    HealthHistory,
    HealthResult,
    health_from_run,
    record_health,
    reduce_health,
)
from .intelligence_items import canonical_json, identity_hash, validate_record

Transform = Callable[[HealthHistory | None], HealthResult]


def _encode(history: HealthHistory) -> dict[str, Any]:
    document = asdict(history)
    document["seen_revisions"] = sorted(history.seen_revisions)
    document["processed_attempts"] = [list(pair) for pair in history.processed_attempts]
    return document


def _decode(document: Any, checksum: str) -> HealthHistory:
    if isinstance(document, str):
        document = json.loads(document)
    if not isinstance(document, dict) or identity_hash(document) != checksum:
        raise ValueError("INTELLIGENCE_HEALTH_JOURNAL_INVALID")
    history = dict(document)
    validate_record("health", history["document"])
    history["seen_revisions"] = frozenset(history["seen_revisions"])
    history["processed_attempts"] = tuple(tuple(pair) for pair in history["processed_attempts"])
    barrier = history["acquisition_failure"]
    history["acquisition_failure"] = AcquisitionFailure(**barrier) if barrier else None
    return HealthHistory(**history)


class HealthJournal(Protocol):
    def transact(self, source_id: str, version: int, transform: Transform) -> HealthResult: ...


class HealthCheckpoints(Protocol):
    def load(self, run_id: str) -> RunState | None: ...
    def load_normalized(self, run_id: str) -> list[dict[str, Any]] | None: ...


class SnowflakeAcquisitionContext:
    """Read the existing immutable structured receipt, without loading XML."""

    def __init__(self, factory: Callable[[], Any], environment: Literal["DEV", "PROD"]) -> None:
        if environment not in {"DEV", "PROD"}:
            raise ValueError("INTELLIGENCE_HEALTH_ENVIRONMENT_INVALID")
        self.factory, self.environment = factory, environment

    def __call__(self, state: RunState) -> dict[str, Any] | None:
        acquire = state.checkpoint(Stage.ACQUIRE)
        if acquire is None or acquire.artifact_id is None:
            return None
        with self.factory() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_TRANSACTION()")
            if cursor.fetchall() != [
                (
                    f"OH_LYME_{self.environment}_RUNTIME",
                    f"ONE_HEALTH_LYME_GAP_ATLAS_{self.environment}",
                    None,
                )
            ]:
                raise PermissionError("INTELLIGENCE_HEALTH_WRITER_CONTEXT_REQUIRED")
            cursor.execute("ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=15")
            cursor.execute(
                "SELECT context_sha256,TO_JSON(context_document) "
                "FROM GOVERNANCE.INTELLIGENCE_ACQUISITION_CONTEXTS "
                "WHERE ingestion_run_id=%s AND artifact_id=%s LIMIT 2",
                (state.ingestion_run_id, acquire.artifact_id),
            )
            rows = cursor.fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise ValueError("INTELLIGENCE_HEALTH_CAPTURE_MISMATCH")
        document = json.loads(rows[0][1])
        if not isinstance(document, dict) or identity_hash(document) != rows[0][0]:
            raise ValueError("INTELLIGENCE_HEALTH_CAPTURE_MISMATCH")
        return document


class SQLiteHealthJournal:
    """Caller-owned local history with serialized read/reduce/append and restart."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=5)) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS health_events ("
                "sequence INTEGER PRIMARY KEY, source_id TEXT NOT NULL, version INTEGER NOT NULL, "
                "checksum TEXT NOT NULL, history TEXT NOT NULL)"
            )
            connection.commit()

    def transact(self, source_id: str, version: int, transform: Transform) -> HealthResult:
        with closing(sqlite3.connect(self.path, timeout=5)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT history,checksum FROM health_events WHERE source_id=? AND version=? "
                    "ORDER BY sequence DESC LIMIT 1",
                    (source_id, version),
                ).fetchone()
                previous = _decode(*row) if row else None
                result = transform(previous)
                document = _encode(result.history)
                checksum = identity_hash(document)
                if not row or checksum != row[1]:
                    connection.execute(
                        "INSERT INTO health_events(source_id,version,checksum,history) "
                        "VALUES(?,?,?,?)",
                        (source_id, version, checksum, canonical_json(document)),
                    )
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise


class SnowflakeHealthJournal:
    """Proposed private history table; exact runtime role and V135 guard.

    DDL and intended-role DEV proof remain parent-coordinated release gates.
    """

    def __init__(self, factory: Callable[[], Any], environment: Literal["DEV", "PROD"]) -> None:
        if environment not in {"DEV", "PROD"}:
            raise ValueError("INTELLIGENCE_HEALTH_ENVIRONMENT_INVALID")
        self.factory, self.environment = factory, environment

    def transact(self, source_id: str, version: int, transform: Transform) -> HealthResult:
        with self.factory() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_TRANSACTION()")
            if cursor.fetchall() != [
                (
                    f"OH_LYME_{self.environment}_RUNTIME",
                    f"ONE_HEALTH_LYME_GAP_ATLAS_{self.environment}",
                    None,
                )
            ]:
                raise PermissionError("INTELLIGENCE_HEALTH_WRITER_CONTEXT_REQUIRED")
            connection.autocommit(False)
            cursor.execute("ALTER SESSION SET LOCK_TIMEOUT=5, STATEMENT_TIMEOUT_IN_SECONDS=120")
            cursor.execute("BEGIN TRANSACTION")
            try:
                cursor.execute(
                    "UPDATE GOVERNANCE.INTELLIGENCE_WRITE_GUARD "
                    "SET write_sequence=write_sequence+1 WHERE guard_id=1"
                )
                if cursor.rowcount != 1:
                    raise PermissionError("INTELLIGENCE_HEALTH_WRITE_GUARD_REQUIRED")
                cursor.execute(
                    "SELECT TO_JSON(history),history_sha256,generation "
                    "FROM GOVERNANCE.INTELLIGENCE_SOURCE_HEALTH_HISTORY "
                    "WHERE source_id=%s AND registry_version=%s "
                    "ORDER BY generation DESC LIMIT 2",
                    (source_id, version),
                )
                rows = cursor.fetchall()
                if len(rows) == 2 and rows[0][2] == rows[1][2]:
                    raise ValueError("INTELLIGENCE_HEALTH_JOURNAL_INVALID")
                previous = _decode(rows[0][0], rows[0][1]) if rows else None
                result = transform(previous)
                document = _encode(result.history)
                checksum = identity_hash(document)
                if not rows or checksum != rows[0][1]:
                    cursor.execute(
                        "INSERT INTO GOVERNANCE.INTELLIGENCE_SOURCE_HEALTH_HISTORY "
                        "(source_id,registry_version,generation,history_sha256,history) "
                        "SELECT %s,%s,%s,%s,PARSE_JSON(%s)",
                        (
                            source_id,
                            version,
                            int(rows[0][2]) + 1 if rows else 1,
                            checksum,
                            canonical_json(document),
                        ),
                    )
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise


class IntelligenceHealthPersistence:
    """Records durable terminal checkpoints; operational state without alert policy."""

    def __init__(
        self,
        journal: HealthJournal,
        *,
        source_lookup: Callable[[str, int], dict[str, Any]],
        context_lookup: Callable[[RunState], dict[str, Any] | None],
        run_binding_lookup: Callable[[str], dict[str, Any] | None] | None = None,
        environment: Literal["DEV", "PROD"] = "DEV",
    ) -> None:
        if environment not in {"DEV", "PROD"}:
            raise ValueError("INTELLIGENCE_HEALTH_ENVIRONMENT_INVALID")
        if isinstance(journal, SnowflakeHealthJournal) and journal.environment != environment:
            raise ValueError("INTELLIGENCE_HEALTH_ENVIRONMENT_INVALID")
        if environment == "PROD" and not isinstance(journal, SnowflakeHealthJournal):
            raise ValueError("INTELLIGENCE_HEALTH_SHARED_JOURNAL_REQUIRED")
        self.journal, self.source_lookup, self.context_lookup = (
            journal,
            source_lookup,
            context_lookup,
        )
        self.run_binding_lookup = run_binding_lookup

    def _source(self, source: dict[str, Any]) -> dict[str, Any]:
        validate_record("source", source)
        if self.source_lookup(source["source_id"], source["registry_version"]) != source:
            raise PermissionError("INTELLIGENCE_HEALTH_SOURCE_AUTHORITY_REQUIRED")
        return source

    def record_checkpoint(
        self,
        source: dict[str, Any],
        checkpoints: HealthCheckpoints,
        run_id: str,
        *,
        observed_at: str,
        emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> HealthResult:
        source = self._source(source)
        state = checkpoints.load(run_id)
        if state is None or state.ingestion_run_id != run_id:
            raise ValueError("INTELLIGENCE_HEALTH_TERMINAL_EVIDENCE_REQUIRED")
        # Independent structured acquisition receipt, never raw payload/XML.
        context = self.context_lookup(state)
        records = checkpoints.load_normalized(run_id) or []
        binding = self.run_binding_lookup(run_id) if self.run_binding_lookup else None
        load = state.checkpoint(Stage.LOAD)
        accepted = bool(load and load.status is StageStatus.COMPLETED and context is not None)
        if binding is None and not accepted:
            raise PermissionError("INTELLIGENCE_HEALTH_RUN_BINDING_REQUIRED")
        if binding is not None:
            expected = {
                "source_id": source["source_id"],
                "registry_version": source["registry_version"],
                "source_sha256": identity_hash(source),
                "parser_version": binding.get("parser_version"),
                "fetch_version": "pinned-https-v1",
            }
            if binding != expected or binding.get("parser_version") not in {
                "rss-atom-v1",
                "rss-atom-native-v2",
            }:
                raise PermissionError("INTELLIGENCE_HEALTH_RUN_BINDING_MISMATCH")

        def transform(previous: HealthHistory | None) -> HealthResult:
            result = health_from_run(
                source,
                state,
                observed_at=observed_at,
                source_context=context,
                items=tuple(records),
                previous=previous,
                policy=None,
            )
            if binding is not None:
                if (
                    accepted
                    and records
                    and any(
                        item["provenance"]["parser_version"] != binding["parser_version"]
                        or item["provenance"]["fetch_version"] != binding["fetch_version"]
                        for item in records
                    )
                ):
                    raise PermissionError("INTELLIGENCE_HEALTH_RUN_BINDING_MISMATCH")
                document = dict(result.history.document)
                document["parser_version"] = binding["parser_version"]
                document["fetch_version"] = binding["fetch_version"]
                validate_record("health", document)
                result = replace(result, history=replace(result.history, document=document))
            return result

        result = self.journal.transact(
            source["source_id"],
            source["registry_version"],
            transform,
        )
        if emit is not None:
            record_health(result, emit)
        return result

    def observe(self, source: dict[str, Any], *, observed_at: str) -> HealthResult:
        source = self._source(source)
        return self.journal.transact(
            source["source_id"],
            source["registry_version"],
            lambda previous: reduce_health(
                source, previous=previous, observed_at=observed_at, policy=None
            ),
        )
