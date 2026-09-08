"""Apply one historical-review migration through its existing DEV owner using snow CLI."""

import argparse
import json
import re
import subprocess

from lyme_gap_atlas_data.migrations import load_migrations, render_migration


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--connection", required=True)
    parser.add_argument("--version", choices=["V044", "V045"], required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--confirm", action="store_true", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        raise ValueError("Exact source commit required")
    database = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
    role = (
        "OH_LYME_DEV_STREAMLIT_OWNER"
        if args.version == "V044"
        else "OH_LYME_DEV_MIGRATION_DEPLOYER"
    )
    warehouse = (
        "OH_LYME_DEV_APPROVAL_XS_WH" if args.version == "V044" else "OH_LYME_DEV_INGEST_XS_WH"
    )

    def sql(statement):
        result = subprocess.run(
            [
                "snow",
                "sql",
                "-c",
                args.connection,
                "--database",
                database,
                "--warehouse",
                warehouse,
                "--format",
                "JSON",
                "-q",
                statement,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("DEV review statement failed; no success ledger written")
        return json.loads(result.stdout)

    context = sql(
        "SELECT CURRENT_USER() AS WHO,CURRENT_ROLE() AS ROLE,"
        "CURRENT_DATABASE() AS DB,CURRENT_WAREHOUSE() AS WH"
    )[0]
    print(json.dumps({"preflight": context}), flush=True)
    if not context["WHO"] or (context["ROLE"], context["DB"], context["WH"]) != (
        role,
        database,
        warehouse,
    ):
        raise ValueError("Unexpected DEV owner context")
    migration = next(item for item in load_migrations() if item.version == args.version)
    prior = sql(f"SELECT sha256 FROM GOVERNANCE.SCHEMA_MIGRATIONS WHERE version='{args.version}'")
    if prior:
        if len(prior) != 1 or prior[0]["SHA256"] != migration.sha256:
            raise ValueError("Migration checksum mismatch")
        print(f"{args.version}=ALREADY_APPLIED")
        return
    sql(render_migration(migration, database))
    sql(
        "INSERT INTO GOVERNANCE.SCHEMA_MIGRATIONS "
        "(version,filename,sha256,deployment_commit,applied_by) "
        f"VALUES ('{migration.version}','{migration.filename}','{migration.sha256}',"
        f"'{args.commit}',CURRENT_USER())"
    )
    print(f"{args.version}=APPLIED sha256={migration.sha256}")


if __name__ == "__main__":
    main()
