"""Bounded, read-only Tier1 lineage proof; never records compatibility approval.

Requires an already authorized named PAT with retained-release reads. A missing
privilege is a blocker, not permission to change roles. Each source/state query
has a 60 second timeout through the existing query helper. Receipts contain no
county records. Run only in the explicitly authorized environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from compare_tier1_release_inputs import BUNDLE, TARGET, query

ORIGINAL = "governed-2026-09-18-unknown-coverage"
ORIGINAL_BUNDLE = "038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026"
SOURCES = ("human", "pathogen", "context_svi", "context_rucc", "tick")
SOURCE_FIELDS = (
    "source_key,resource_key,source_id,dataset_id,source_version_id,ingestion_run_id,"
    "artifact_id,vintage,note,source_url,label"
)
ROW_FIELDS = (
    "county_fips,measure_id,temporal_window,source_key,source_version_id,ingestion_run_id,"
    "artifact_id,artifact_sha256,semantic_source_record_id,semantic_source_row_hash,"
    "governed_source_version_id,governed_ingestion_run_id,governed_source_record_id,"
    "governed_source_row_hash,record_match_kind"
)


def multiset(rows):
    return Counter(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    if args.receipt.exists():
        raise ValueError("Use a fresh receipt path; prior evidence is immutable")
    args.receipt.write_text(json.dumps({"status": "incomplete", "kind": "not_approval"}) + "\n")
    context = query(
        args.connection,
        "SELECT CURRENT_USER() AS U,CURRENT_ROLE() AS R,"
        "CURRENT_DATABASE() AS D,CURRENT_WAREHOUSE() AS W",
    )
    if len(context) != 1 or context[0]["D"] != "ONE_HEALTH_LYME_GAP_ATLAS_PROD":
        raise ValueError("Explicitly authorized retained PROD read context required")
    # Proof prerequisites: original source descriptions and complete mappings.
    # READ lacks this retained-manifest projection today; fail before long scans.
    pins = []
    for release, bundle in ((ORIGINAL, ORIGINAL_BUNDLE), (TARGET, BUNDLE)):
        release_rows = query(
            args.connection,
            "SELECT bundle_sha256,source_manifest FROM "
            f"PRESENTATION.SEMANTIC_RELEASES WHERE release_id='{release}'",
        )
        if len(release_rows) != 1 or release_rows[0]["BUNDLE_SHA256"] != bundle:
            raise ValueError("Retained release identity differs")
        manifest = release_rows[0]["SOURCE_MANIFEST"]
        if isinstance(manifest, str):
            manifest = json.loads(manifest)
        mapped = [r for r in manifest["sources"] if r["source_key"] in SOURCES]
        if len(mapped) != len(SOURCES) or {r["source_key"] for r in mapped} != set(SOURCES):
            raise ValueError("Missing or duplicate source mapping")
        selected = [
            {k: r[k] for k in ("source_key", "artifact_sha256", "definition_version", "field_map")}
            for r in mapped
        ]
        source_rows = query(
            args.connection,
            "SELECT " + SOURCE_FIELDS + " FROM "
            f"PRESENTATION.SEMANTIC_DATA_SOURCES WHERE release_id='{release}' "
            "AND source_key IN ('human','pathogen','context_svi','context_rucc','tick')",
        )
        if len(source_rows) != len(SOURCES) or {r["SOURCE_KEY"] for r in source_rows} != set(
            SOURCES
        ):
            raise ValueError("Missing or duplicate source metadata")
        pins.append((multiset(selected), multiset(source_rows)))
    if pins[0] != pins[1]:
        raise ValueError("Scientific source mapping or identity differs; ML review required")
    canonical = (
        (Path(__file__).parents[1] / "src/lyme_gap_atlas_data/data/canonical-county-fips-2022.txt")
        .read_text()
        .split()
    )
    states = sorted({f[:2] for f in canonical})
    receipt = {
        "kind": "full_lineage_comparison_not_approval",
        "status": "incomplete",
        "original_release": ORIGINAL,
        "target_release": TARGET,
        "source_pins_equal": True,
        "context": context,
        "partitions": [],
    }
    for state in states:
        rows = []
        for release in (ORIGINAL, TARGET):
            result = query(
                args.connection,
                "SELECT " + ROW_FIELDS + " FROM "
                "LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V "
                f"WHERE release_id='{release}' AND SUBSTR(county_fips,1,2)='{state}' "
                "AND source_key IN ('human','pathogen','context_svi','context_rucc','tick')",
            )
            base = query(
                args.connection,
                "SELECT COUNT(*) AS N FROM PRESENTATION.SEMANTIC_OBSERVATIONS "
                f"WHERE release_id='{release}' AND SUBSTR(fips,1,2)='{state}' "
                "AND source_key IN ('human','pathogen','context_svi','context_rucc','tick')",
            )
            if len(base) != 1 or len(result) != base[0]["N"]:
                raise ValueError("Audit projection dropped or multiplied observation lineage")
            if not result or any(
                r["RECORD_MATCH_KIND"] == "UNMATCHED"
                or r["GOVERNED_SOURCE_VERSION_ID"] is None
                or r["GOVERNED_INGESTION_RUN_ID"] is None
                or r["ARTIFACT_SHA256"] is None
                for r in result
            ):
                raise ValueError("Missing governed row lineage in partition " + state)
            rows.append(multiset(result))
        equal = rows[0] == rows[1]
        digest = hashlib.sha256(json.dumps(sorted(rows[0].items())).encode()).hexdigest()
        receipt["partitions"].append(
            {
                "state": state,
                "rows": sum(rows[0].values()),
                "lineage_sha256": digest,
                "equal": equal,
            }
        )
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
        if not equal:
            raise ValueError("Observation lineage differs; ML review required")
    receipt["status"] = "complete_equal_not_approval"
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
