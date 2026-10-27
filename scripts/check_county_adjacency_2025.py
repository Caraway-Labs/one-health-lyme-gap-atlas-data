"""Offline check of the pinned Census 2025 county adjacency file.

The file is not a repository fixture. Pass a local path. The script prints
counts only and exits non-zero when the digest or the pair counts do not
match the issue #872 pin.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from lyme_gap_atlas_data.county_adjacency import (
    EXPECTED_EDGE_PAIRS,
    EXPECTED_ISLANDS,
    EXPECTED_POINT_PAIRS,
    EXPECTED_UNDIRECTED_PAIRS,
    PINNED_SHA256,
    CountyAdjacencyError,
    conform_published_rows,
    project_counties,
)
from lyme_gap_atlas_data.ingestion.adapters import _csv_rows
from lyme_gap_atlas_data.ingestion.source_definition import load_source_definition

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = ROOT / "config" / "sources" / "census_county_adjacency_2025.yml"


def main(path: Path) -> int:
    body = path.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    if digest != PINNED_SHA256:
        print(f"SHA256_MISMATCH {digest}")
        return 2
    definition = load_source_definition(DEFINITION)
    rows = _csv_rows(body, definition)
    try:
        result = conform_published_rows(rows, reference=project_counties())
    except CountyAdjacencyError as error:
        print(error.code)
        return 1
    islands = frozenset(result.islands)
    if (
        len(result.pairs) != EXPECTED_UNDIRECTED_PAIRS
        or result.edge_count != EXPECTED_EDGE_PAIRS
        or result.point_count != EXPECTED_POINT_PAIRS
        or islands != EXPECTED_ISLANDS
    ):
        print("PAIR_COUNT")
        return 1
    print(
        f"pairs={len(result.pairs)} edge={result.edge_count} "
        f"point={result.point_count} islands={','.join(result.islands)}"
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("USAGE")
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
