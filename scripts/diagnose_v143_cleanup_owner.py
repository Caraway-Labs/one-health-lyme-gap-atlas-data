"""Fixed read-only V143 owner readback before the separate security handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from lyme_gap_atlas_data.migrations import DEV_DATABASE, load_migrations

USER = "OH_LYME_DEV_MIGRATION_DEPLOY_SVC"
ROLE = "OH_LYME_DEV_MIGRATION_DEPLOYER"
WAREHOUSE = "OH_LYME_DEV_INGEST_XS_WH"
VERSION = "V143"
FILENAME = "V143__dev_intelligence_raw_cleanup_authority.sql"
MIGRATION_SHA256 = "a92157ddac0d7b087b6c93f7fff65c65a081dd1e1aea0b5918a4e604a2a52968"
BODY_SHA256 = "d994b73843b7011174be69b64620434a4333bcd54e25be5807681f5739f72703"
CREATED_ON = "2026-10-08T21:30:14.635000-07:00"
SCHEMA = f"{DEV_DATABASE}.GOVERNANCE"
PROCEDURE = f"{SCHEMA}.PURGE_INTELLIGENCE_RAW_CHECKPOINT"
SIGNATURE = "PURGE_INTELLIGENCE_RAW_CHECKPOINT(VARCHAR, VARCHAR, VARCHAR, VARCHAR) RETURN VARCHAR"

IDENTITY_SQL = (
    "SELECT CURRENT_USER() AS USER_NAME, CURRENT_ROLE() AS ROLE_NAME, "
    "CURRENT_DATABASE() AS DATABASE_NAME, CURRENT_WAREHOUSE() AS WAREHOUSE_NAME"
)
LEDGER_SQL = f"SELECT VERSION,FILENAME,SHA256 FROM {SCHEMA}.SCHEMA_MIGRATIONS WHERE VERSION='V143'"
PROCEDURE_SQL = f"SHOW PROCEDURES LIKE 'PURGE_INTELLIGENCE_RAW_CHECKPOINT' IN SCHEMA {SCHEMA}"
GRANTS_SQL = f"SHOW GRANTS ON PROCEDURE {PROCEDURE}(VARCHAR,VARCHAR,VARCHAR,VARCHAR)"
DEFINITION_SQL = (
    "SELECT PROCEDURE_OWNER,PROCEDURE_DEFINITION FROM "
    f"{DEV_DATABASE}.INFORMATION_SCHEMA.PROCEDURES "
    "WHERE PROCEDURE_SCHEMA='GOVERNANCE' "
    "AND PROCEDURE_NAME='PURGE_INTELLIGENCE_RAW_CHECKPOINT'"
)
DDL_SQL = f"SELECT GET_DDL('PROCEDURE', '{PROCEDURE}(VARCHAR,VARCHAR,VARCHAR,VARCHAR)') AS DDL"
VIEW_SQL = f"SHOW VIEWS LIKE 'INTELLIGENCE_RAW_CLEANUP_EXPECTED_HANDOFF_V' IN SCHEMA {SCHEMA}"
APPROVALS_SQL = f"SELECT COUNT(*) AS ROW_COUNT FROM {SCHEMA}.INTELLIGENCE_RAW_CLEANUP_APPROVALS"
ATTESTATIONS_SQL = (
    f"SELECT COUNT(*) AS ROW_COUNT FROM {SCHEMA}.INTELLIGENCE_RAW_CLEANUP_HANDOFF_ATTESTATIONS"
)
ALLOWED_SQL = frozenset(
    (
        IDENTITY_SQL,
        LEDGER_SQL,
        PROCEDURE_SQL,
        GRANTS_SQL,
        DEFINITION_SQL,
        DDL_SQL,
        VIEW_SQL,
        APPROVALS_SQL,
        ATTESTATIONS_SQL,
    )
)
Query = Callable[[str], list[dict[str, Any]]]


def _value(row: dict[str, Any], column: str) -> Any:
    return next((value for key, value in row.items() if key.upper() == column.upper()), None)


def _creation_matches(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        observed = datetime.fromisoformat(value)
    except ValueError:
        try:
            observed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f %z")
        except ValueError:
            return False
    return observed.tzinfo is not None and observed == datetime.fromisoformat(CREATED_ON)


def _reviewed_source() -> tuple[str, str]:
    migrations = [item for item in load_migrations() if item.version == VERSION]
    if len(migrations) != 1:
        raise ValueError("V143 source unavailable")
    migration = migrations[0]
    if (migration.filename, migration.sha256) != (FILENAME, MIGRATION_SHA256):
        raise ValueError("V143 source changed")
    body_match = re.search(
        r"\bCREATE PROCEDURE GOVERNANCE\.PURGE_INTELLIGENCE_RAW_CHECKPOINT\("
        r".*?\bAS\s*\$\$(.*?)\$\$;",
        migration.source,
        re.S,
    )
    view_match = re.search(
        r"CREATE VIEW GOVERNANCE\.INTELLIGENCE_RAW_CLEANUP_EXPECTED_HANDOFF_V AS\b.*?;",
        migration.source,
        re.S,
    )
    if body_match is None or view_match is None:
        raise ValueError("Reviewed V143 definition unavailable")
    body = body_match.group(1).strip()
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != BODY_SHA256:
        raise ValueError("Reviewed V143 body hash changed")
    return body, view_match.group(0).strip()


def diagnose(query: Query, expected_warehouse: str) -> dict[str, Any]:
    """Return only non-sensitive match evidence; every missing read fails closed."""
    result: dict[str, Any] = {"disposition": "FAIL", "writes": False}
    try:
        rows = query(IDENTITY_SQL)
    except (RuntimeError, ValueError, TypeError):
        result["reason"] = "IDENTITY_UNAVAILABLE"
        return result
    identity = rows[0] if len(rows) == 1 else {}
    result["identity_matches"] = {
        "user": _value(identity, "USER_NAME") == USER,
        "role": _value(identity, "ROLE_NAME") == ROLE,
        "database": _value(identity, "DATABASE_NAME") == DEV_DATABASE,
        "warehouse": expected_warehouse == WAREHOUSE
        and _value(identity, "WAREHOUSE_NAME") == WAREHOUSE,
    }
    if not all(result["identity_matches"].values()):
        result["reason"] = "IDENTITY_MISMATCH"
        return result

    try:
        expected_body, expected_view = _reviewed_source()
        ledger = query(LEDGER_SQL)
        procedures = query(PROCEDURE_SQL)
        grants = query(GRANTS_SQL)
        definitions = query(DEFINITION_SQL)
        ddl_rows = query(DDL_SQL)
        views = query(VIEW_SQL)
        approvals = query(APPROVALS_SQL)
        attestations = query(ATTESTATIONS_SQL)
    except (RuntimeError, ValueError, TypeError):
        result["reason"] = "SOURCE_OR_READ_UNAVAILABLE"
        return result

    procedure = procedures[0] if len(procedures) == 1 else {}
    definition = definitions[0] if len(definitions) == 1 else {}
    ddl = _value(ddl_rows[0], "DDL") if len(ddl_rows) == 1 else None
    live_body = _value(definition, "PROCEDURE_DEFINITION")
    live_body_hash = (
        hashlib.sha256(live_body.strip().encode("utf-8")).hexdigest()
        if isinstance(live_body, str) and live_body.strip()
        else None
    )
    view = views[0] if len(views) == 1 else {}
    result.update(
        source_sha256=MIGRATION_SHA256,
        expected_body_sha256=BODY_SHA256,
        observed_body_sha256=live_body_hash,
        created_on=_value(procedure, "created_on"),
        owner=_value(grants[0], "grantee_name") if len(grants) == 1 else None,
        signature=_value(procedure, "arguments"),
        approval_rows=_value(approvals[0], "ROW_COUNT") if len(approvals) == 1 else None,
        attestation_rows=_value(attestations[0], "ROW_COUNT") if len(attestations) == 1 else None,
    )
    checks = {
        "ledger": len(ledger) == 1
        and all(
            _value(ledger[0], key) == expected
            for key, expected in (
                ("VERSION", VERSION),
                ("FILENAME", FILENAME),
                ("SHA256", MIGRATION_SHA256),
            )
        ),
        "signature_and_creation": (
            len(procedures) == 1
            and _value(procedure, "name") == "PURGE_INTELLIGENCE_RAW_CHECKPOINT"
            and _value(procedure, "catalog_name") == DEV_DATABASE
            and _value(procedure, "schema_name") == "GOVERNANCE"
            and _value(procedure, "min_num_arguments") == 4
            and _value(procedure, "max_num_arguments") == 4
            and _value(procedure, "arguments") == SIGNATURE
            and _creation_matches(_value(procedure, "created_on"))
        ),
        "owner_and_no_executor_usage": (
            len(grants) == 1
            and _value(grants[0], "privilege") == "OWNERSHIP"
            and _value(grants[0], "grantee_name") == ROLE
            and _value(grants[0], "granted_to") == "ROLE"
            and str(_value(grants[0], "grant_option")).lower() == "true"
            and _value(definition, "PROCEDURE_OWNER") == ROLE
        ),
        "body": live_body_hash == BODY_SHA256 and live_body.strip() == expected_body
        if isinstance(live_body, str) and live_body.strip()
        else False,
        "owner_rights": (
            isinstance(ddl, str)
            and len(ddl) > len(expected_body)
            and "EXECUTE AS OWNER" in ddl.upper()
            and "INTELLIGENCE_RAW_DELETE_SCOPE_INVALID" in ddl
        ),
        "expected_handoff_view": (
            len(views) == 1
            and _value(view, "name") == "INTELLIGENCE_RAW_CLEANUP_EXPECTED_HANDOFF_V"
            and _value(view, "owner") == ROLE
            and isinstance(_value(view, "text"), str)
            and _value(view, "text").strip() == expected_view
        ),
        "empty_approval_and_attestation": (
            type(result["approval_rows"]) is int
            and result["approval_rows"] == 0
            and type(result["attestation_rows"]) is int
            and result["attestation_rows"] == 0
        ),
    }
    result["checks"] = checks
    result["disposition"] = "PASS" if all(checks.values()) else "FAIL"
    result["reason"] = (
        "EXACT_V143_OWNER_READBACK" if result["disposition"] == "PASS" else "V143_OWNER_MISMATCH"
    )
    return result


def _snow_query(config_file: Path, sql: str) -> list[dict[str, Any]]:
    if sql not in ALLOWED_SQL:
        raise ValueError("Only fixed read-only V143 owner queries are allowed")
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
        raise RuntimeError("V143 owner query timed out") from exc
    if completed.returncode != 0:
        raise RuntimeError("V143 owner query unavailable")
    rows = json.loads(completed.stdout)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise RuntimeError("Unexpected Snowflake response")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-file", type=Path, required=True)
    args = parser.parse_args()
    result = diagnose(
        lambda sql: _snow_query(args.config_file, sql), os.environ.get("SNOWFLAKE_WAREHOUSE", "")
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["disposition"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
