"""Curated, versioned readiness contracts for high-risk governed operations."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from .migrations import load_migrations

Status = Literal["PASS", "BLOCKED", "UNKNOWN"]
ENVIRONMENTS = {"dev", "prod"}
OPERATIONS = {"forward_migration", "governed_source_run", "semantic_release", "api_read"}
CONTRACT_PATH = Path(__file__).resolve().parents[2] / "config" / "operation-capabilities-v1.yml"
CONNECTION_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,80}$")


@dataclass(frozen=True)
class Finding:
    check: str
    status: Status
    evidence_reference: str
    next_authorized_action: str


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    """Load the deliberately small contract and reject unsafe ambiguity."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ValueError("Operation capability contract must declare version: 1")
    aliases = raw.get("role_aliases")
    operations = raw.get("operations")
    if not isinstance(aliases, dict) or not isinstance(operations, dict):
        raise ValueError("Operation capability contract requires role_aliases and operations")
    if set(operations) != OPERATIONS:
        raise ValueError("Operation capability contract must define exactly the curated operations")
    known_migrations = {migration.version for migration in load_migrations()}
    for name, item in operations.items():
        if not isinstance(item, dict):
            raise ValueError(f"Operation {name} must be a mapping")
        for key in (
            "execution_mode",
            "executor",
            "required_migrations",
            "object_capabilities",
            "authority",
            "approval",
        ):
            if key not in item:
                raise ValueError(f"Operation {name} is missing {key}")
        for alias_key in ("executor", "authority"):
            if item[alias_key] not in aliases:
                raise ValueError(
                    f"Operation {name} references unknown role alias {item[alias_key]}"
                )
        if (
            not isinstance(item["required_migrations"], list)
            or not set(item["required_migrations"]) <= known_migrations
        ):
            raise ValueError(f"Operation {name} references a missing migration")
        if not isinstance(item["object_capabilities"], list) or not item["object_capabilities"]:
            raise ValueError(f"Operation {name} requires bounded object capabilities")
        if name == "governed_source_run" and item["authority"] == item["executor"]:
            raise ValueError("Runtime roles cannot self-grant or approve sources")
    return raw


def operation_plan(contract: dict[str, Any], *, operation: str, environment: str) -> dict[str, Any]:
    """Render a no-guessing identity/object/dependency plan for one environment."""
    if operation not in OPERATIONS:
        raise ValueError(f"Unsupported operation: {operation}")
    if environment not in ENVIRONMENTS:
        raise ValueError(f"Unsupported environment: {environment}")
    item = contract["operations"][operation]
    env = environment.upper()
    aliases = contract["role_aliases"]
    return {
        "contract_version": contract["version"],
        "operation": operation,
        "environment": environment,
        "database": f"ONE_HEALTH_LYME_GAP_ATLAS_{env}",
        "execution_mode": item["execution_mode"],
        "expected_executor_role": aliases[item["executor"]].replace("{ENV}", env),
        "expected_inspector_role": aliases["read"].replace("{ENV}", env),
        "grant_authority_role": aliases[item["authority"]].replace("{ENV}", env),
        "required_migrations": item["required_migrations"],
        "object_capabilities": item["object_capabilities"],
        "approval": item["approval"],
    }


