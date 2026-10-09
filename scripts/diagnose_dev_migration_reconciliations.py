"""Fixed, read-only DEV legacy migration reconciliation diagnostic."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    LEGACY_DEV_MIGRATION_CHECKSUMS,
    RECONCILIATION_REASON,
    load_migrations,
)

USER = "OH_LYME_DEV_MIGRATION_DEPLOY_SVC"
ROLE = "OH_LYME_DEV_MIGRATION_DEPLOYER"
WAREHOUSE = "OH_LYME_DEV_INGEST_XS_WH"
TABLE = f"{DEV_DATABASE}.GOVERNANCE.SCHEMA_MIGRATION_RECONCILIATIONS"
IDENTITY_SQL = (
    "SELECT CURRENT_USER() AS USER_NAME, CURRENT_ROLE() AS ROLE_NAME, "
    "CURRENT_DATABASE() AS DATABASE_NAME, CURRENT_WAREHOUSE() AS WAREHOUSE_NAME"
)
TABLE_SQL = (
    f"SHOW TABLES LIKE 'SCHEMA_MIGRATION_RECONCILIATIONS' IN SCHEMA {DEV_DATABASE}.GOVERNANCE"
)
GRANTS_SQL = f"SHOW GRANTS ON TABLE {TABLE}"
ROWS_SQL = (
    "SELECT MIGRATION_VERSION, LEGACY_SHA256, SOURCE_SHA256, RECONCILIATION_SCOPE, "
    "RATIONALE, APPROVED_BY "
    f"FROM {TABLE} ORDER BY MIGRATION_VERSION, RECONCILIATION_SCOPE"
)
ALLOWED_SQL = frozenset((IDENTITY_SQL, TABLE_SQL, GRANTS_SQL, ROWS_SQL))
Query = Callable[[str], list[dict[str, Any]]]


def _value(row: dict[str, Any], column: str) -> Any:
    return next((value for key, value in row.items() if key.upper() == column.upper()), None)


def diagnose(query: Query, expected_warehouse: str) -> dict[str, Any]:
    """Fail closed on identity, visibility, or any unexpected DEV evidence."""
    result: dict[str, Any] = {"disposition": "FAIL", "identity_matches": {}}
    try:
        identity_rows = query(IDENTITY_SQL)
    except (RuntimeError, ValueError):
        result["reason"] = "IDENTITY_UNAVAILABLE"
        return result
    identity = identity_rows[0] if len(identity_rows) == 1 else {}
    matches = {
        "user": _value(identity, "USER_NAME") == USER,
        "role": _value(identity, "ROLE_NAME") == ROLE,
        "database": _value(identity, "DATABASE_NAME") == DEV_DATABASE,
        "warehouse": expected_warehouse == WAREHOUSE
        and _value(identity, "WAREHOUSE_NAME") == WAREHOUSE,
    }
    result["identity_matches"] = matches
    if not all(matches.values()):
        result["reason"] = "IDENTITY_MISMATCH"
        return result

    try:
        tables = query(TABLE_SQL)
        grants = query(GRANTS_SQL)
        rows = query(ROWS_SQL)
    except (RuntimeError, ValueError):
        result["reason"] = "TABLE_OR_PRIVILEGE_UNAVAILABLE"
        return result
    found = [row for row in tables if _value(row, "name") == "SCHEMA_MIGRATION_RECONCILIATIONS"]
    if len(found) != 1:
        result["reason"] = "TABLE_NOT_VISIBLE_OR_AMBIGUOUS"
        return result
    result["table_owner"] = _value(found[0], "owner") or "UNKNOWN"
    result["table_grants"] = sorted(
        [
            {
                "grantee": _value(row, "grantee_name"),
                "granted_to": _value(row, "granted_to"),
                "privilege": _value(row, "privilege"),
                "grant_option": _value(row, "grant_option"),
            }
            for row in grants
        ],
        key=lambda row: (str(row["grantee"]), str(row["privilege"])),
    )
    result["owner_matches"] = result["table_owner"] == ROLE
    result["grants_match"] = len(grants) == 1 and all(
        _value(row, "privilege") == "OWNERSHIP"
        and _value(row, "grantee_name") == ROLE
        and _value(row, "granted_to") == "ROLE"
        and str(_value(row, "grant_option")).lower() == "false"
        for row in grants
    )

    expected_sources = {item.version: item.sha256 for item in load_migrations()}
    required = set(LEGACY_DEV_MIGRATION_CHECKSUMS)
    dev_rows = [row for row in rows if _value(row, "RECONCILIATION_SCOPE") == "DEV"]
    counts = Counter(str(_value(row, "MIGRATION_VERSION")) for row in dev_rows)
    result["dev_row_count"] = len(dev_rows)
    result["version_counts"] = dict(sorted(counts.items()))
    result["unexpected_versions"] = sorted(set(counts) - required)
    result["checksums_match"] = {
        version: counts[version] == 1
        and all(
            _value(row, "LEGACY_SHA256") == LEGACY_DEV_MIGRATION_CHECKSUMS[version]
            and _value(row, "SOURCE_SHA256") == expected_sources[version]
            and _value(row, "RATIONALE") == RECONCILIATION_REASON
            and bool(str(_value(row, "APPROVED_BY") or "").strip())
            for row in dev_rows
            if _value(row, "MIGRATION_VERSION") == version
        )
        for version in sorted(required)
    }
    result["expected_pairs"] = {
        version: {
            "legacy_sha256": LEGACY_DEV_MIGRATION_CHECKSUMS[version],
            "source_sha256": expected_sources[version],
        }
        for version in sorted(required)
    }
    result["observed_rows"] = [
        {
            "version": _value(row, "MIGRATION_VERSION"),
            "legacy_sha256": _value(row, "LEGACY_SHA256"),
            "source_sha256": _value(row, "SOURCE_SHA256"),
            "scope": _value(row, "RECONCILIATION_SCOPE"),
            "rationale_matches": _value(row, "RATIONALE") == RECONCILIATION_REASON,
            "approval_attributed": bool(str(_value(row, "APPROVED_BY") or "").strip()),
        }
        for row in dev_rows
    ]
    if (
        len(dev_rows) == len(required)
        and set(counts) == required
        and result["owner_matches"]
        and result["grants_match"]
        and all(result["checksums_match"].values())
    ):
        result["disposition"] = "PASS"
        result["reason"] = "EXACT_DEV_RECONCILIATIONS"
    else:
        result["reason"] = "DEV_RECONCILIATION_MISMATCH"
    return result


def _snow_query(config_file: Path, sql: str) -> list[dict[str, Any]]:
    if sql not in ALLOWED_SQL:
        raise ValueError("Only fixed read-only reconciliation queries are allowed")
    try:
        completed = subprocess.run(
            [
                "snow",
                "--config-file",
                str(config_file),
                "sql",
                "-c",
                "oh_lyme_dev",
                "-q",
                sql,
                "--format",
                "JSON",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Read-only reconciliation query timed out") from exc
    if completed.returncode != 0:
        raise RuntimeError("Read-only reconciliation query unavailable")
    rows = json.loads(completed.stdout)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise RuntimeError("Unexpected Snowflake response")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-file", type=Path, required=True)
    args = parser.parse_args()
    result = diagnose(
        lambda sql: _snow_query(args.config_file, sql),
        os.environ.get("SNOWFLAKE_WAREHOUSE", ""),
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["disposition"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
