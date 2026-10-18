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
from datetime import UTC, datetime
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
    parser.add_argument(
        "--reviewed-projections",
        action="store_true",
        help="Use separately security-approved, scoped LINEAGE_AUDIT views",
    )
    args = parser.parse_args()

    def read(sql):
        if args.reviewed_projections:
            for base, view in {
                "PRESENTATION.SEMANTIC_RELEASES": "LINEAGE_AUDIT.RETAINED_MODEL_RELEASES_V",
                "PRESENTATION.SEMANTIC_DATA_SOURCES": "LINEAGE_AUDIT.RETAINED_MODEL_SOURCES_V",
                "PRESENTATION.SEMANTIC_COUNTY_ATLAS": "LINEAGE_AUDIT.RETAINED_MODEL_MEMBERSHIP_V",
                "PRESENTATION.SEMANTIC_OBSERVATIONS": "LINEAGE_AUDIT.RETAINED_MODEL_OBSERVATIONS_V",
            }.items():
                sql = sql.replace(base, view)
        return query(args.connection, sql)

    if args.receipt.exists():
        raise ValueError("Use a fresh receipt path; prior evidence is immutable")
    args.receipt.write_text(json.dumps({"status": "incomplete", "kind": "not_approval"}) + "\n")
    context = read(
        "SELECT CURRENT_USER() AS U,CURRENT_ROLE() AS R,"
        "CURRENT_DATABASE() AS D,CURRENT_WAREHOUSE() AS W",
    )
    if len(context) != 1 or (context[0]["D"], context[0]["R"]) != (
        "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        "OH_LYME_PROD_READ",
    ):
        raise ValueError("Explicitly authorized retained PROD read context required")
    # Proof prerequisites: original source descriptions and complete mappings.
    # READ lacks this retained-manifest projection today; fail before long scans.
    receipt = {
        "kind": "full_lineage_comparison_not_approval",
        "status": "incomplete",
        "observed_at": datetime.now(UTC).isoformat(),
        "original_release": ORIGINAL,
        "target_release": TARGET,
        "context": context,
        "partitions": [],
        "mismatches": [],
        "canonical_membership_equal": False,
    }
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    canonical = set(
        (Path(__file__).parents[1] / "src/lyme_gap_atlas_data/data/canonical-county-fips-2022.txt")
        .read_text()
        .split()
    )
    pins = []
    for release, bundle in ((ORIGINAL, ORIGINAL_BUNDLE), (TARGET, BUNDLE)):
        release_rows = read(
            "SELECT bundle_sha256,source_manifest FROM "
            f"PRESENTATION.SEMANTIC_RELEASES WHERE release_id='{release}'",
        )
        if len(release_rows) != 1 or release_rows[0]["BUNDLE_SHA256"] != bundle:
            raise ValueError("Retained release identity differs")
        members = read(
            f"SELECT fips FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS WHERE release_id='{release}'",
        )
        if len(members) != len(canonical) or {r["FIPS"] for r in members} != canonical:
            receipt["mismatches"].append(
                {
                    "release": release,
                    "field": "canonical_membership",
                    "actual_rows": len(members),
                    "missing_fips": sorted(canonical - {r["FIPS"] for r in members}),
                    "extra_fips": sorted({r["FIPS"] for r in members} - canonical),
                }
            )
            args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
            raise ValueError("Canonical membership differs")
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
        source_rows = read(
            "SELECT " + SOURCE_FIELDS + " FROM "
            f"PRESENTATION.SEMANTIC_DATA_SOURCES WHERE release_id='{release}' "
            "AND source_key IN ('human','pathogen','context_svi','context_rucc','tick')",
        )
        if len(source_rows) != len(SOURCES) or {r["SOURCE_KEY"] for r in source_rows} != set(
            SOURCES
        ):
            raise ValueError("Missing or duplicate source metadata")
        pins.append((multiset(selected), multiset(source_rows)))
    receipt["canonical_membership_equal"] = True
    if pins[0] != pins[1]:
        for kind, position in (("source_mapping", 0), ("source_metadata", 1)):
            before = {
                json.loads(r).get("source_key", json.loads(r).get("SOURCE_KEY")): json.loads(r)
                for r in pins[0][position]
            }
            after = {
                json.loads(r).get("source_key", json.loads(r).get("SOURCE_KEY")): json.loads(r)
                for r in pins[1][position]
            }
            for source in sorted(set(before) | set(after)):
                old, new = before.get(source, {}), after.get(source, {})
                for field in sorted(set(old) | set(new)):
                    if old.get(field) != new.get(field):
                        receipt["mismatches"].append(
                            {
                                "kind": kind,
                                "source_key": source,
                                "field": field,
                                "original": old.get(field),
                                "target": new.get(field),
                            }
                        )
        receipt["status"] = "different_not_eligible_not_approval"
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
        raise ValueError("Scientific source mapping or identity differs; ML review required")
    states = sorted({f[:2] for f in canonical})
    receipt["source_pins_equal"] = True
    for state in states:
        rows = []
        for release in (ORIGINAL, TARGET):
            result = read(
                "SELECT " + ROW_FIELDS + ",observation_id,release_bundle_sha256 FROM "
                "LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V "
                f"WHERE release_id='{release}' AND SUBSTR(county_fips,1,2)='{state}' "
                "AND source_key IN ('human','pathogen','context_svi','context_rucc','tick')",
            )
            base = read(
                "SELECT COUNT(*) AS N FROM PRESENTATION.SEMANTIC_OBSERVATIONS "
                f"WHERE release_id='{release}' AND SUBSTR(fips,1,2)='{state}' "
                "AND source_key IN ('human','pathogen','context_svi','context_rucc','tick')",
            )
            if len(base) != 1 or len(result) != base[0]["N"]:
                receipt["mismatches"].append(
                    {
                        "kind": "audit_base_cardinality",
                        "state": state,
                        "release": release,
                        "audit_rows": len(result),
                        "base_counts": base,
                    }
                )
                args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
                raise ValueError("Audit projection dropped or multiplied observation lineage")
            ids = [r["OBSERVATION_ID"] for r in result]
            if len(set(ids)) != len(ids) or any(value is None for value in ids):
                receipt["mismatches"].append(
                    {
                        "kind": "nonunique_audit_identity",
                        "state": state,
                        "release": release,
                        "rows": len(ids),
                        "distinct_ids": len(set(ids)),
                    }
                )
                args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
                raise ValueError("Audit projection duplicated an observation identity")
            expected_bundle = ORIGINAL_BUNDLE if release == ORIGINAL else BUNDLE
            invalid = Counter()
            for row in result:
                checks = {
                    "record_match_kind": row["RECORD_MATCH_KIND"] != "UNMATCHED",
                    "source_version": row["GOVERNED_SOURCE_VERSION_ID"] is not None
                    and row["SOURCE_VERSION_ID"] == row["GOVERNED_SOURCE_VERSION_ID"],
                    "ingestion_run": row["GOVERNED_INGESTION_RUN_ID"] is not None
                    and row["INGESTION_RUN_ID"] == row["GOVERNED_INGESTION_RUN_ID"],
                    "artifact_sha256": row["ARTIFACT_SHA256"] is not None,
                    "release_bundle": row["RELEASE_BUNDLE_SHA256"] == expected_bundle,
                    "source_row_hash": row["SEMANTIC_SOURCE_ROW_HASH"] is not None
                    and row["SEMANTIC_SOURCE_ROW_HASH"] == row["GOVERNED_SOURCE_ROW_HASH"],
                }
                invalid.update(field for field, valid in checks.items() if not valid)
            if not result or invalid:
                receipt["mismatches"].append(
                    {
                        "kind": "governed_lineage_validation",
                        "state": state,
                        "release": release,
                        "invalid_rows_by_field": dict(invalid),
                        "empty_partition": not result,
                    }
                )
                args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
                raise ValueError("Missing governed row lineage in partition " + state)
            rows.append(
                multiset(
                    [
                        {
                            k: v
                            for k, v in row.items()
                            if k not in {"OBSERVATION_ID", "RELEASE_BUNDLE_SHA256"}
                        }
                        for row in result
                    ]
                )
            )
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
            receipt["status"] = "different_not_eligible_not_approval"
            receipt["mismatches"].append(
                {
                    "kind": "observation_lineage",
                    "state": state,
                    "original_only_multiplicity": sum((rows[0] - rows[1]).values()),
                    "target_only_multiplicity": sum((rows[1] - rows[0]).values()),
                }
            )
            args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
            raise ValueError("Observation lineage differs; ML review required")
    receipt["status"] = "complete_equal_not_approval"
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
