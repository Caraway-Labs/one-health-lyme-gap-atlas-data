"""Bounded, read-only V103 DEV post-application verification."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lyme_gap_atlas_data.migrations import DEV_DATABASE, load_migrations, migration_plan

MIGRATION_USER = "OH_LYME_DEV_MIGRATION_DEPLOY_SVC"
MIGRATION_ROLE = "OH_LYME_DEV_MIGRATION_DEPLOYER"
RUNTIME_ROLE = "OH_LYME_DEV_RUNTIME"
SCHEMA = f"{DEV_DATABASE}.GOVERNANCE"
TABLE_NAMES = (
    "INGESTION_RUN_NORMALIZED_PARTITIONS",
    "INGESTION_RUN_PARTITION_COMPLETIONS",
    "GOVERNED_SOURCE_RECORD_REVISIONS",
)
READ_ONLY_SQL = re.compile(r"^\s*(?:SELECT|SHOW|DESCRIBE)\b", re.IGNORECASE)
CREATE_TABLE = re.compile(
    r"CREATE TABLE IF NOT EXISTS GOVERNANCE\.(\w+)\s*\(\n(.*?)\n\);", re.DOTALL
)
Query = Callable[[str], list[dict[str, Any]]]


def _value(row: dict[str, Any], name: str) -> Any:
    return next((value for key, value in row.items() if key.lower() == name.lower()), None)


def _source_tables() -> dict[str, dict[str, Any]]:
    migration = next(item for item in load_migrations() if item.version == "V103")
    tables: dict[str, dict[str, Any]] = {}
    for match in CREATE_TABLE.finditer(migration.source):
        columns: list[dict[str, Any]] = []
        primary_key: list[str] = []
        for line in match.group(2).splitlines():
            definition = line.strip().rstrip(",")
            if definition.startswith("PRIMARY KEY"):
                primary_key = [
                    item.strip().upper() for item in definition[12:].strip(" ()").split(",")
                ]
                continue
            name, type_name, *remainder = definition.split(maxsplit=2)
            options = remainder[0] if remainder else ""
            columns.append(
                {
                    "name": name.upper(),
                    "type": _normalized_type(type_name),
                    "nullable": "NOT NULL" not in options and "PRIMARY KEY" not in options,
                }
            )
            if "PRIMARY KEY" in options:
                primary_key.append(name.upper())
        tables[match.group(1)] = {"columns": columns, "primary_key": primary_key}
    if set(tables) != set(TABLE_NAMES):
        raise ValueError("V103 source table set changed; update the bounded diagnostic")
    return tables


def _normalized_type(value: str) -> str:
    normalized = value.upper().replace(" ", "")
    return {
        "VARCHAR": "VARCHAR(16777216)",
        "NUMBER": "NUMBER(38,0)",
        "TIMESTAMP_LTZ": "TIMESTAMP_LTZ(9)",
    }.get(normalized, normalized)


def _columns_match(observed: list[dict[str, Any]], expected: list[dict[str, Any]]) -> bool:
    actual = [
        {
            "name": str(_value(row, "name")).upper(),
            "type": _normalized_type(str(_value(row, "type"))),
            "nullable": str(_value(row, "null?")).upper() == "Y",
        }
        for row in observed
        if str(_value(row, "kind")).upper() == "COLUMN"
    ]
    return actual == expected


def _primary_key(rows: list[dict[str, Any]]) -> list[str]:
    return [
        str(_value(row, "column_name")).upper()
        for row in sorted(rows, key=lambda row: int(_value(row, "key_sequence")))
    ]


def _try_query(query: Query, sql: str) -> list[dict[str, Any]] | None:
    try:
        return query(sql)
    except (RuntimeError, ValueError):
        return None


def diagnose(query: Query, expected_warehouse: str, source_commit: str) -> dict[str, Any]:
    """Return metadata only; UNKNOWN is distinct from an observed false."""
    identity_rows = _try_query(
        query,
        "SELECT CURRENT_USER() AS USER_NAME, CURRENT_ROLE() AS ROLE_NAME, "
        "CURRENT_DATABASE() AS DATABASE_NAME, CURRENT_WAREHOUSE() AS WAREHOUSE_NAME",
    )
    identity = identity_rows[0] if identity_rows and len(identity_rows) == 1 else {}
    matches = {
        "user": _value(identity, "USER_NAME") == MIGRATION_USER,
        "role": _value(identity, "ROLE_NAME") == MIGRATION_ROLE,
        "database": _value(identity, "DATABASE_NAME") == DEV_DATABASE,
        "warehouse": bool(expected_warehouse)
        and _value(identity, "WAREHOUSE_NAME") == expected_warehouse,
    }
    result: dict[str, Any] = {
        "environment": "DEV",
        "source_commit": source_commit,
        "identity_matches": matches,
        "disposition": "IDENTITY_MISMATCH",
    }
    if not all(matches.values()):
        return result

    source_tables = _source_tables()
    migration = next(item for item in load_migrations() if item.version == "V103")
    result["v103_checksum"] = migration.sha256
    ledger = _try_query(
        query,
        f"SELECT VERSION, FILENAME, SHA256 FROM {SCHEMA}.SCHEMA_MIGRATIONS ORDER BY VERSION",
    )
    applied = {str(_value(row, "VERSION")): row for row in ledger or []}
    v103_receipt = applied.get("V103")
    pending = (
        [item["version"] for item in migration_plan(DEV_DATABASE) if item["version"] not in applied]
        if ledger is not None
        else None
    )
    result["ledger"] = {
        "latest": max(applied) if ledger is not None and applied else "UNKNOWN",
        "v103_present": "UNKNOWN" if ledger is None else "V103" in applied,
        "v103_filename": _value(v103_receipt, "FILENAME") if v103_receipt else "UNKNOWN",
        "v103_sha256": _value(v103_receipt, "SHA256") if v103_receipt else "UNKNOWN",
        "v103_source_matches": (
            "UNKNOWN"
            if ledger is None or v103_receipt is None
            else _value(v103_receipt, "FILENAME") == migration.filename
            and _value(v103_receipt, "SHA256") == migration.sha256
        ),
        "applied_versions": sorted(applied) if ledger is not None else "UNKNOWN",
        "pending_versions": pending if pending is not None else "UNKNOWN",
    }

    schema_rows = _try_query(
        query,
        f"SELECT SCHEMA_OWNER, IS_MANAGED_ACCESS FROM {DEV_DATABASE}.INFORMATION_SCHEMA.SCHEMATA "
        "WHERE SCHEMA_NAME='GOVERNANCE'",
    )
    schema = schema_rows[0] if schema_rows and len(schema_rows) == 1 else {}
    schema_grants = _try_query(query, f"SHOW GRANTS ON SCHEMA {SCHEMA}")
    runtime_roles = _try_query(query, f"SHOW ROLES LIKE '{RUNTIME_ROLE}'")
    relevant_roles = {MIGRATION_ROLE, RUNTIME_ROLE, "OH_LYME_DEV_OWNER"}
    result["schema"] = {
        "owner": _value(schema, "SCHEMA_OWNER") or "UNKNOWN",
        "managed_access": (
            "UNKNOWN" if not schema else _value(schema, "IS_MANAGED_ACCESS") == "YES"
        ),
        "relevant_grants": (
            "UNKNOWN"
            if schema_grants is None
            else [
                {
                    "role": _value(row, "grantee_name"),
                    "privilege": _value(row, "privilege"),
                    "grant_option": _value(row, "grant_option"),
                }
                for row in schema_grants
                if _value(row, "grantee_name") in relevant_roles
            ]
        ),
        "migration_create_table": (
            "UNKNOWN"
            if schema_grants is None
            else any(
                _value(row, "grantee_name") == MIGRATION_ROLE
                and _value(row, "privilege") == "CREATE TABLE"
                for row in schema_grants
            )
        ),
        "runtime_role_visible": (
            "UNKNOWN"
            if runtime_roles is None or not runtime_roles
            else any(_value(row, "name") == RUNTIME_ROLE for row in runtime_roles)
        ),
    }

    tables: dict[str, dict[str, Any]] = {}
    for name in TABLE_NAMES:
        qualified = f"{SCHEMA}.{name}"
        shown = _try_query(query, f"SHOW TABLES LIKE '{name}' IN SCHEMA {SCHEMA}")
        matches_table = [row for row in shown or [] if _value(row, "name") == name]
        if not matches_table:
            tables[name] = {"exists": "UNKNOWN", "visibility": "not visible or query denied"}
            continue
        table = matches_table[0]
        described = _try_query(query, f"DESCRIBE TABLE {qualified}")
        keys = _try_query(query, f"SHOW PRIMARY KEYS IN TABLE {qualified}")
        grants = _try_query(query, f"SHOW GRANTS ON TABLE {qualified}")
        definition_matches: bool | str = "UNKNOWN"
        if described is not None and keys is not None:
            expected = source_tables[name]
            definition_matches = _columns_match(described, expected["columns"]) and (
                _primary_key(keys) == expected["primary_key"]
            )
        privileges: dict[str, list[str]] | str = "UNKNOWN"
        conflicting_grants: bool | str = "UNKNOWN"
        if grants is not None:
            privileges = {
                role: sorted(
                    str(_value(row, "privilege"))
                    for row in grants
                    if _value(row, "grantee_name") == role
                )
                for role in (RUNTIME_ROLE, MIGRATION_ROLE)
            }
            conflicting_grants = bool(
                set(privileges[RUNTIME_ROLE]) & {"UPDATE", "DELETE", "TRUNCATE", "OWNERSHIP"}
            )
        tables[name] = {
            "exists": True,
            "owner": _value(table, "owner") or "UNKNOWN",
            "created_at": _value(table, "created_on") or "UNKNOWN",
            "row_count": _value(table, "rows"),
            "bytes": _value(table, "bytes"),
            "table_type": _value(table, "kind") or "UNKNOWN",
            "columns": (
                "UNKNOWN"
                if described is None
                else [
                    {
                        "name": _value(row, "name"),
                        "type": _value(row, "type"),
                        "nullable": _value(row, "null?"),
                    }
                    for row in described
                    if _value(row, "kind") == "COLUMN"
                ]
            ),
            "primary_key": "UNKNOWN" if keys is None else _primary_key(keys),
            "definition_matches_v103": definition_matches,
            "grants": privileges,
            "runtime_select_insert": (
                "UNKNOWN"
                if isinstance(privileges, str)
                else {item: item in privileges[RUNTIME_ROLE] for item in ("SELECT", "INSERT")}
            ),
            "migration_select": (
                "UNKNOWN" if isinstance(privileges, str) else "SELECT" in privileges[MIGRATION_ROLE]
            )
            if name == "GOVERNED_SOURCE_RECORD_REVISIONS"
            else "not required",
            "conflicting_grants": conflicting_grants,
            "owned_by_migration_role": (
                "UNKNOWN"
                if not _value(table, "owner")
                else _value(table, "owner") == MIGRATION_ROLE
            ),
        }
    result["tables"] = tables

    if result["ledger"]["v103_source_matches"] is False:
        disposition = "LEDGER_SOURCE_MISMATCH"
    elif (
        result["ledger"]["v103_present"] is False
        or any(
            (table.get("exists") is True and table.get("table_type") != "TABLE")
            or table.get("definition_matches_v103") is False
            or table.get("owned_by_migration_role") is False
            or table.get("conflicting_grants") is True
            or (
                isinstance(table.get("runtime_select_insert"), dict)
                and not all(table["runtime_select_insert"].values())
            )
            or table.get("migration_select") is False
            for table in tables.values()
        )
        or result["schema"]["managed_access"] is True
        or (bool(schema) and result["schema"]["owner"] != "ACCOUNTADMIN")
        or result["schema"]["migration_create_table"] is False
        or result["schema"]["runtime_role_visible"] is False
    ):
        disposition = "APPLIED_STATE_MISMATCH"
    elif (
        any(table["exists"] is not True for table in tables.values())
        or any(
            table.get("definition_matches_v103") == "UNKNOWN"
            or table.get("grants") == "UNKNOWN"
            or table.get("owned_by_migration_role") == "UNKNOWN"
            for table in tables.values()
        )
        or ledger is None
        or result["ledger"]["v103_source_matches"] == "UNKNOWN"
        or not schema
        or schema_grants is None
        or result["schema"]["runtime_role_visible"] == "UNKNOWN"
    ):
        disposition = "INSUFFICIENT_VISIBILITY"
    else:
        disposition = "VERIFIED_APPLIED"
    result["disposition"] = disposition
    return result


def _snow_query(config_file: Path, sql: str) -> list[dict[str, Any]]:
    if not READ_ONLY_SQL.match(sql) or ";" in sql:
        raise ValueError("V103 diagnostic accepts one read-only metadata statement")
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
    )
    if completed.returncode != 0:
        raise RuntimeError("Read-only metadata query unavailable")
    rows = json.loads(completed.stdout)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise RuntimeError("Unexpected Snowflake metadata response")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-file", type=Path, required=True)
    args = parser.parse_args()
    result = diagnose(
        lambda sql: _snow_query(args.config_file, sql),
        os.environ.get("SNOWFLAKE_WAREHOUSE", ""),
        os.environ.get("GITHUB_SHA", "UNKNOWN"),
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["disposition"] != "IDENTITY_MISMATCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
