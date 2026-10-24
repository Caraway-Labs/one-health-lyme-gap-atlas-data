"""Set-oriented intelligence item persistence for bounded daily feed loads."""

from __future__ import annotations

from typing import Any

from .ingestion.bulk_stage import stage_json_rows
from .intelligence_items import canonical_json, identity_hash, revision_content


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
    from .intelligence_storage import IntelligenceStorageError

    join = " AND ".join(f"target.{column}=source.{column}" for column in key_columns)
    cursor.execute(
        f"""SELECT COUNT(*) FROM ({_stage_source(transport)}) source
        JOIN {relation} target ON {join}
        WHERE target.{hash_column}<>source.{hash_column}""",
    )
    row = cursor.fetchone()
    if row is None or int(row[0]) != 0:
        raise IntelligenceStorageError(error)


def bulk_write_items(
    cursor: Any,
    *,
    run_id: str,
    source_id: str,
    registry_version: int,
    rows: list[dict[str, Any]],
) -> tuple[Any, str | None]:
    """Persist validated intelligence rows with a bounded statement count."""
    from .intelligence_storage import IntelligenceStorageError, WriteReceipt, capture_id

    if not rows:
        return WriteReceipt(0, 0, 0), None
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
        return WriteReceipt(0, 0, replays), None
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
    cursor.execute(
        f"""MERGE INTO GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES target
        USING ({_stage_source(transport)}) source
        ON target.capture_id=source.capture_id
        WHEN NOT MATCHED THEN INSERT
          (capture_id, item_id, revision_id, source_id, registry_version, transport,
           ingestion_run_id, artifact_id, artifact_sha256, item_sha256, item_document,
           retrieved_at)
          VALUES (source.capture_id, source.item_id, source.revision_id, source.source_id,
                  source.registry_version, source.transport, source.ingestion_run_id,
                  source.artifact_id, source.artifact_sha256, source.item_sha256,
                  source.item_document, source.retrieved_at)"""
    )
    captures_inserted = cursor.rowcount or 0
    capture_replays = len(staged) - captures_inserted
    return WriteReceipt(revisions_inserted, captures_inserted, replays + capture_replays), transport
