"""Bounded, immutable transport files for set-oriented Snowflake persistence.

These files are transport copies, not the governed source artifacts. Their names
include the content digest so a retry cannot silently replace different bytes.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_STAGE = "GOVERNANCE.INGESTION_BULK_STAGE"
_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")
_TRANSPORT_REF = re.compile(
    rf"^@{re.escape(_STAGE)}/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/"
    r"[A-Za-z0-9_-]+-[a-f0-9]{64}\.json\.gz$"
)


def stage_json_rows(cursor: Any, *, run_id: str, kind: str, rows: Iterable[dict[str, Any]]) -> str:
    """Upload one bounded JSON-lines file and return its exact stage reference."""
    if not _SAFE.fullmatch(run_id) or not _SAFE.fullmatch(kind):
        raise ValueError("Unsafe bulk transport identity")
    with tempfile.TemporaryDirectory(prefix="atlas-bulk-") as directory:
        content = b"".join(
            json.dumps(row, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
            + b"\n"
            for row in rows
        )
        if not content:
            raise ValueError("Empty bulk transport")
        digest = hashlib.sha256(content).hexdigest()
        filename = f"{kind}-{digest}.json.gz"
        path = Path(directory) / filename
        with (
            path.open("wb") as output,
            gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed,
        ):
            compressed.write(content)
        target = f"@{_STAGE}/{run_id}/{kind}"
        uri = f"file://{path.as_posix()}" if os.name == "nt" else path.as_uri()
        cursor.execute(
            f"PUT '{uri}' {target} AUTO_COMPRESS=FALSE SOURCE_COMPRESSION=GZIP OVERWRITE=FALSE"
        )
    return f"{target}/{filename}"


def remove_transport(cursor: Any, source: str) -> None:
    """Discard only a known transport file after its destination transaction commits."""
    if not _TRANSPORT_REF.fullmatch(source):
        raise ValueError("Unsafe bulk transport reference")
    cursor.execute(f"REMOVE {source}")
