"""Active feed versions are registry JSON documents plus activation rows.

The protected register workflow is the only ongoing writer. It records one
idempotent MERGE. Callers must not keep a second source-to-hash dictionary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .intelligence_items import identity_hash

ACTIVATION_STATES = frozenset({"ACTIVE", "BLOCKED", "RETIRED"})
REGISTRY_DIR = Path(__file__).resolve().parents[2] / "config" / "intelligence"


@dataclass(frozen=True)
class Activation:
    source_id: str
    registry_version: int
    registry_sha256: str
    state: str
    decision_id: str


def load_registry_documents(directory: Path = REGISTRY_DIR) -> tuple[dict[str, Any], ...]:
    """Load checked-in source registry documents. No source list is hardcoded."""
    documents: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*-source-v*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("INTELLIGENCE_REGISTRY_DOCUMENT_INVALID")
        documents.append(document)
    return tuple(documents)


def activation_for_registration(
    source: dict[str, Any],
    *,
    superseded: tuple[dict[str, Any], ...] = (),
) -> tuple[Activation, ...]:
    """Admit the registry document being registered and block the versions it replaces."""
    if any(prior["source_id"] != source["source_id"] for prior in superseded):
        raise PermissionError("INTELLIGENCE_ACTIVATION_SOURCE_MISMATCH")
    if any(prior["registry_version"] >= source["registry_version"] for prior in superseded):
        raise PermissionError("INTELLIGENCE_ACTIVATION_VERSION_ORDER")
    return (_row(source, "ACTIVE"), *(_row(prior, "BLOCKED") for prior in superseded))


def activation_merge_statement(
    rows: tuple[Activation, ...] | list[Activation],
) -> tuple[str, tuple[Any, ...]]:
    """One idempotent MERGE. A matching row is left unchanged, including activated_at."""
    if not rows:
        raise PermissionError("INTELLIGENCE_ACTIVATION_REQUIRED")
    values = ", ".join("(%s, %s, %s, %s, %s)" for _ in rows)
    statement = f"""MERGE INTO GOVERNANCE.INTELLIGENCE_SOURCE_ACTIVATIONS target
USING (
    SELECT COLUMN1::VARCHAR AS source_id,
           COLUMN2::NUMBER AS registry_version,
           COLUMN3::VARCHAR AS registry_sha256,
           COLUMN4::VARCHAR AS state,
           COLUMN5::VARCHAR AS decision_id
    FROM VALUES {values}
) source
ON target.source_id = source.source_id
 AND target.registry_version = source.registry_version
WHEN MATCHED AND (
    target.registry_sha256 <> source.registry_sha256
    OR target.state <> source.state
    OR target.decision_id <> source.decision_id
) THEN UPDATE SET
    registry_sha256 = source.registry_sha256,
    state = source.state,
    decision_id = source.decision_id,
    activated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
    source_id, registry_version, registry_sha256, state, decision_id
) VALUES (
    source.source_id, source.registry_version, source.registry_sha256,
    source.state, source.decision_id
)"""
    params = tuple(
        item
        for row in rows
        for item in (
            row.source_id,
            row.registry_version,
            row.registry_sha256,
            row.state,
            row.decision_id,
        )
    )
    return statement, params


def fetch_activations(cursor: Any) -> tuple[Activation, ...]:
    """Read activation rows. This is a read, not a feed-view rewrite."""
    cursor.execute(
        "SELECT source_id, registry_version, registry_sha256, state, decision_id "
        "FROM GOVERNANCE.INTELLIGENCE_SOURCE_ACTIVATIONS"
    )
    found: list[Activation] = []
    for row in cursor.fetchall():
        state = str(row[3])
        if state not in ACTIVATION_STATES:
            raise PermissionError("INTELLIGENCE_ACTIVATION_STATE_INVALID")
        found.append(Activation(str(row[0]), int(row[1]), str(row[2]), state, str(row[4])))
    return tuple(found)


def source_is_active(
    source: dict[str, Any],
    documents: tuple[dict[str, Any], ...],
    activations: tuple[Activation, ...],
) -> bool:
    """True when the registry JSON and an ACTIVE row name the same version hash."""
    digest = identity_hash(source)
    recorded = any(
        document["source_id"] == source["source_id"]
        and document["registry_version"] == source["registry_version"]
        and identity_hash(document) == digest
        for document in documents
    )
    admitted = any(
        row.state == "ACTIVE"
        and row.source_id == source["source_id"]
        and row.registry_version == source["registry_version"]
        and row.registry_sha256 == digest
        for row in activations
    )
    return recorded and admitted


def _row(source: dict[str, Any], state: str) -> Activation:
    if state not in ACTIVATION_STATES:
        raise PermissionError("INTELLIGENCE_ACTIVATION_STATE_INVALID")
    decision_id = source["approval"]["decision_ref"]
    if not isinstance(decision_id, str) or not decision_id:
        raise PermissionError("INTELLIGENCE_ACTIVATION_DECISION_REQUIRED")
    return Activation(
        str(source["source_id"]),
        int(source["registry_version"]),
        identity_hash(source),
        state,
        decision_id,
    )
