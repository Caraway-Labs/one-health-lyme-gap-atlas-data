"""Set-oriented intelligence item persistence for bounded daily feed loads."""

from __future__ import annotations

from typing import Any

from .ingestion.bulk_stage import stage_json_rows
from .intelligence_items import canonical_json, identity_hash, revision_content
from .intelligence_storage import (
    CAPTURE_NATURAL_KEY,
    IntelligenceStorageError,
    WriteReceipt,
    capture_id,
)


def _stage_source(transport: str) -> str:
    return (
        f"SELECT $1:capture_id::VARCHAR AS capture_id,"
        f" $1:item_id::VARCHAR AS item_id,"
        f" $1:revision_id::VARCHAR AS revision_id,"
        f" $1:content_sha256::VARCHAR AS content_sha256,"
        f" PARSE_JSON($1:content_document_json::VARCHAR) AS content_document,"
        f" $1:item_sha256::VARCHAR AS item_sha256,"
        f" PARSE_JSON($1:item_document_json::VARCHAR) AS item_document,"
        f" $1:source_id::VARCHAR AS source_id,"
        f" $1:registry_version::NUMBER AS registry_version,"
        f" $1:transport::VARCHAR AS transport,"
        f" $1:ingestion_run_id::VARCHAR AS ingestion_run_id,"
        f" $1:artifact_id::VARCHAR AS artifact_id,"
        f" $1:artifact_sha256::VARCHAR AS artifact_sha256,"
        f" TO_TIMESTAMP_LTZ($1:retrieved_at::VARCHAR) AS retrieved_at"
        f" FROM {transport}"
    )


def _count_conflicts(
    cursor: Any,
    transport: str,
    *,
    relation: str,
    key_columns: tuple[str, ...],
    hash_column: str,
    error: str,
) -> None:
    join = " AND ".join(f"target.{column}=source.{column}" for column in key_columns)
    cursor.execute(
        f"""SELECT COUNT(*) FROM ({_stage_source(transport)}) source
        JOIN {relation} target ON {join}
        WHERE target.{hash_column}<>source.{hash_column}""",
    )
    row = cursor.fetchone()
    if row is None or int(row[0]) != 0:
        raise IntelligenceStorageError(error)


def _capture_change_sql(transport: str) -> str:
    """One aggregate over this run's staged rows and this source version's captures."""
    return f"""
        SELECT
          COUNT(*) AS items_seen,
          COALESCE(SUM(IFF(prior_item IS NULL, 1, 0)), 0) AS items_new,
          COALESCE(SUM(IFF(prior_item IS NOT NULL AND prior_revision IS NULL, 1, 0)), 0)
            AS items_changed,
          COALESCE(SUM(IFF(prior_revision IS NOT NULL, 1, 0)), 0) AS items_unchanged
        FROM (
          SELECT
            MAX(prior.item_id) AS prior_item,
            MAX(IFF(prior.revision_id = source.revision_id, prior.revision_id, NULL))
              AS prior_revision
          FROM ({_stage_source(transport)}) source
          LEFT JOIN GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES prior
            ON prior.source_id = source.source_id
           AND prior.registry_version = source.registry_version
           AND prior.transport = source.transport
           AND prior.item_id = source.item_id
           AND prior.source_id = %s
           AND prior.registry_version = %s
          WHERE source.source_id = %s
            AND source.registry_version = %s
          GROUP BY source.source_id, source.registry_version, source.transport,
                   source.item_id, source.revision_id
        ) classified
    """


def _capture_merge_sql(transport: str) -> str:
    """Insert a capture only when its natural key is absent for this source version."""
    match = " AND ".join(f"existing.{column}=source.{column}" for column in CAPTURE_NATURAL_KEY)
    return f"""
        MERGE INTO GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES target
        USING (
          SELECT source.*
          FROM ({_stage_source(transport)}) source
          WHERE source.source_id = %s
            AND source.registry_version = %s
            AND NOT EXISTS (
              SELECT 1
              FROM GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES existing
              WHERE {match}
                AND existing.source_id = %s
                AND existing.registry_version = %s
            )
        ) source
        ON target.capture_id = source.capture_id
        WHEN NOT MATCHED THEN INSERT
          (capture_id, item_id, revision_id, source_id, registry_version, transport,
           ingestion_run_id, artifact_id, artifact_sha256, item_sha256, item_document,
           retrieved_at)
          VALUES (source.capture_id, source.item_id, source.revision_id, source.source_id,
                  source.registry_version, source.transport, source.ingestion_run_id,
                  source.artifact_id, source.artifact_sha256, source.item_sha256,
                  source.item_document, source.retrieved_at)
    """


