"""Fixed eighteen-statement DEV metadata inspection; no repair or data queries."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import sqlglot

from . import climate_membership_diagnostic as bounds
from .climate_dev_validation import DEV, ROLE, USER, WAREHOUSE
from .migrations import (
    LEGACY_DEV_MIGRATION_CHECKSUMS,
    REQUIRED_REGISTRATION_COLUMNS,
    is_line_ending_equivalent_checksum,
    load_migrations,
    migration_plan,
)

ROOT = Path(__file__).resolve().parents[2]
SQL_PATH = ROOT / "docs/contracts/climate/v147-dev-execution-preflight.sql"
SQL_SHA256 = "60d72d286304929d1e501e686f18aaa4b8883864d7f8c35eb1bdccba6d6144ad"
V147 = {
    "version": "V147",
    "filename": "V147__dev_climate_scalar_membership_join.sql",
    "sha256": "22caabb8abb205316005d866286d7adb995a0b7dc5ec8b05aa6c6f053dfca83b",
}
NAMES = (
    "identity",
    "warehouse",
    "role_permissions",
    "schema_permissions",
    "observation_ownership",
    "metadata_ownership",
    "observation_definition",
    "metadata_definition",
    "migration_ledger",
    "legacy_reconciliation",
    "registration_columns",
    "revision_permissions",
    "release_permissions",
    "pointer_permissions",
    "ledger_permissions",
    "reconciliation_permissions",
    "observation_columns",
    "metadata_columns",
)


class Stop(ValueError):
    pass


def require(condition: bool, category: str) -> None:
    if not condition:
        raise Stop(category)


def statements() -> list[str]:
    source = SQL_PATH.read_text(encoding="utf-8")
    require(hashlib.sha256(source.encode()).hexdigest() == SQL_SHA256, "SQL_SCOPE_CHANGED")
    sql = re.sub(r"--[^\n]*", "", source)
    result = [part.strip() for part in sql.split(";") if part.strip()]
    require(len(result) == 18, "STATEMENT_LIMIT")
    require(all(re.match(r"^(SELECT|SHOW|DESCRIBE)\b", s) for s in result), "READ_ONLY_SCOPE")
    return result


def receipt(code_sha: str) -> dict[str, Any]:
    return {
        "mode": "V147_DEV_METADATA_PREFLIGHT_ONLY",
        "code_sha": code_sha,
        "status": "BLOCKED",
        "sql_sha256": SQL_SHA256,
        "approved_maximum_usd": 7,
        "reserved_forecast_usd": None,
        "pricing_assumptions": {
            "unit_price_usd": None,
            "basis": "OWNER_SUPPLIED_FORECAST_REQUIRED_NOT_ACCOUNT_INVOICE",
            "actual_billed_unit_price_usd": None,
            "actual_billed_cost_usd": None,
            "usage": "NOT_QUERIED_NO_EXTRA_STATEMENTS",
        },
        "checks": [
            {"ordinal": i + 1, "name": name, "status": "NOT_EXECUTED"}
            for i, name in enumerate(NAMES)
        ],
        "statements_executed": 0,
        "pending_migrations": None,
        "v149_excluded": None,
        "sole_v147_ready": False,
    }


def prepare_evidence(document: str, report: dict[str, Any]) -> dict[str, Any]:
    """Validate reviewed owner input and the forward cap before authentication."""
    evidence = bounds.budget_evidence(document)
    price = evidence["unit_price_usd"]
    forecast = (315 * 5.75 / 3600 + 20 * 1.35 / 60) * price + 1
    report["reserved_forecast_usd"] = forecast
    report["pricing_assumptions"].update(
        unit_price_usd=price,
        basis=evidence["basis"],
        evidence_reference=evidence["evidence_reference"],
        verified_at=evidence["verified_at"],
    )
    report["owner_evidence_sha256"] = hashlib.sha256(document.encode()).hexdigest()
    require(forecast <= report["approved_maximum_usd"], "FORECAST_CAP")
    return evidence


def grants(rows: list[dict[str, Any]], roles: set[str], privileges: set[str]) -> bool:
    return any(
        str(row.get("grantee_name")) in roles
        and row.get("granted_to") == "ROLE"
        and row.get("privilege") in privileges
        for row in rows
    )


def column_contract(index: int) -> list[tuple[str, str]]:
    source = (ROOT / "sql/january_climate_consumer_views.sql").read_text()
    tree = sqlglot.parse(source, read="snowflake")[index]
    assert tree is not None
    names = [expression.alias_or_name.upper() for expression in tree.expression.expressions]
    variant = {
        "VALUE",
        "EXPECTED_AREA_M2",
        "INTERSECTED_AREA_M2",
        "SOURCE_SUPPORTED_AREA_M2",
        "VALID_AREA_M2",
        "SOURCE_COVERAGE_FRACTION",
        "VALID_FRACTION_OF_SUPPORTED_AREA",
        "LIMITATIONS",
        "ALLOWED_VALUE_STATES",
    }
    types = {
        "PERIOD_START": "DATE",
        "PERIOD_END": "DATE",
        "SOURCE_TIME_PRESENT": "BOOLEAN",
        "ATLAS_ACQUIRED_AT": "TIMESTAMP_LTZ",
        "SOURCE_PUBLISHED_AT": "TIMESTAMP_TZ",
    }
    return [
        (
            name,
            "VARIANT"
            if name in variant
            else "FLOAT"
            if name.endswith("_NATIVE_DOUBLE")
            else types.get(name, "VARCHAR"),
        )
        for name in names
    ]


def validate(
    index: int,
    rows: list[dict[str, Any]],
    report: dict[str, Any],
    state: dict[str, Any],
    helpers: dict[str, Any],
) -> dict[str, Any]:
    check: dict[str, Any] = {"row_count": len(rows)}
    roles = state.setdefault("roles", {ROLE})
    if index == 0:
        identity = tuple(rows[0].values()) if len(rows) == 1 else ()
        require(
            len(identity) == 6 and identity[:4] == (USER, ROLE, DEV, WAREHOUSE),
            "EFFECTIVE_IDENTITY_MISMATCH",
        )
        evidence = helpers["budget_evidence"]
        require(identity[4] == evidence["region"], "REGION_BINDING")
        capability = evidence.get("standard_capability_evidence")
        if capability:
            require(str(identity[4]).split("_", 1)[0] == capability["cloud"], "CLOUD_BINDING")
            bounds.verify_donor_account_binding(
                {
                    "account_locator_sha256": capability["account_locator_sha256"],
                    "region": evidence["region"],
                },
                identity,
            )
            report["standard_capability_binding"] = "MATCHED_LIVE_ACCOUNT"
        state["region"] = identity[4]
    elif index == 1:
        require(len(rows) == 1 and rows[0].get("name") == WAREHOUSE, "WAREHOUSE_VISIBILITY")
        warehouse = rows[0]
        fields = (
            "size",
            "type",
            "generation",
            "max_cluster_count",
            "min_cluster_count",
            "enable_query_acceleration",
            "auto_suspend",
        )
        allowed = {"X-Small", "STANDARD", "1", "2", "GEN_1", "GEN_2", "GEN1", "GEN2"}
        check["configuration"] = {
            key: {
                "present": key in warehouse,
                "value": value
                if value is None
                or type(value) in (bool, int, float)
                or isinstance(value, str)
                and value in allowed
                else "UNRECOGNIZED",
            }
            for key in fields
            for value in (warehouse.get(key),)
        }
        report["warehouse_configuration"] = check["configuration"]
        # Reuse the already-reviewed January entitlement bound. Missing fields
        # remain missing; this never writes observed defaults into the receipt.
        bounds.validate_warehouse_cost(
            warehouse, helpers["budget_evidence"], state["region"], report
        )
        if not helpers["budget_evidence"].get("standard_capability_evidence") and (
            type(warehouse.get("min_cluster_count")) is not int
            or warehouse["min_cluster_count"] != 1
        ):
            report["warehouse_cost_failed_fields"] = ["min_cluster_count"]
            raise Stop("WAREHOUSE_COST_ASSUMPTIONS_UNVERIFIED")
    elif index == 2:
        require(bool(rows), "ROLE_PERMISSION_VISIBILITY")
        roles.update(
            str(row["name"])
            for row in rows
            if row.get("granted_on") == "ROLE"
            and row.get("privilege") == "USAGE"
            and row.get("grantee_name") == ROLE
            and row.get("granted_to") == "ROLE"
        )
    elif index in (3, 4, 5, 11, 12, 13, 14, 15):
        needed = (
            {"OWNERSHIP", "CREATE VIEW"}
            if index == 3
            else (
                {"OWNERSHIP"}
                if index in (4, 5)
                else {"OWNERSHIP", "INSERT"}
                if index == 14
                else {"OWNERSHIP", "SELECT"}
            )
        )
        check["required_privilege_verified"] = grants(rows, roles, needed)
        require(check["required_privilege_verified"], "PERMISSION_OR_OWNERSHIP_UNVERIFIED")
        if index in (4, 5):
            check["ownership_verified"] = True
            check["existing_grants"] = sorted({str(row.get("privilege")) for row in rows})
    elif index in (6, 7):
        require(len(rows) == 1, "VIEW_DEFINITION_VISIBILITY")
        ddl = next(iter(rows[0].values()))
        old = (ROOT / "sql/january_climate_consumer_views.sql").read_text()
        expected = helpers["proposals"](old)[index - 6]
        require(isinstance(ddl, str), "VIEW_DEFINITION_TYPE")
        check["ddl_sha256"] = hashlib.sha256(ddl.encode()).hexdigest()
        check["normalized_body_matches_v136"] = helpers["body"](ddl) == helpers["body"](expected)
        require(check["normalized_body_matches_v136"], "UNEXPECTED_VIEW_DEFINITION")
    elif index == 8:
        require(len(rows) <= 150, "LEDGER_ROW_LIMIT")
        versions = [row.get("version") for row in rows]
        require(len(set(versions)) == len(versions), "DUPLICATE_MIGRATION_VERSIONS")
        require("V136" in versions and "V147" not in versions, "V136_OR_V147_STATE")
        source = {item.version: item for item in load_migrations()}
        report["migration_ledger"] = []
        for row in rows:
            migration = source.get(str(row.get("version")))
            require(
                migration is not None and migration.filename == row.get("filename"),
                "LEDGER_SOURCE_IDENTITY",
            )
            assert migration is not None
            checksum = row.get("sha256")
            report["migration_ledger"].append(
                {
                    "version": migration.version,
                    "filename": migration.filename,
                    "sha256": checksum
                    if isinstance(checksum, str) and re.fullmatch(r"[0-9a-f]{64}", checksum)
                    else "REDACTED_INVALID",
                }
            )
            if migration.version in LEGACY_DEV_MIGRATION_CHECKSUMS:
                require(
                    checksum == LEGACY_DEV_MIGRATION_CHECKSUMS[migration.version],
                    "LEGACY_LEDGER_SHAPE",
                )
            require(
                checksum == migration.sha256
                or is_line_ending_equivalent_checksum(migration.source, str(checksum))
                or checksum == LEGACY_DEV_MIGRATION_CHECKSUMS.get(migration.version),
                "LEDGER_CHECKSUM_MISMATCH",
            )
        pending = [item for item in migration_plan(DEV) if item["version"] not in versions]
        report["pending_migrations"] = pending
        report["v149_excluded"] = all(item["version"] != "V149" for item in pending)
        require(pending == [V147], "PENDING_SET_NOT_SOLE_V147")
    elif index == 9:
        source = {item.version: item for item in load_migrations()}
        expected_rows = {
            (version, old, source[version].sha256, "DEV")
            for version, old in LEGACY_DEV_MIGRATION_CHECKSUMS.items()
        }
        actual = {
            tuple(
                row.get(key)
                for key in (
                    "migration_version",
                    "legacy_sha256",
                    "source_sha256",
                    "reconciliation_scope",
                )
            )
            for row in rows
        }
        require(
            len(rows) == len(expected_rows) and actual == expected_rows,
            "LEGACY_RECONCILIATION_NOT_VERIFIED_NOOP",
        )
    elif index == 10:
        require(
            {str(next(iter(row.values()))) for row in rows} >= REQUIRED_REGISTRATION_COLUMNS,
            "LEGACY_REGISTRATION_COLUMNS",
        )
    elif index in (16, 17):
        observed = [(str(row.get("name")), str(row.get("type")).split("(", 1)[0]) for row in rows]
        require(observed == column_contract(index - 16), "VIEW_COLUMN_CONTRACT")
        check["ordered_names_and_type_families_match"] = True
    return check


def inspect(cursor: Any, report: dict[str, Any], helpers: dict[str, Any]) -> dict[str, Any]:
    sql = statements()
    require(report["reserved_forecast_usd"] <= report["approved_maximum_usd"], "FORECAST_CAP")
    started = time.monotonic()
    state: dict[str, Any] = {}
    for index, statement in enumerate(sql):
        check = report["checks"][index]
        try:
            require(time.monotonic() - started < 180, "PROCESS_DEADLINE")
            report["statements_executed"] += 1
            cursor.execute(statement)
            check["query_id"] = getattr(cursor, "sfqid", None)
            columns = [str(column[0]).lower() for column in cursor.description]
            rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
            check.update(validate(index, rows, report, state, helpers))
            check["status"] = "PASS"
        except (Exception, KeyboardInterrupt) as error:
            check["status"] = "BLOCKED"
            check["category"] = (
                str(error)
                if isinstance(error, (Stop, bounds.DiagnosticStop))
                else "READ_OR_ACCESS_UNAVAILABLE"
            )
            check["query_id"] = getattr(cursor, "sfqid", None)
            check["error_code"] = getattr(error, "errno", None)
            report["elapsed_seconds"] = round(time.monotonic() - started, 3)
            return report
    report.update(
        status="PASS",
        metadata_prerequisites_pass=True,
        application_readiness="SEPARATE_RESOURCE_AND_APPLY_AUTHORIZATION_REQUIRED",
        elapsed_seconds=round(time.monotonic() - started, 3),
    )
    return report


def ledger_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe bounded ledger history without accepting or collapsing duplicates."""
    source = {item.version: item for item in load_migrations()}
    records = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        require(set(row) == {"version", "filename", "sha256", "applied_at"}, "LEDGER_COLUMNS")
        version, filename, checksum = (row[key] for key in ("version", "filename", "sha256"))
        require(
            isinstance(version, str) and re.fullmatch(r"V[0-9]{3,6}", version) is not None,
            "LEDGER_VERSION",
        )
        require(
            isinstance(filename, str)
            and re.fullmatch(r"V[0-9]{3,6}__[A-Za-z0-9_]{1,200}\.sql", filename) is not None,
            "LEDGER_FILENAME",
        )
        require(
            isinstance(checksum, str) and re.fullmatch(r"[0-9a-f]{64}", checksum) is not None,
            "LEDGER_HASH",
        )
        timestamp = row["applied_at"]
        require(isinstance(timestamp, datetime), "LEDGER_TIMESTAMP")
        canonical = source.get(version)
        comparison = "UNEXPECTED_VERSION"
        if canonical:
            comparison = "CONFLICT_WITH_CANONICAL"
            if filename == canonical.filename and (
                checksum == canonical.sha256
                or is_line_ending_equivalent_checksum(canonical.source, checksum)
                or checksum == LEGACY_DEV_MIGRATION_CHECKSUMS.get(version)
            ):
                comparison = "CANONICAL_OR_SUPPORTED_LEGACY_MATCH"
        record = {
            "version": version,
            "filename": filename,
            "sha256": checksum,
            "applied_at": timestamp.isoformat(),
            "canonical_comparison": comparison,
        }
        records.append(record)
        grouped.setdefault(version, []).append(record)
    duplicates = [
        {
            "version": version,
            "row_count": len(entries),
            "classification": "IDENTICAL_SOURCE_ENTRIES"
            if len({(entry["filename"], entry["sha256"]) for entry in entries}) == 1
            else "CONFLICTING_SOURCE_ENTRIES",
            "records": entries,
        }
        for version, entries in grouped.items()
        if len(entries) > 1
    ]
    return {
        "records": records,
        "duplicates": duplicates,
        "row_count": len(rows),
        "complete": len(rows) <= 150,
        "integrity": "BLOCKED"
        if duplicates
        or any(r["canonical_comparison"] != "CANONICAL_OR_SUPPORTED_LEGACY_MATCH" for r in records)
        else "SOURCE_IDENTITIES_MATCH_ONLY",
    }


