"""Publication-grain Snowflake storage with immutable revisions and captures.

No source approval, migration execution, grant changes, or inferred tagging.
Factories must provide a fresh owned connection, never a shared caller transaction.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .intelligence_items import (
    IDENTITY_VERSION,
    canonical_json,
    canonical_timestamp,
    canonical_url,
    identity_hash,
    item_identities,
    permitted_text,
    validate_record,
)
from .settings import PipelineSettings


class IntelligenceStorageError(RuntimeError):
    """Only allowlisted diagnostics, never warehouse/private provider messages."""


@dataclass(frozen=True)
class WriteReceipt:
    revisions_inserted: int
    captures_inserted: int
    captures_replayed: int


def capture_id(item: dict[str, Any]) -> str:
    return identity_hash(
        {
            "run_id": item["provenance"]["run_id"],
            "artifact_id": item["provenance"]["artifact_id"],
            "source_id": item["source_id"],
            "registry_version": item["registry_version"],
            "transport": item["transport"],
            "item_id": item["item_id"],
            "revision_id": item["revision_id"],
        }
    )


def _one(cursor: Any, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    if len(rows) > 1:
        raise IntelligenceStorageError("INTELLIGENCE_DUPLICATE_LEDGER_KEY")
    return tuple(rows[0]) if rows else None


class IntelligenceStore:
    def __init__(
        self,
        *,
        connection_factory: Callable[[], Any],
        retention_allowed: Callable[[str], bool],
        settings: PipelineSettings | None = None,
    ) -> None:
        self.factory = connection_factory
        self.retention_allowed = retention_allowed
        self.settings = settings or PipelineSettings()

    def _context(self, cursor: Any) -> None:
        cursor.execute("SELECT CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_TRANSACTION()")
        rows = cursor.fetchall()
        expected = (
            f"OH_LYME_{self.settings.topx_env.upper()}_RUNTIME",
            self.settings.snowflake_database,
        )
        if len(rows) != 1 or tuple(rows[0][:2]) != expected or rows[0][2] is not None:
            raise PermissionError("INTELLIGENCE_WRITER_CONTEXT_REQUIRED")

    def _source(self, cursor: Any, source_id: str, version: int) -> dict[str, Any]:
        row = _one(
            cursor,
            """SELECT registry_sha256, TO_JSON(registry_document)
            FROM GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS s
            WHERE source_id=%s AND registry_version=%s
              AND NOT EXISTS (SELECT 1 FROM GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS newer
                  WHERE newer.source_id=s.source_id AND newer.registry_version>s.registry_version)
            LIMIT 2""",
            (source_id, version),
        )
        if row is None:
            raise PermissionError("INTELLIGENCE_CURRENT_SOURCE_REQUIRED")
        record = json.loads(row[1])
        validate_record("source", record)
        if (
            record["source_id"] != source_id
            or record["registry_version"] != version
            or row[0] != identity_hash(record)
        ):
            raise IntelligenceStorageError("INTELLIGENCE_REGISTRY_HASH_MISMATCH")
        if (
            record["state"] not in {"active", "manual"}
            or record["approval"]["status"] != "approved"
            or record["trust_review"]["status"] != "approved"
            or not self.retention_allowed(record["access_use"]["content_retention_policy_ref"])
        ):
            raise PermissionError("INTELLIGENCE_SOURCE_RIGHTS_REQUIRED")
        return dict(record)

    def lookup_source(self, source_id: str, version: int) -> dict[str, Any]:
        """Read-only authoritative lookup for a separately approved adapter composition."""
        with self.factory() as connection, connection.cursor() as cursor:
            self._context(cursor)
            return self._source(cursor, source_id, version)

    @staticmethod
    def _validate(item: dict[str, Any], source: dict[str, Any], run_id: str) -> None:
        validate_record("item", item)
        if (
            item["source_id"] != source["source_id"]
            or item["registry_version"] != source["registry_version"]
            or item["transport"] != source["transport"]
            or item["provenance"]["run_id"] != run_id
        ):
            raise IntelligenceStorageError("INTELLIGENCE_ITEM_CONTEXT_MISMATCH")
        if item["provenance"]["normalization_version"] != IDENTITY_VERSION:
            raise IntelligenceStorageError("INTELLIGENCE_NORMALIZATION_VERSION_UNSUPPORTED")
        item_id, content_hash, revision = item_identities(item)
        if (
            item["item_id"] != item_id
            or item["deduplication_key"] != item_id
            or item["content_sha256"] != content_hash
            or item["revision_id"] != revision
        ):
            raise IntelligenceStorageError("INTELLIGENCE_ITEM_HASH_MISMATCH")
        if canonical_url(item["canonical_url"]) != item["canonical_url"]:
            raise IntelligenceStorageError("INTELLIGENCE_URL_NOT_CANONICAL")
        for field in ("published_at", "updated_at", "event_at", "fetched_at"):
            if item[field] is not None and canonical_timestamp(item[field]) != item[field]:
                raise IntelligenceStorageError("INTELLIGENCE_TIMESTAMP_NOT_CANONICAL")
        rights = source["access_use"]
        excerpt = item["excerpt"]
        if excerpt is not None and (
            not rights["public_excerpt_permitted"]
            or permitted_text(excerpt, rights["excerpt_max_chars"]) != excerpt
        ):
            raise PermissionError("INTELLIGENCE_EXCERPT_NOT_PERMITTED")
        if permitted_text(item["title"], 1000) != item["title"]:
            raise IntelligenceStorageError("INTELLIGENCE_TITLE_NOT_SANITIZED")
        if any(tag["origin"] != "publisher" for tag in item["topics"] + item["geographies"]):
            raise PermissionError("INTELLIGENCE_INFERENCE_REVIEW_REQUIRED")

    def write(
        self,
        *,
        source_id: str,
        registry_version: int,
        resource_key: str,
        run_id: str,
        items: list[dict[str, Any]],
    ) -> WriteReceipt:
        # Freeze caller documents, bound the entire unit and reject malformed data
        # before opening a write transaction. One run/source is one atomic unit.
        serialized = canonical_json(items)
        if len(items) > 1000 or len(serialized.encode("utf-8")) > 10_000_000:
            raise IntelligenceStorageError("INTELLIGENCE_WRITE_LIMIT")
        frozen: list[dict[str, Any]] = json.loads(serialized)
        for item in frozen:
            validate_record("item", item)
        with self.factory() as connection, connection.cursor() as cursor:
            self._context(cursor)
            # Dedicated connection: no nested transaction or caller session changes.
            cursor.execute("ALTER SESSION SET LOCK_TIMEOUT=5, STATEMENT_TIMEOUT_IN_SECONDS=120")
            cursor.execute("BEGIN TRANSACTION")
            try:
                cursor.execute("""UPDATE GOVERNANCE.INTELLIGENCE_WRITE_GUARD
                    SET write_sequence=write_sequence+1 WHERE guard_id=1""")
                if cursor.rowcount != 1:
                    raise IntelligenceStorageError("INTELLIGENCE_WRITE_GUARD_INVALID")
                source = self._source(cursor, source_id, registry_version)
                run = _one(
                    cursor,
                    """SELECT resource_key FROM GOVERNANCE.INGESTION_RUNS
                    WHERE ingestion_run_id=%s LIMIT 2""",
                    (run_id,),
                )
                if run is None or run[0] != resource_key:
                    raise IntelligenceStorageError("INTELLIGENCE_RUN_REFERENCE_INVALID")
                revisions = captures = replays = 0
                seen: dict[str, str] = {}
                for item in frozen:
                    self._validate(item, source, run_id)
                    provenance = item["provenance"]
                    artifact = _one(
                        cursor,
                        """SELECT sha256 FROM GOVERNANCE.RAW_ARTIFACTS
                        WHERE artifact_id=%s AND ingestion_run_id=%s LIMIT 2""",
                        (provenance["artifact_id"], run_id),
                    )
                    if artifact is None or artifact[0] != provenance["artifact_sha256"]:
                        raise IntelligenceStorageError("INTELLIGENCE_ARTIFACT_REFERENCE_INVALID")
                    key = capture_id(item)
                    item_hash = identity_hash(item)
                    if key in seen:
                        if seen[key] != item_hash:
                            raise IntelligenceStorageError("INTELLIGENCE_CAPTURE_REPLAY_CONFLICT")
                        replays += 1
                        continue
                    seen[key] = item_hash
                    content = {
                        field: item[field]
                        for field in ("title", "excerpt", "published_at", "updated_at", "event_at")
                    }
                    row = _one(
                        cursor,
                        """SELECT content_sha256, TO_JSON(content_document)
                        FROM CONFORMED.INTELLIGENCE_ITEM_REVISIONS
                        WHERE item_id=%s AND revision_id=%s LIMIT 2""",
                        (item["item_id"], item["revision_id"]),
                    )
                    if row is None:
                        cursor.execute(
                            """INSERT INTO CONFORMED.INTELLIGENCE_ITEM_REVISIONS
                            (item_id,revision_id,content_sha256,content_document)
                            SELECT %s,%s,%s,PARSE_JSON(%s)""",
                            (
                                item["item_id"],
                                item["revision_id"],
                                item["content_sha256"],
                                canonical_json(content),
                            ),
                        )
                        revisions += 1
                    elif row[0] != item["content_sha256"] or json.loads(row[1]) != content:
                        raise IntelligenceStorageError("INTELLIGENCE_REVISION_REPLAY_CONFLICT")
                    row = _one(
                        cursor,
                        """SELECT item_sha256, TO_JSON(item_document)
                        FROM GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES
                        WHERE capture_id=%s LIMIT 2""",
                        (key,),
                    )
                    if row is None:
                        cursor.execute(
                            """INSERT INTO GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES
                            (capture_id,item_id,revision_id,source_id,registry_version,transport,
                             ingestion_run_id,artifact_id,artifact_sha256,item_sha256,
                             item_document,retrieved_at)
                            SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                   PARSE_JSON(%s),%s::TIMESTAMP_LTZ""",
                            (
                                key,
                                item["item_id"],
                                item["revision_id"],
                                source_id,
                                registry_version,
                                item["transport"],
                                run_id,
                                provenance["artifact_id"],
                                provenance["artifact_sha256"],
                                item_hash,
                                canonical_json(item),
                                item["fetched_at"],
                            ),
                        )
                        captures += 1
                    elif row[0] == item_hash and json.loads(row[1]) == item:
                        replays += 1
                    else:
                        raise IntelligenceStorageError("INTELLIGENCE_CAPTURE_REPLAY_CONFLICT")
                connection.commit()
                return WriteReceipt(revisions, captures, replays)
            except BaseException as error:
                connection.rollback()
                if isinstance(
                    error, (IntelligenceStorageError, PermissionError, KeyboardInterrupt)
                ):
                    raise
                raise IntelligenceStorageError("INTELLIGENCE_TRANSACTION_FAILED") from None
