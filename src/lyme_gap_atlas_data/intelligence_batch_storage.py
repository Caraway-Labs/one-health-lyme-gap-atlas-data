"""Bounded SQL batches inside IntelligenceStore's existing guarded transaction.

No commit, source admission, schema or grants here. The caller freezes and bounds
the entire capture first and commits only after every batch succeeds.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from .intelligence_items import (
    canonical_json,
    identity_hash,
    revision_content,
    validate_acquisition_context,
)
from .intelligence_metadata import verify_native_item
from .intelligence_storage import IntelligenceStorageError, WriteReceipt, _one, capture_id

if TYPE_CHECKING:
    from .intelligence_storage import IntelligenceStore


def document_batches(documents: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    """Reuse the existing 250-row / 900,000-byte logical transport envelope."""
    batch: list[dict[str, Any]] = []
    size = 2
    for document in documents:
        encoded = len(canonical_json(document).encode("utf-8"))
        if encoded + 2 > 900_000:
            raise IntelligenceStorageError("INTELLIGENCE_WRITE_LIMIT")
        if batch and (len(batch) == 250 or size + encoded + 1 > 900_000):
            yield batch
            batch, size = [], 2
        size += encoded + (1 if batch else 0)
        batch.append(document)
    if batch:
        yield batch


def _reference(
    store: IntelligenceStore,
    cursor: Any,
    source: dict[str, Any],
    resource_key: str,
    run_id: str,
    item: dict[str, Any],
) -> None:
    provenance = item["provenance"]
    artifact_id = provenance["artifact_id"]
    artifact = _one(
        cursor,
        "SELECT sha256 FROM GOVERNANCE.RAW_ARTIFACTS "
        "WHERE artifact_id=%s AND ingestion_run_id=%s LIMIT 2",
        (artifact_id, run_id),
    )
    if artifact is None or artifact[0] != provenance["artifact_sha256"]:
        raise IntelligenceStorageError("INTELLIGENCE_ARTIFACT_REFERENCE_INVALID")
    receipt = store._context_receipt(cursor, run_id, artifact_id)
    if receipt is None:
        raise IntelligenceStorageError("INTELLIGENCE_ACQUISITION_REFERENCE_INVALID")
    context = json.loads(receipt[1])
    try:
        validate_acquisition_context(source, resource_key, source["fetch_location"], context)
    except ValueError:
        raise IntelligenceStorageError("INTELLIGENCE_ACQUISITION_REFERENCE_INVALID") from None
    if (
        receipt[0] != identity_hash(context)
        or context["artifact_sha256"] != provenance["artifact_sha256"]
        or context["fetched_at"] != item["fetched_at"]
    ):
        raise IntelligenceStorageError("INTELLIGENCE_ACQUISITION_REFERENCE_INVALID")
    store._references(cursor, resource_key, run_id, artifact_id, context)


def write_complete_batches(
    store: IntelligenceStore,
    cursor: Any,
    source: dict[str, Any],
    resource_key: str,
    run_id: str,
    items: list[dict[str, Any]],
) -> WriteReceipt:
    revisions: dict[tuple[str, str], dict[str, Any]] = {}
    captures: dict[str, dict[str, Any]] = {}
    checked_references: set[tuple[str, str, str]] = set()
    replays = 0
    for item in items:
        store._validate(item, source, run_id)
        if item["contract_version"] == "2.0.0":
            if store.native_policy_lookup is None:
                raise PermissionError("INTELLIGENCE_NATIVE_RIGHTS_REQUIRED")
            verify_native_item(
                item,
                store.native_policy_lookup(source["source_id"], source["registry_version"]),
                source,
            )
        provenance = item["provenance"]
        reference = (provenance["artifact_id"], provenance["artifact_sha256"], item["fetched_at"])
        if reference not in checked_references:
            _reference(store, cursor, source, resource_key, run_id, item)
            checked_references.add(reference)
        revision = {
            "item_id": item["item_id"],
            "revision_id": item["revision_id"],
            "content_sha256": item["content_sha256"],
            "content_document": revision_content(item),
        }
        revision_key = (item["item_id"], item["revision_id"])
        if revision_key in revisions and revisions[revision_key] != revision:
            raise IntelligenceStorageError("INTELLIGENCE_REVISION_REPLAY_CONFLICT")
        revisions[revision_key] = revision
        key = capture_id(item)
        capture = {
            "capture_id": key,
            "item_id": item["item_id"],
            "revision_id": item["revision_id"],
            "source_id": source["source_id"],
            "registry_version": source["registry_version"],
            "transport": item["transport"],
            "ingestion_run_id": run_id,
            "artifact_id": provenance["artifact_id"],
            "artifact_sha256": provenance["artifact_sha256"],
            "item_sha256": identity_hash(item),
            "item_document": item,
            "retrieved_at": item["fetched_at"],
        }
        if key in captures:
            if captures[key] != capture:
                raise IntelligenceStorageError("INTELLIGENCE_CAPTURE_REPLAY_CONFLICT")
            replays += 1
        captures[key] = capture

    revision_count = capture_count = 0
    for batch in document_batches(list(revisions.values())):
        params = tuple(value for row in batch for value in (row["item_id"], row["revision_id"]))
        cursor.execute(
            "SELECT item_id,revision_id,content_sha256,TO_JSON(content_document) "
            "FROM CONFORMED.INTELLIGENCE_ITEM_REVISIONS WHERE (item_id,revision_id) IN ("
            + ",".join("(%s,%s)" for _ in batch)
            + f") LIMIT {len(batch) + 1}",
            params,
        )
        existing: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        for row in cursor.fetchall():
            key_pair = (row[0], row[1])
            if key_pair in existing:
                raise IntelligenceStorageError("INTELLIGENCE_DUPLICATE_LEDGER_KEY")
            existing[key_pair] = (row[2], json.loads(row[3]))
        pending = []
        for document in batch:
            previous = existing.get((document["item_id"], document["revision_id"]))
            if previous is None:
                pending.append(document)
            elif previous != (document["content_sha256"], document["content_document"]):
                raise IntelligenceStorageError("INTELLIGENCE_REVISION_REPLAY_CONFLICT")
        if pending:
            cursor.execute(
                "INSERT INTO CONFORMED.INTELLIGENCE_ITEM_REVISIONS "
                "(item_id,revision_id,content_sha256,content_document) "
                "SELECT value:item_id::VARCHAR,value:revision_id::VARCHAR,"
                "value:content_sha256::VARCHAR,value:content_document "
                "FROM TABLE(FLATTEN(INPUT=>PARSE_JSON(%s)))",
                (canonical_json(pending),),
            )
            if cursor.rowcount != len(pending):
                raise IntelligenceStorageError("INTELLIGENCE_WRITE_COUNT_MISMATCH")
            revision_count += len(pending)

    for batch in document_batches(list(captures.values())):
        cursor.execute(
            "SELECT capture_id,item_sha256,TO_JSON(item_document) "
            "FROM GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES WHERE capture_id IN ("
            + ",".join("%s" for _ in batch)
            + f") LIMIT {len(batch) + 1}",
            tuple(row["capture_id"] for row in batch),
        )
        previous_captures: dict[str, tuple[str, dict[str, Any]]] = {}
        for row in cursor.fetchall():
            if row[0] in previous_captures:
                raise IntelligenceStorageError("INTELLIGENCE_DUPLICATE_LEDGER_KEY")
            previous_captures[row[0]] = (row[1], json.loads(row[2]))
        pending = []
        for document in batch:
            previous = previous_captures.get(document["capture_id"])
            if previous is None:
                pending.append(document)
            elif previous == (document["item_sha256"], document["item_document"]):
                replays += 1
            else:
                raise IntelligenceStorageError("INTELLIGENCE_CAPTURE_REPLAY_CONFLICT")
        if pending:
            cursor.execute(
                "INSERT INTO GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES "
                "(capture_id,item_id,revision_id,source_id,registry_version,transport,"
                "ingestion_run_id,artifact_id,artifact_sha256,item_sha256,"
                "item_document,retrieved_at) "
                "SELECT value:capture_id::VARCHAR,value:item_id::VARCHAR,"
                "value:revision_id::VARCHAR,"
                "value:source_id::VARCHAR,value:registry_version::NUMBER,value:transport::VARCHAR,"
                "value:ingestion_run_id::VARCHAR,value:artifact_id::VARCHAR,value:artifact_sha256::VARCHAR,"
                "value:item_sha256::VARCHAR,value:item_document,value:retrieved_at::TIMESTAMP_LTZ "
                "FROM TABLE(FLATTEN(INPUT=>PARSE_JSON(%s)))",
                (canonical_json(pending),),
            )
            if cursor.rowcount != len(pending):
                raise IntelligenceStorageError("INTELLIGENCE_WRITE_COUNT_MISMATCH")
            capture_count += len(pending)
    return WriteReceipt(revision_count, capture_count, replays)
