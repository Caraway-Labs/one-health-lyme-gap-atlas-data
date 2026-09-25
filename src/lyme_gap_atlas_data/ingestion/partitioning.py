"""Bounded, deterministic normalized-row partitions for canonical ingestion."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

MAX_PARTITION_ROWS = 250
MAX_PARTITION_BYTES = 900_000


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class NormalizedPartition:
    ordinal: int
    records: tuple[dict[str, object], ...]
    sha256: str
    byte_count: int

    @property
    def partition_id(self) -> str:
        return f"{self.ordinal:08d}:{self.sha256}"


def partition_records(
    records: Iterable[dict[str, object]],
    *,
    max_rows: int = MAX_PARTITION_ROWS,
    max_bytes: int = MAX_PARTITION_BYTES,
) -> Iterator[NormalizedPartition]:
    """Consume rows once; never hold more than one bounded partition."""
    if max_rows < 1 or max_bytes < 3:
        raise ValueError("Partition limits must be positive")
    batch: list[dict[str, object]] = []
    size = 2  # JSON array brackets
    ordinal = 0
    for record in records:
        row_size = len(canonical_bytes(record))
        if row_size + 2 > max_bytes:
            raise ValueError("Normalized row exceeds partition byte limit")
        additional = row_size + (1 if batch else 0)
        if batch and (len(batch) >= max_rows or size + additional > max_bytes):
            yield _partition(ordinal, batch)
            ordinal += 1
            batch = []
            size = 2
            additional = row_size
        batch.append(record)
        size += additional
    if batch:
        yield _partition(ordinal, batch)


def _partition(ordinal: int, records: list[dict[str, object]]) -> NormalizedPartition:
    content = canonical_bytes(records)
    return NormalizedPartition(
        ordinal=ordinal,
        records=tuple(records),
        sha256=hashlib.sha256(content).hexdigest(),
        byte_count=len(content),
    )
