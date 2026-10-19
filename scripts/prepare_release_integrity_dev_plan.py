"""Fixed approved fixture rendering; no Snowflake/network or execution option.

Product Owner Decision 1 approves this mapping. Execution still requires
exact-head engineering/security approval in the existing DEV workflow.
Rendering is not permission to apply a migration outside its ledger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from lyme_gap_atlas_data.migrations import DEV_DATABASE, load_migrations, render_migration

SCHEMAS = {name: "RI706_" + name for name in ("FEATURE_STORE", "PRESENTATION", "GOVERNANCE")}


def render_fixture(migration):
    if migration.version not in {"V157", "V158"}:
        raise ValueError("Only the exact V157/V158 pair can be prepared")
    sql = render_migration(migration, DEV_DATABASE)
    for source, target in SCHEMAS.items():
        sql = re.sub(r"\b" + source + r"\.", target + ".", sql)
    if any(re.search(r"\b" + schema + r"\.", sql) for schema in SCHEMAS):
        raise ValueError("Unisolated reference remains")
    if "{{" in sql or "OH_LYME_PROD_" in sql:
        raise ValueError("Unresolved or production role reference")
    if not sql.startswith("--") or "USE DATABASE " + DEV_DATABASE + ";" not in sql:
        raise ValueError("Unexpected migration database scope")
    return "-- UNAPPROVED FIXTURE RENDERING. DO NOT EXECUTE.\n" + sql


def prepare(output):
    if output.exists():
        raise ValueError("Use a fresh plan directory; existing evidence is immutable")
    selected = [m for m in load_migrations() if m.version in {"V157", "V158"}]
    if {m.version for m in selected} != {"V157", "V158"}:
        raise ValueError("Incomplete migration pair")
    output.mkdir(parents=True)
    plan = {
        "status": "PROPOSAL_NOT_AUTHORIZATION_NOT_EXECUTED",
        "database": DEV_DATABASE,
        "schema_mapping": SCHEMAS,
        "preparation_git_head": subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip(),
        "image_digest": None,
        "dev_execution_receipt": None,
        "protected_workflow": ".github/workflows/deploy-dev.yml",
        "required_execution_role": "OH_LYME_DEV_MIGRATION_DEPLOYER",
        "required_execution_user": "OH_LYME_DEV_MIGRATION_DEPLOY_SVC",
        "required_warehouse": "OH_LYME_DEV_INGEST_XS_WH",
        "migrations": [],
        "blockers": [
            "PROD scoped guard unchanged; dedicated fixture job requires independent review",
            "Product-approved fixture implementation needs exact-head security/engineering review",
            "Synthetic owner calls are approved only after the required implementation review",
            "No real Data/scientific admission may be recorded",
        ],
        "preserve": [
            "All live DEV schemas and release pointer",
            "PROD",
            "Existing migration ledger",
            "Unrelated pending migrations",
            "Frozen ML artifact bytes",
        ],
    }
    for migration in selected:
        sql = render_fixture(migration)
        (output / migration.filename).write_text(sql)
        plan["migrations"].append(
            {
                "version": migration.version,
                "filename": migration.filename,
                "source_sha256": migration.sha256,
                "fixture_sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
            }
        )
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.output)))


if __name__ == "__main__":
    main()