def _source_version_params(source_id: str, registry_version: int) -> tuple[Any, ...]:
    return (source_id, registry_version, source_id, registry_version)


def _require_capture_accounting(
    *,
    staged_count: int,
    captures_inserted: int,
    items_seen: int,
    items_new: int,
    items_changed: int,
    items_unchanged: int,
) -> None:
    if (
        items_seen != staged_count
        or items_new + items_changed + items_unchanged != items_seen
        or captures_inserted != items_new + items_changed
        or items_unchanged != staged_count - captures_inserted
        or min(items_seen, items_new, items_changed, items_unchanged, captures_inserted) < 0
    ):
        raise IntelligenceStorageError("INTELLIGENCE_CAPTURE_ACCOUNTING_MISMATCH")


def bulk_write_items(
    cursor: Any,
    *,
    run_id: str,
    source_id: str,
    registry_version: int,
    rows: list[dict[str, Any]],
) -> tuple[WriteReceipt, str | None]:
    """Persist validated intelligence rows with a bounded statement count.

    The capture change report is one extra aggregate SELECT per source-run.
    The insert anti-join stays inside the existing capture MERGE.
    """
    if not rows:
        return WriteReceipt(0, 0, 0, 0, 0, 0, 0), None
    staged: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    replays = 0
    for item in rows:
        key = capture_id(item)
        item_hash = identity_hash(item)
        if key in seen:
            if seen[key] != item_hash:
                raise IntelligenceStorageError("INTELLIGENCE_CAPTURE_REPLAY_CONFLICT")
            replays += 1
            continue
        seen[key] = item_hash
        content = revision_content(item)
        provenance = item["provenance"]
        staged.append(
            {
                "capture_id": key,
                "item_id": item["item_id"],
                "revision_id": item["revision_id"],
                "content_sha256": item["content_sha256"],
                "content_document_json": canonical_json(content),
                "item_sha256": item_hash,
                "item_document_json": canonical_json(item),
                "source_id": source_id,
                "registry_version": registry_version,
                "transport": item["transport"],
                "ingestion_run_id": run_id,
                "artifact_id": provenance["artifact_id"],
                "artifact_sha256": provenance["artifact_sha256"],
                "retrieved_at": item["fetched_at"],
            }
        )
    if not staged:
        return WriteReceipt(0, 0, replays, 0, 0, 0, 0), None
    transport = stage_json_rows(cursor, run_id=run_id, kind="intelligence-items", rows=staged)
    _count_conflicts(
        cursor,
        transport,
        relation="CONFORMED.INTELLIGENCE_ITEM_REVISIONS",
        key_columns=("item_id", "revision_id"),
        hash_column="content_sha256",
        error="INTELLIGENCE_REVISION_REPLAY_CONFLICT",
    )
    _count_conflicts(
        cursor,
        transport,
        relation="GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES",
        key_columns=("capture_id",),
        hash_column="item_sha256",
        error="INTELLIGENCE_CAPTURE_REPLAY_CONFLICT",
    )
    cursor.execute(
        f"""MERGE INTO CONFORMED.INTELLIGENCE_ITEM_REVISIONS target
        USING ({_stage_source(transport)}) source
        ON target.item_id=source.item_id AND target.revision_id=source.revision_id
        WHEN NOT MATCHED THEN INSERT
          (item_id, revision_id, content_sha256, content_document)
          VALUES (source.item_id, source.revision_id, source.content_sha256,
                  source.content_document)"""
    )
    revisions_inserted = cursor.rowcount or 0
    scope = _source_version_params(source_id, registry_version)
    cursor.execute(_capture_change_sql(transport), scope)
    counted = cursor.fetchone()
    if counted is None or len(counted) != 4:
        raise IntelligenceStorageError("INTELLIGENCE_CAPTURE_ACCOUNTING_MISMATCH")
    items_seen, items_new, items_changed, items_unchanged = (int(value) for value in counted)
    cursor.execute(_capture_merge_sql(transport), scope)
    captures_inserted = cursor.rowcount or 0
    _require_capture_accounting(
        staged_count=len(staged),
        captures_inserted=captures_inserted,
        items_seen=items_seen,
        items_new=items_new,
        items_changed=items_changed,
        items_unchanged=items_unchanged,
    )
    return (
        WriteReceipt(
            revisions_inserted,
            captures_inserted,
            replays + items_unchanged,
            items_seen,
            items_new,
            items_changed,
            items_unchanged,
        ),
        transport,
    )