def _snow_cli_rows(connection_name: str, query: str) -> list[dict[str, Any]]:
    if CONNECTION_NAME_PATTERN.fullmatch(connection_name) is None:
        raise ValueError(
            "Snowflake connection name must use uppercase letters, digits, and underscores"
        )
    result = subprocess.run(
        ["snow", "sql", "--connection", connection_name, "--format", "json", "--query", query],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise RuntimeError("Read-only Snowflake inspection returned an unexpected result")
    return rows


def _observed_capabilities(
    grant_rows: list[dict[str, Any]], *, database: str, object_capabilities: list[str]
) -> dict[str, bool]:
    observed: dict[str, bool] = {}
    for capability in object_capabilities:
        object_name, privilege = capability.rsplit(":", maxsplit=1)
        qualified_name = f"{database}.{object_name}"
        observed[capability] = any(
            row.get("name") == qualified_name and row.get("privilege") == privilege
            for row in grant_rows
        )
    return observed


def inspect_live_facts(
    snowflake_connection: str | None = None, *, plan: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Collect only current identity and migration versions through configured read access.

    This function executes no DDL, DML, grants, or approval procedure.  It is
    intentionally opt-in at the CLI because a report must not create a new
    authorization path; capability and approval facts remain unknown unless a
    bounded, separately authorized observation supplies them.
    """
    if snowflake_connection is not None:
        identity_rows = _snow_cli_rows(
            snowflake_connection,
            "SELECT CURRENT_USER() AS CURRENT_USER, CURRENT_ROLE() AS CURRENT_ROLE, "
            "CURRENT_WAREHOUSE() AS CURRENT_WAREHOUSE, CURRENT_DATABASE() AS CURRENT_DATABASE",
        )
        if len(identity_rows) != 1:
            raise RuntimeError("Identity inspection returned an unexpected row count")
        migration_rows = _snow_cli_rows(
            snowflake_connection,
            "SELECT version FROM GOVERNANCE.SCHEMA_MIGRATIONS ORDER BY version",
        )
        identity = identity_rows[0]
        facts: dict[str, Any] = {
            "identity": {
                "user": str(identity["CURRENT_USER"]),
                "role": str(identity["CURRENT_ROLE"]),
                "warehouse": str(identity["CURRENT_WAREHOUSE"]),
                "database": str(identity["CURRENT_DATABASE"]),
            },
            "applied_migrations": [str(row["VERSION"]) for row in migration_rows],
        }
        if plan is not None:
            grant_rows = _snow_cli_rows(
                snowflake_connection,
                f"SHOW GRANTS TO ROLE {plan['expected_executor_role']}",
            )
            facts["capabilities"] = _observed_capabilities(
                grant_rows,
                database=plan["database"],
                object_capabilities=plan["object_capabilities"],
            )
        return facts

    with connect(SnowflakeSettings()) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_DATABASE()"
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("Identity inspection returned no row")
            user, role, warehouse, database = row
            cursor.execute("SELECT version FROM GOVERNANCE.SCHEMA_MIGRATIONS")
            migrations = [str(item[0]) for item in cursor.fetchall()]
        finally:
            cursor.close()
    return {
        "identity": {
            "user": str(user),
            "role": str(role),
            "warehouse": str(warehouse),
            "database": str(database),
        },
        "applied_migrations": migrations,
    }


def assess_operation(
    contract: dict[str, Any],
    *,
    operation: str,
    environment: str,
    observed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assess only supplied bounded evidence; absent visibility is never inferred."""
    plan = operation_plan(contract, operation=operation, environment=environment)
    facts = observed or {}
    findings: list[Finding] = []
    identity = facts.get("identity")
    if identity is None:
        findings.append(
            Finding(
                "effective_identity",
                "UNKNOWN",
                "not inspected",
                "Run authorized read-only identity inspection.",
            )
        )
    elif identity.get("database") != plan["database"]:
        findings.append(
            Finding(
                "effective_identity",
                "BLOCKED",
                "sanitized identity observation",
                "Use the contract-mapped DEV or PROD database.",
            )
        )
    elif identity.get("role") == plan["expected_inspector_role"]:
        findings.append(
            Finding(
                "effective_identity",
                "PASS",
                "sanitized read-only inspector observation",
                "None.",
            )
        )
        findings.append(
            Finding(
                "execution_identity",
                "UNKNOWN",
                "read-only inspection cannot prove runtime identity",
                "Revalidate immediately before mutation as the contract-mapped executor.",
            )
        )
    elif identity.get("role") != plan["expected_executor_role"]:
        findings.append(
            Finding(
                "effective_identity",
                "BLOCKED",
                "sanitized identity observation",
                "Use the contract-mapped executor or read-only inspector identity.",
            )
        )
    else:
        findings.append(
            Finding("effective_identity", "PASS", "sanitized identity observation", "None.")
        )
    applied = facts.get("applied_migrations")
    if applied is None:
        findings.append(
            Finding(
                "migration_dependencies",
                "UNKNOWN",
                "migration ledger not inspected",
                "Run an authorized read-only ledger check.",
            )
        )
    elif not set(plan["required_migrations"]).issubset(set(applied)):
        findings.append(
            Finding(
                "migration_dependencies",
                "BLOCKED",
                "migration ledger observation",
                "Use the protected forward-migration workflow.",
            )
        )
    else:
        findings.append(
            Finding("migration_dependencies", "PASS", "migration ledger observation", "None.")
        )
    capabilities = facts.get("capabilities", {})
    for capability in plan["object_capabilities"]:
        value = capabilities.get(capability)
        status: Status = "UNKNOWN" if value is None else ("PASS" if value else "BLOCKED")
        action = (
            "Obtain authorized read-only capability evidence."
            if status == "UNKNOWN"
            else (
                "Use the separately authorized grant authority; runtime roles cannot self-grant."
                if status == "BLOCKED"
                else "None."
            )
        )
        findings.append(
            Finding(
                f"runtime_capability:{capability}",
                status,
                "bounded capability observation" if value is not None else "not inspected",
                action,
            )
        )
    grant_authority = facts.get("grant_authority")
    grant_authority_status: Status = (
        "UNKNOWN" if grant_authority is None else ("PASS" if grant_authority else "BLOCKED")
    )
    findings.append(
        Finding(
            "grant_authority",
            grant_authority_status,
            "grant-authority observation" if grant_authority is not None else "not inspected",
            "Use the contract-mapped authority only after separate authorization."
            if grant_authority_status != "PASS"
            else "None.",
        )
    )
    approval = facts.get("approval")
    approval_status: Status = "UNKNOWN" if approval is None else ("PASS" if approval else "BLOCKED")
    findings.append(
        Finding(
            "release_or_approval",
            approval_status,
            "approval evidence" if approval is not None else "not inspected",
            "Obtain the contract-required human/protected approval."
            if approval_status != "PASS"
            else "None.",
        )
    )
    overall: Status = (
        "BLOCKED"
        if any(f.status == "BLOCKED" for f in findings)
        else ("UNKNOWN" if any(f.status == "UNKNOWN" for f in findings) else "PASS")
    )
    return {
        **plan,
        "mutation_started": False,
        "status": overall,
        "findings": [asdict(item) for item in findings],
    }
