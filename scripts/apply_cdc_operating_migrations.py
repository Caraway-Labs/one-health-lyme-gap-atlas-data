"""Explicitly authorized, CLI-only application of CDC migrations V042/V043."""

import argparse
import json
import re
import subprocess

from lyme_gap_atlas_data.migrations import load_migrations, render_migration


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=["dev", "prod"], required=True)
    parser.add_argument("--connection", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--confirm", action="store_true", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        raise ValueError("An exact source commit is required")
    env = args.environment.upper()
    database = f"ONE_HEALTH_LYME_GAP_ATLAS_{env}"

    def sql(query):
        result = subprocess.run(
            [
                "snow",
                "sql",
                "-c",
                args.connection,
                "--database",
                database,
                "--warehouse",
                f"OH_LYME_{env}_INGEST_XS_WH",
                "--format",
                "JSON",
                "-q",
                query,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("Scoped Snowflake CLI statement failed; no ledger success recorded")
        return json.loads(result.stdout)

    context = sql(
        "SELECT CURRENT_USER() AS WHO,CURRENT_ROLE() AS ROLE,"
        "CURRENT_DATABASE() AS DB,CURRENT_WAREHOUSE() AS WH"
    )[0]
    if context["ROLE"] != "ACCOUNTADMIN" or context["DB"] != database:
        raise ValueError("This approved repair requires the exact scoped account-admin context")
    if context["WH"] != f"OH_LYME_{env}_INGEST_XS_WH":
        raise ValueError("Unexpected warehouse")
    print(json.dumps({"preflight": context}), flush=True)
    prior = {
        row["VERSION"]: row["SHA256"]
        for row in sql(
            "SELECT version,sha256 FROM GOVERNANCE.SCHEMA_MIGRATIONS "
            "WHERE version IN ('V042','V043')"
        )
    }
    for migration in load_migrations():
        if migration.version not in {"V042", "V043"}:
            continue
        if migration.version in prior:
            if prior[migration.version] != migration.sha256:
                raise ValueError(f"Checksum mismatch for {migration.version}")
            print(f"{migration.version}=ALREADY_APPLIED", flush=True)
            continue
        sql(render_migration(migration, database))
        sql(
            "INSERT INTO GOVERNANCE.SCHEMA_MIGRATIONS "
            "(version,filename,sha256,deployment_commit,applied_by) "
            f"VALUES ('{migration.version}','{migration.filename}','{migration.sha256}',"
            f"'{args.commit}',CURRENT_USER())"
        )
        print(f"{migration.version}=APPLIED sha256={migration.sha256}", flush=True)


if __name__ == "__main__":
    main()
