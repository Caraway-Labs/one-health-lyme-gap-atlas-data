"""Deterministic source-row identity for governed tabular ingestion.

Publisher identifiers are preferred when the source supplies one. A canonical
content hash is the explicit fallback for sources that do not expose one; it is
deliberately not a fabricated business key.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

PUBLISHER_ID_FIELDS: tuple[str, ...] = (":id", "id")


@dataclass(frozen=True)
class IdentityAssessment:
    """Bounded identity observations for a source sample."""

    row_count: int
    publisher_id_fields: tuple[str, ...]
    publisher_id_count: int
    distinct_publisher_id_count: int
    duplicate_publisher_id_count: int
    duplicate_content_hash_count: int

    @property
    def publisher_identity_observed(self) -> bool:
        return self.publisher_id_count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_count": self.row_count,
            "publisher_id_fields": list(self.publisher_id_fields),
            "publisher_identity_observed": self.publisher_identity_observed,
            "publisher_id_count": self.publisher_id_count,
            "distinct_publisher_id_count": self.distinct_publisher_id_count,
            "duplicate_publisher_id_count": self.duplicate_publisher_id_count,
            "duplicate_content_hash_count": self.duplicate_content_hash_count,
        }


def canonical_source_row(row: Mapping[str, Any]) -> str:
    """Serialize a source row deterministically for hashing and comparison."""
    return json.dumps(dict(row), sort_keys=True, separators=(",", ":"), default=str)


def source_row_hash(row: Mapping[str, Any]) -> str:
    """Return the checksum of the source row, including publisher metadata."""
    return hashlib.sha256(canonical_source_row(row).encode("utf-8")).hexdigest()


def publisher_record_id(row: Mapping[str, Any]) -> str | None:
    """Return a non-empty publisher/system ID, if one is present."""
    for field_name in PUBLISHER_ID_FIELDS:
        value = row.get(field_name)
        if value not in (None, ""):
            return str(value)
    return None


def identity_strategy(row: Mapping[str, Any]) -> str:
    """Describe whether identity came from the publisher or content."""
    return "PUBLISHER_SYSTEM_ID" if publisher_record_id(row) is not None else "CANONICAL_ROW_HASH"


def deterministic_record_id(
    resource_key: str, definition_version: int, row: Mapping[str, Any]
) -> str:
    """Build the stable governed record ID without inventing a natural key."""
    source_identity = publisher_record_id(row) or source_row_hash(row)
    value = f"record:{resource_key}:{definition_version}:{source_identity}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def assess_identity(rows: Iterable[Mapping[str, Any]]) -> IdentityAssessment:
    """Summarize bounded identity and duplicate observations without raw rows."""
    materialized = list(rows)
    publisher_ids = [
        identifier
        for identifier in (publisher_record_id(row) for row in materialized)
        if identifier
    ]
    content_hashes = [source_row_hash(row) for row in materialized]
    fields = tuple(
        field_name
        for field_name in PUBLISHER_ID_FIELDS
        if any(row.get(field_name) not in (None, "") for row in materialized)
    )
    return IdentityAssessment(
        row_count=len(materialized),
        publisher_id_fields=fields,
        publisher_id_count=len(publisher_ids),
        distinct_publisher_id_count=len(set(publisher_ids)),
        duplicate_publisher_id_count=len(publisher_ids) - len(set(publisher_ids)),
        duplicate_content_hash_count=len(content_hashes) - len(set(content_hashes)),
    )
