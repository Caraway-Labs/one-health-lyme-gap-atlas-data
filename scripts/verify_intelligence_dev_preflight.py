"""Fixed read-only DEV intelligence metadata preflight; private evidence only."""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from lyme_gap_atlas_data.climate_dev_validation import DEV, ROLE, USER, WAREHOUSE

TARGETS = (
    ("TABLE", "GOVERNANCE", "INTELLIGENCE_RAW_RETENTION_DOCUMENTS"),
    ("TABLE", "GOVERNANCE", "INTELLIGENCE_RAW_RETENTION_AUDIT"),
    ("TABLE", "GOVERNANCE", "INTELLIGENCE_SOURCE_VERSIONS"),
    ("VIEW", "PRESENTATION", "INTELLIGENCE_FEED_V"),
    ("VIEW", "PRESENTATION", "INTELLIGENCE_FEED_V2"),
)


def budget(confirmation: str) -> None:
    # Private dollar/price/request receipts stay outside public Actions inputs/logs.
    # This confirms prior independent reconciliation, not billing measurement.
    if confirmation != "true":
        raise ValueError("FEED_PRIVATE_ACCOUNTING_CONFIRMATION_REQUIRED")


def rows(cursor: Any) -> list[dict[str, Any]]:
    return [
        dict(zip([column[0] for column in cursor.description], row, strict=True))
        for row in cursor.fetchall()
    ]


def view_matches(name: str, actual: str) -> bool:
    source = (
        Path(__file__).parents[1] / "docs/contracts/intelligence/v2/presentation-projection.sql"
    ).read_text()
    proposals = re.split(r"(?=CREATE (?:OR REPLACE )?VIEW\b)", source)[1:]
    proposal = next(
        part
        for part in proposals
        if re.match(
            r"CREATE (?:OR REPLACE )?VIEW (?:IF NOT EXISTS )?PRESENTATION\." + name + r"\b", part
        )
    )
    proposal = proposal.split(";", 1)[0]

    def tokens(ddl: str) -> list[str]:
        ddl = re.sub(r"--[^\n]*", "", ddl)
        body = re.split(r"\bAS\s+SELECT\b", ddl, maxsplit=1, flags=re.I)[1]
        # Conservative exact token equivalence. Formatting/case of unquoted SQL
        # may vary; literals remain exact. Any qualification/quoting mismatch
        # requires review rather than automatically replacing a live object.
        return [
            part if part.startswith("'") else part.upper()
            for part in re.findall(r"'(?:''|[^'])*'|[A-Za-z_][A-Za-z_0-9]*|[^\s;]", body)
        ]

    return tokens(actual) == tokens(proposal)


def inspect(cursor: Any, report: dict[str, Any]) -> None:
    cursor.execute(
        "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=10, STATEMENT_QUEUED_TIMEOUT_IN_SECONDS=2"
    )
    cursor.execute(
        "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()", timeout=10
    )
    if tuple(cursor.fetchone()) != (USER, ROLE, DEV, WAREHOUSE):
        raise ValueError("FEED_PREFLIGHT_IDENTITY")
    report["identity_matches_expected"] = True
    objects: list[dict[str, Any]] = []
    report["objects"] = objects
    for kind, schema, name in TARGETS:
        qualified = f"{DEV}.{schema}.{name}"
        cursor.execute(f"SHOW {kind}S LIKE '{name}' IN SCHEMA {DEV}.{schema}", timeout=10)
        catalog = [row for row in rows(cursor) if str(row.get("name", row.get("NAME"))) == name]
        entry: dict[str, Any] = {
            "target": name,
            "kind": kind,
            "state": "VISIBLE" if catalog else "NOT_VISIBLE_NOT_PROOF_OF_ABSENCE",
            "inspection_complete": False,
        }
        objects.append(entry)
        print(json.dumps(report, sort_keys=True), flush=True)
        if catalog:
            owner = catalog[0].get("owner", catalog[0].get("OWNER"))
            entry["owner_matches_expected"] = owner == ROLE
            cursor.execute(f"DESCRIBE {kind} {qualified}", timeout=10)
            columns = rows(cursor)
            entry["columns_inspected"] = bool(columns)
            print(json.dumps(report, sort_keys=True), flush=True)
            cursor.execute(f"SHOW GRANTS ON {kind} {qualified}", timeout=10)
            grants = rows(cursor)
            entry["grants_inspected"] = bool(grants)
            print(json.dumps(report, sort_keys=True), flush=True)
            # Do not expose names, privileges, definitions, source records or hashes.
            if kind == "VIEW":
                cursor.execute(f"SELECT GET_DDL('VIEW','{qualified}')", timeout=10)
                ddl = cursor.fetchone()[0]
                entry["definition_inspected"] = bool(ddl)
                version = "1.0.0" if name == "INTELLIGENCE_FEED_V" else "2.0.0"
                entry["expected_version_literal_present"] = f"'{version}'" in ddl
                entry["exact_reviewed_definition_matches"] = view_matches(name, ddl)
        entry["inspection_complete"] = True
        print(json.dumps(report, sort_keys=True), flush=True)
    report["writes"] = False
    report["source_registration_authorized"] = False


def terminate(report: dict[str, Any]) -> None:
    # Termination performs no evidence I/O. Progress was emitted as it completed.
    # Even a blocked/broken stdout or artifact filesystem cannot prevent exit.
    os._exit(124)


def main() -> None:
    budget(os.environ.get("FEED_PREFLIGHT_ACCOUNTING_CONFIRMED", "false"))
    report: dict[str, Any] = {"state": "FAILED", "objects": [], "writes": False}

    def expire() -> None:
        terminate(report)

    watchdog = threading.Timer(50, expire)
    watchdog.daemon = True
    watchdog.start()
    try:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            inspect(cursor, report)
        report["state"] = "COMPLETE"
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        raise SystemExit("FEED_PREFLIGHT_FAILED") from None
    finally:
        print(json.dumps(report, sort_keys=True), flush=True)
        watchdog.cancel()


if __name__ == "__main__":
    main()
