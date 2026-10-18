"""Create exact-action security request hashes without any database connection."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS = [
    "RETAINED_MODEL_RELEASES_V",
    "RETAINED_MODEL_SOURCES_V",
    "RETAINED_MODEL_MEMBERSHIP_V",
    "RETAINED_MODEL_OBSERVATIONS_V",
]


def request():
    paths = [
        "sql/validation/release-integrity-retained-diagnostic-proposal.sql",
        "sql/validation/release-integrity-retained-diagnostic-revoke.sql",
    ]
    return {
        "status": "DESIGN_APPROVED_EXECUTION_NOT_AUTHORIZED",
        "product_design_approval": "Product Owner Decision 2, 2026-10-18 instruction",
        "security_review": None,
        "exact_action_authorization": None,
        "database": "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        "schema": "LINEAGE_AUDIT",
        "caller_role": "OH_LYME_PROD_READ",
        "caller_connection": "ATLAS_PROD_READ",
        "installation_role": "OH_LYME_PROD_MIGRATION_DEPLOYER",
        "installation_route": "Separately authorized protected forward migration; not generic DEV",
        "objects": ["LINEAGE_AUDIT." + name for name in VIEWS],
        "new_reader_grants": [
            {"privilege": "SELECT", "object": "LINEAGE_AUDIT." + name, "role": "OH_LYME_PROD_READ"}
            for name in VIEWS
        ],
        "existing_required_grants": [
            "DATABASE USAGE",
            "LINEAGE_AUDIT USAGE",
            "SELECT LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V",
        ],
        "base_table_reader_grants": [],
        "role_membership_changes": [],
        "installer_dependency_reads": [
            "PRESENTATION." + name
            for name in (
                "SEMANTIC_RELEASES",
                "SEMANTIC_DATA_SOURCES",
                "SEMANTIC_COUNTY_ATLAS",
                "SEMANTIC_OBSERVATIONS",
            )
        ],
        "sources": ["human", "pathogen", "tick", "context_svi", "context_rucc"],
        "retained_pairs": [
            {
                "release_id": "governed-2026-09-18-unknown-coverage",
                "bundle_sha256": "038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026",
            },
            {
                "release_id": "governed-2026-10-15-january-climate-prod",
                "bundle_sha256": "53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d",
            },
        ],
        "sql_artifacts": [
            {
                "path": path,
                "normalized_utf8_sha256": hashlib.sha256(
                    (ROOT / path).read_text(encoding="utf-8").encode()
                ).hexdigest(),
            }
            for path in paths
        ],
        "proposed_fail_closed_expiry_utc": "2026-10-25T00:00:00Z",
        "expiry_policy": (
            "After expiry views return no rows; refresh date/hash/review if execution is later"
        ),
        "retention_policy": (
            "Retain aggregate proof/query-ID and GET_DDL/grant receipts before revocation"
        ),
        "revocation_policy": (
            "Revoke only four new SELECT grants; drop only receipt-matched new"
            " views after dependency review"
        ),
        "preserve": [
            "V137/V148 and existing audit SELECT",
            "LINEAGE_AUDIT schema and USAGE",
            "All base data",
            "Approvals",
            "Models",
            "Semantic pointers",
        ],
        "credential_policy": (
            "No OWNER/MIGRATOR/ACCOUNTADMIN diagnostic caller or exported service keys"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Choose a fresh request artifact path")
    args.output.write_text(json.dumps(request(), indent=2) + "\n")


if __name__ == "__main__":
    main()
