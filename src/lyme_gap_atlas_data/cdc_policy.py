"""Pure CDC snapshot and retry decisions shared by governed runtime commands."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo


def snapshot_checksum(row_hashes: Iterable[str]) -> str:
    """Hash a multiset: order independent but duplicate sensitive and versioned."""
    hashes = list(row_hashes)
    if not hashes or any(re.fullmatch(r"[0-9a-fA-F]{64}", item) is None for item in hashes):
        raise ValueError("A snapshot requires nonempty SHA-256 row hashes")
    payload = "cdc-snapshot-v1\n" + "\n".join(sorted(item.lower() for item in hashes))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def metadata_fingerprint(metadata: Mapping[str, Any], *, dataset_id: str = "x5j9-wybp") -> str:
    """Use publisher change markers and schema, excluding popularity counters."""
    if dataset_id not in {"x5j9-wybp", "qtbi-xd4i"} or metadata.get("id") != dataset_id:
        raise ValueError("Unexpected CDC metadata identity")
    if not metadata.get("rowsUpdatedAt") or not metadata.get("columns"):
        raise ValueError("CDC metadata lacks update or schema evidence")
    columns = sorted(
        (
            {key: column.get(key) for key in ("fieldName", "dataTypeName")}
            for column in metadata["columns"]
        ),
        key=lambda column: str(column["fieldName"]),
    )
    evidence = {
        "id": metadata["id"],
        "rowsUpdatedAt": metadata["rowsUpdatedAt"],
        "columns": columns,
    }
    return hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()


def transient_source_error(error: Exception) -> bool:
    """Never retry permanent HTTP responses or source parse/schema errors."""
    if isinstance(error, HTTPError):
        return error.code in {408, 429, 500, 502, 503, 504}
    return isinstance(error, (URLError, TimeoutError, ConnectionError))


def publication_decision(
    *,
    current_revision: int,
    expected_revision: int,
    current_checksum: str | None,
    candidate_checksum: str,
    failed_checks: int,
    check_count: int,
) -> str:
    """Fail closed on incomplete validation or a stale publication attempt."""
    if current_revision != expected_revision:
        raise ValueError("Publication changed while candidate was being validated")
    if failed_checks != 0 or check_count != 8:
        raise ValueError("Publication requires all eight passing quality checks")
    return "UNCHANGED" if current_checksum == candidate_checksum else "PUBLISH"


def overdue_metadata_period(now: datetime, last_success: datetime | None) -> str | None:
    """Monthly 09:00 Mountain checks have seven days of grace, including DST."""
    if now.tzinfo is None or (last_success is not None and last_success.tzinfo is None):
        raise ValueError("Monitoring timestamps must be timezone-aware")
    local = now.astimezone(ZoneInfo("America/Denver"))
    due = local.replace(day=1, hour=9, minute=0, second=0, microsecond=0)
    if local <= due + timedelta(days=7):
        due = (due - timedelta(days=1)).replace(day=1)
    if last_success is not None and last_success >= due:
        return None
    return due.strftime("%Y-%m")
