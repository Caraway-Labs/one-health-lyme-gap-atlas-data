"""Fixed current-state DEV metadata report; no handoff or source-state assertions."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
ROLE = "OH_LYME_DEV_MIGRATION_DEPLOYER"
USER = "OH_LYME_DEV_MIGRATION_DEPLOY_SVC"
WAREHOUSE = "OH_LYME_DEV_INGEST_XS_WH"
MODE = "report_dev_cleanup_ownership"
PROCEDURE = (
    f"{DATABASE}.GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(VARCHAR,VARCHAR,VARCHAR,VARCHAR)"
)
VIEW = f"{DATABASE}.GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_EXPECTED_HANDOFF_V"
IDENTITY_SQL = (
    "SELECT CURRENT_USER() AS USER_NAME,CURRENT_ROLE() AS ROLE_NAME,"
    "CURRENT_DATABASE() AS DATABASE_NAME,CURRENT_WAREHOUSE() AS WAREHOUSE_NAME"
)
OBJECT_SQL = {
    PROCEDURE: f"SHOW GRANTS ON PROCEDURE {PROCEDURE}",
    VIEW: f"SHOW GRANTS ON VIEW {VIEW}",
}
ALLOWED_SQL = frozenset({IDENTITY_SQL, *OBJECT_SQL.values()})
Query = Callable[[str], list[dict[str, Any]]]
EXPECTED_OWNERS = {
    "migration_deployer": ROLE,
    "purge_owner": "OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER",
}


class QueryFailure(RuntimeError):
    def __init__(self, category: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("DEV_OWNERSHIP_QUERY_UNAVAILABLE")
        self.details = {
            "category": category,
            "error_code": None,
            "sqlstate": None,
            "query_id": None,
            "meaning": "Diagnostic failed; no access conclusion can be drawn.",
            **(details or {}),
        }


def cli_error_details(stdout: str, stderr: str) -> dict[str, Any]:
    """Keep only validated identifiers and fixed explanations, never provider prose."""
    text = (stderr + "\n" + stdout)[:16384]
    match = re.search(r"\b([0-9]{6})\s*\(([A-Z0-9]{5})\)", text)
    code, state = match.groups() if match else (None, None)
    query_match = re.search(
        r"(?i)\b(?:query[_ ]?id|sfqid)\s*[:=]\s*"
        r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\b",
        text,
    )
    query_id = query_match.group(1).lower() if query_match else None
    for candidate in (stderr, stdout):
        try:
            payload = json.loads(candidate) if len(candidate) <= 16384 else None
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        raw_code = payload.get("errno", payload.get("error_code"))
        if type(raw_code) is int and 0 <= raw_code <= 999999:
            raw_code = f"{raw_code:06d}"
        if isinstance(raw_code, str) and re.fullmatch(r"[0-9]{6}", raw_code):
            code = raw_code
        raw_state = payload.get("sqlstate")
        if isinstance(raw_state, str) and re.fullmatch(r"[A-Z0-9]{5}", raw_state):
            state = raw_state
        raw_id = payload.get("sfqid", payload.get("query_id"))
        if isinstance(raw_id, str) and re.fullmatch(
            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", raw_id
        ):
            query_id = raw_id.lower()
    meaning = "CLI query failed; provider message withheld; cause remains unresolved."
    if code == "002003":
        meaning = "Object does not exist or is not authorized; these causes are not distinguished."
    elif code == "001003":
        meaning = "SQL compilation/syntax error; inspect the fixed query formulation."
    elif state == "42501":
        meaning = "Insufficient privilege reported; this does not authorize a grant or role change."
    elif state and state.startswith("08"):
        meaning = "Connection/session error; object visibility was not established."
    return {"error_code": code, "sqlstate": state, "query_id": query_id, "meaning": meaning}


def failure_details(error: Exception) -> dict[str, Any]:
    return (
        error.details
        if isinstance(error, QueryFailure)
        else QueryFailure("UNEXPECTED_ERROR").details
    )


def validate_dispatch(inputs: Any, ref: str) -> None:
    if (
        ref != "refs/heads/main"
        or not isinstance(inputs, dict)
        or not (inputs.get(MODE) is True or inputs.get(MODE) == "true")
        or any(
            value not in (None, False, "false", "") for key, value in inputs.items() if key != MODE
        )
    ):
        raise ValueError("DEV_OWNERSHIP_REPORT_MODE_CONFLICT")


def value(row: dict[str, Any], key: str) -> Any:
    return next((v for k, v in row.items() if k.upper() == key.upper()), None)


def token(item: Any) -> str | None:
    return (
        item
        if isinstance(item, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_ .:-]{0,127}", item)
        else None
    )


def object_report(target: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) > 64:
        return {
            "object": target,
            "status": "UNKNOWN",
            "reason": "RESPONSE_LIMIT",
            "owner": None,
            "grants": [],
            "owner_matches_expected": {label: None for label in EXPECTED_OWNERS},
        }
    grants = []
    valid = True
    for row in rows:
        privilege, grantee_type = token(value(row, "privilege")), token(value(row, "granted_to"))
        grantee = token(value(row, "grantee_name")) if grantee_type == "ROLE" else None
        option = str(value(row, "grant_option")).lower()
        valid &= (
            privilege is not None
            and grantee_type is not None
            and grantee is not None
            and option in {"true", "false"}
        )
        grants.append(
            {
                "privilege": privilege,
                "granted_to": grantee_type,
                "grantee_name": grantee,
                "grant_option": option == "true" if option in {"true", "false"} else None,
            }
        )
    owners = [
        row["grantee_name"]
        for row in grants
        if row["privilege"] == "OWNERSHIP" and row["grantee_name"]
    ]
    visible = valid and len(owners) == 1
    return {
        "object": target,
        "status": "VISIBLE" if visible else "UNKNOWN",
        "reason": "CURRENT_METADATA" if visible else "PARTIAL_OR_NOT_VISIBLE",
        "owner": owners[0] if len(owners) == 1 else None,
        "owner_matches_expected": {
            label: owners[0] == expected if visible else None
            for label, expected in EXPECTED_OWNERS.items()
        },
        "grants": grants,
    }


def report(query: Query) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "BLOCKED", "writes": False, "objects": []}
    try:
        rows = query(IDENTITY_SQL)
        identity = rows[0] if len(rows) == 1 else {}
        result["identity_matches"] = {
            key: value(identity, key) == expected
            for key, expected in (
                ("USER_NAME", USER),
                ("ROLE_NAME", ROLE),
                ("DATABASE_NAME", DATABASE),
                ("WAREHOUSE_NAME", WAREHOUSE),
            )
        }
    except Exception as error:
        result["reason"] = "IDENTITY_UNAVAILABLE"
        result["error"] = failure_details(error)
        return result
    if not all(result["identity_matches"].values()):
        result["reason"] = "IDENTITY_MISMATCH"
        return result
    for target, sql in OBJECT_SQL.items():
        try:
            rows = query(sql)
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise ValueError("INVALID_METADATA_SHAPE")
            result["objects"].append(object_report(target, rows))
        except Exception as error:
            result["objects"].append(
                {
                    "object": target,
                    "status": "UNKNOWN",
                    "reason": "QUERY_UNAVAILABLE",
                    "owner": None,
                    "grants": [],
                    "owner_matches_expected": {label: None for label in EXPECTED_OWNERS},
                    "error": failure_details(error),
                }
            )
    result["status"] = (
        "COMPLETE" if all(row["status"] == "VISIBLE" for row in result["objects"]) else "PARTIAL"
    )
    return result


def snow_query(config_file: Path, sql: str) -> list[dict[str, Any]]:
    if sql not in ALLOWED_SQL:
        raise ValueError("STATEMENT_NOT_ALLOWLISTED")
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
            timeout=15,
        )
        if completed.returncode:
            raise QueryFailure("CLI_ERROR", cli_error_details(completed.stdout, completed.stderr))
        if len(completed.stdout.encode()) > 1_048_576:
            raise QueryFailure("RESPONSE_LIMIT", {"meaning": "Response exceeded the 1 MiB bound."})
        try:
            rows = json.loads(completed.stdout)
        except ValueError:
            raise QueryFailure("INVALID_JSON", {"meaning": "CLI returned invalid JSON."}) from None
        if (
            not isinstance(rows, list)
            or not all(isinstance(row, dict) for row in rows)
            or len(rows) > 64
        ):
            raise QueryFailure(
                "RESPONSE_LIMIT_OR_SHAPE",
                {"meaning": "Unexpected metadata shape or more than 64 rows."},
            )
        return rows
    except QueryFailure:
        raise
    except subprocess.TimeoutExpired:
        raise QueryFailure(
            "TIMEOUT", {"meaning": "The fixed query did not complete within 15 seconds."}
        ) from None
    except Exception:
        raise QueryFailure(
            "CLI_EXECUTION_ERROR",
            {"meaning": "CLI execution/response processing failed; SQL completion is unverified."},
        ) from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--config-file", type=Path)
    group.add_argument("--validate-event", type=Path)
    parser.add_argument("--ref")
    args = parser.parse_args()
    if args.validate_event:
        try:
            if args.validate_event.stat().st_size > 1_048_576:
                raise ValueError()
            validate_dispatch(json.loads(args.validate_event.read_text()).get("inputs"), args.ref)
        except Exception:
            raise SystemExit("DEV_OWNERSHIP_REPORT_MODE_CONFLICT") from None
        return 0
    watchdog = threading.Timer(60, lambda: os._exit(124))
    watchdog.daemon = True
    watchdog.start()
    try:
        result = report(lambda sql: snow_query(args.config_file, sql))
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "COMPLETE" else 2
    finally:
        watchdog.cancel()


if __name__ == "__main__":
    raise SystemExit(main())
