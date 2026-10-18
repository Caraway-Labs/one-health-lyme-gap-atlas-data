"""Fixed named-PAT read probes; never deploys, grants or calls owner procedures."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from lyme_gap_atlas_data.migrations import load_migrations

ROOT = Path(__file__).resolve().parents[1]
PROBES = {
    "dev_ledger": (
        "DEV",
        "SELECT version,filename,sha256,deployment_commit FROM "
        "GOVERNANCE.SCHEMA_MIGRATIONS ORDER BY version",
    ),
    "dev_release": ("DEV", "SELECT release_id,bundle_sha256 FROM PRESENTATION.CURRENT_RELEASE_V"),
    "retained_manifests": (
        "PROD",
        "SELECT release_id,bundle_sha256,source_manifest "
        "FROM PRESENTATION.SEMANTIC_RELEASES LIMIT 0",
    ),
    "retained_sources": (
        "PROD",
        "SELECT release_id,source_key,source_id,dataset_id,resource_key,"
        "source_version_id,ingestion_run_id,artifact_id,label,vintage,source_url,note "
        "FROM PRESENTATION.SEMANTIC_DATA_SOURCES LIMIT 0",
    ),
    "retained_observations": (
        "PROD",
        "SELECT release_id,fips,source_key FROM PRESENTATION.SEMANTIC_OBSERVATIONS LIMIT 0",
    ),
    "retained_membership": (
        "PROD",
        "SELECT release_id,fips FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS LIMIT 0",
    ),
    "governed_lineage": (
        "PROD",
        "SELECT release_id,observation_id,release_bundle_sha256,"
        "governed_source_version_id,governed_ingestion_run_id,artifact_sha256,"
        "semantic_source_row_hash,governed_source_row_hash,record_match_kind "
        "FROM LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V LIMIT 0",
    ),
}


def execute(environment, sql):
    warehouse = "COMPUTE_WH" if environment == "PROD" else "OH_LYME_DEV_INGEST_XS_WH"
    result = subprocess.run(
        [
            "snow",
            "sql",
            "-c",
            "ATLAS_" + environment + "_READ",
            "--warehouse",
            warehouse,
            "--format",
            "JSON",
            "-q",
            "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=30,"
            "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS=10,QUERY_TAG='DATA706_ACCESS_PREFLIGHT'; "
            + sql
            + "; SELECT LAST_QUERY_ID() AS QUERY_ID",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode:
        ids = re.findall(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", result.stderr)
        codes = re.findall(r"\b[0-9]{6} \([0-9A-Z]{5}\)", result.stderr)
        return {
            "status": "BLOCKED",
            "query_id": ids[-1] if ids else None,
            "error_code": codes[-1] if codes else "CLI_ERROR",
            "rows": None,
        }
    values = json.loads(result.stdout)
    return {"status": "PASS", "query_id": values[-1][0]["QUERY_ID"], "rows": values[-2]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    if args.receipt.exists():
        raise ValueError("Choose a fresh immutable receipt path")
    receipt = {
        "kind": "read_only_access_preflight_not_execution_or_approval",
        "observed_at": datetime.now(UTC).isoformat(),
        "source_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip(),
        "contexts": {},
        "probes": {},
        "migration_source": [],
    }
    for environment in ("DEV", "PROD"):
        result = execute(
            environment,
            "SELECT CURRENT_USER() AS U,CURRENT_ROLE() AS R,"
            "CURRENT_DATABASE() AS D,CURRENT_WAREHOUSE() AS W",
        )
        if result["status"] != "PASS":
            raise ValueError("Named READ context unavailable: " + environment)
        row = result["rows"][0]
        if row["R"] != "OH_LYME_" + environment + "_READ" or row["D"] != (
            "ONE_HEALTH_LYME_GAP_ATLAS_" + environment
        ):
            raise ValueError("Unexpected READ context")
        receipt["contexts"][environment] = result
    for name, (environment, sql) in PROBES.items():
        receipt["probes"][name] = execute(environment, sql)
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    for migration in load_migrations():
        if migration.version in {"V157", "V158"}:
            receipt["migration_source"].append(
                {
                    "version": migration.version,
                    "filename": migration.filename,
                    "sha256": migration.sha256,
                }
            )
    ledger = receipt["probes"]["dev_ledger"]
    if ledger["status"] == "PASS":
        applied = {row["VERSION"] for row in ledger["rows"]}
        receipt["dev_release_integrity_installed"] = {v: v in applied for v in ("V157", "V158")}
    receipt["workflow_sha256"] = hashlib.sha256(
        (ROOT / ".github/workflows/deploy-dev.yml").read_bytes()
    ).hexdigest()
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: v["status"] for k, v in receipt["probes"].items()}))


if __name__ == "__main__":
    main()