def inspect_ledger(cursor: Any, report: dict[str, Any], helpers: dict[str, Any]) -> dict[str, Any]:
    """Execute only fixed identity, warehouse and ledger reads; never acceptance."""
    sql = statements()
    report.update(mode="V147_DEV_LEDGER_DIAGNOSTIC_ONLY", checks=[])
    require(report["reserved_forecast_usd"] <= report["approved_maximum_usd"], "FORECAST_CAP")
    started = time.monotonic()
    state: dict[str, Any] = {}
    for index in (0, 1, 8):
        check = {"ordinal": len(report["checks"]) + 1, "name": NAMES[index]}
        report["checks"].append(check)
        try:
            require(time.monotonic() - started < 180, "PROCESS_DEADLINE")
            report["statements_executed"] += 1
            cursor.execute(sql[index])
            check["query_id"] = getattr(cursor, "sfqid", None)
            columns = [str(column[0]).lower() for column in cursor.description]
            require(len(columns) == len(set(columns)), "DUPLICATE_RESULT_COLUMNS")
            rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
            if index == 8:
                report["ledger_evidence"] = ledger_evidence(rows)
                require(report["ledger_evidence"]["complete"], "LEDGER_RESULT_TRUNCATED")
            else:
                check.update(validate(index, rows, report, state, helpers))
            check["status"] = "PASS"
        except (Exception, KeyboardInterrupt) as error:
            check.update(
                status="BLOCKED",
                category=str(error)
                if isinstance(error, (Stop, bounds.DiagnosticStop))
                else "READ_OR_ACCESS_UNAVAILABLE",
            )
            report["elapsed_seconds"] = round(time.monotonic() - started, 3)
            return report
    report.update(
        status="PASS",
        diagnostic_evidence_captured=True,
        sole_v147_ready=False,
        elapsed_seconds=round(time.monotonic() - started, 3),
    )
    return report
