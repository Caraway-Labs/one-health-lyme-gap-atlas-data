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
    f"{DATABASE}.GOVERNANCE."
    "PURGE_INTELLIGENCE_RAW_CHECKPOINT(VARCHAR,VARCHAR,VARCHAR,VARCHAR)"
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
    except Exception:
        result["reason"] = "IDENTITY_UNAVAILABLE"
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
        except Exception:
            result["objects"].append(
                {
                    "object": target,
                    "status": "UNKNOWN",
                    "reason": "QUERY_UNAVAILABLE",
                    "owner": None,
                    "grants": [],
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
        if completed.returncode or len(completed.stdout.encode()) > 1_048_576:
            raise ValueError("QUERY_UNAVAILABLE")
        rows = json.loads(completed.stdout)
        if (
            not isinstance(rows, list)
            or not all(isinstance(row, dict) for row in rows)
            or len(rows) > 64
        ):
            raise ValueError("RESPONSE_LIMIT_OR_SHAPE")
        return rows
    except Exception:
        raise RuntimeError("DEV_OWNERSHIP_QUERY_UNAVAILABLE") from None


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
