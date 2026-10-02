"""Bounded read-only metadata evidence. Never authorizes or repairs database changes."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .migrations import is_line_ending_equivalent_checksum, load_migrations
from .operation_capabilities import load_contract, operation_plan

ROOT = Path(__file__).resolve().parents[2]
SCOPE_PATH = ROOT / "config" / "metadata-scope-v1.json"
IDENTIFIER = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
TYPES = {
    "TEXT",
    "NUMBER",
    "FLOAT",
    "BOOLEAN",
    "DATE",
    "TIME",
    "TIMESTAMP_NTZ",
    "TIMESTAMP_LTZ",
    "TIMESTAMP_TZ",
    "VARIANT",
    "OBJECT",
    "ARRAY",
    "BINARY",
}
PRIVILEGES = {
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "USAGE",
    "OWNERSHIP",
    "CREATE TABLE",
    "CREATE VIEW",
    "CREATE PROCEDURE",
}
KINDS = {"BASE TABLE", "VIEW", "TABLE", "PROCEDURE", "SCHEMA", "DATABASE", "ROLE"}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_scope(path: Path = SCOPE_PATH) -> dict[str, Any]:
    scope: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    validate_scope(scope)
    return scope


def validate_scope(scope: dict[str, Any]) -> None:
    if (
        not isinstance(scope, dict)
        or scope.get("version") != 1
        or set(scope)
        != {
            "version",
            "objects",
            "procedures",
            "maximum_age_hours",
        }
    ):
        raise ValueError("Unsupported metadata scope")
    if (
        type(scope["maximum_age_hours"]) is not int
        or scope["maximum_age_hours"] < 1
        or not isinstance(scope["objects"], dict)
        or not isinstance(scope["procedures"], dict)
    ):
        raise ValueError("Invalid freshness policy")
    for name, item in scope["objects"].items():
        if (
            not isinstance(name, str)
            or len(name.split(".")) != 2
            or not all(IDENTIFIER.fullmatch(x) for x in name.split("."))
        ):
            raise ValueError("Unreviewed object identifier")
        if (
            not isinstance(item, dict)
            or set(item) != {"kind", "columns"}
            or item["kind"] not in {"BASE TABLE", "VIEW"}
            or not isinstance(item["columns"], list)
        ):
            raise ValueError("Invalid object scope")
        if not all(isinstance(x, str) and IDENTIFIER.fullmatch(x) for x in item["columns"]):
            raise ValueError("Invalid column scope")
    for signature, item in scope["procedures"].items():
        if not isinstance(signature, str) or not isinstance(item, dict):
            raise ValueError("Invalid reviewed procedure signature")
        # Only reviewed, literal-free signatures. No procedure body is requested.
        name, sep, arguments = signature.partition("(")
        args = arguments.removesuffix(")").split(",") if arguments != ")" else []
        if (
            not sep
            or not signature.endswith(")")
            or len(name.split(".")) != 2
            or not all(IDENTIFIER.fullmatch(x) for x in name.split("."))
            or not all(x in TYPES for x in args)
            or set(item) != {"execute_as", "returns"}
            or item["execute_as"] not in {"OWNER", "CALLER", "RESTRICTED CALLER"}
            or item["returns"] not in TYPES
        ):
            raise ValueError("Invalid reviewed procedure signature")


def snow_rows(query: str) -> list[dict[str, Any]]:
    """Use only the existing DEV audit connection; diagnostics never expose raw output."""
    try:
        result = subprocess.run(
            [
                "snow",
                "sql",
                "--silent",
                "--secondary-roles",
                "NONE",
                "--connection",
                "ATLAS_DEV_READ",
                "--format",
                "json",
                "--query",
                query,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        output = result.stdout
        # Some snow launchers emit a startup banner. Accept exactly one trailing JSON array.
        rows = None
        for match in re.finditer(r"(?m)^\s*\[", output):
            try:
                candidate, end = json.JSONDecoder().raw_decode(output[match.end() - 1 :])
                if not output[match.end() - 1 + end :].strip():
                    rows = candidate
                    break
            except ValueError:
                continue
        if not isinstance(rows, list) or not all(isinstance(x, dict) for x in rows):
            raise ValueError
        return rows
    except (OSError, ValueError, subprocess.SubprocessError):
        raise RuntimeError("Metadata inspection unavailable; no authority fallback") from None


def _rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{str(k).upper(): v for k, v in row.items()} for row in rows]


def collect_dev(
    scope: dict[str, Any],
    query: Callable[[str], list[dict[str, Any]]] = snow_rows,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fixed projected queries, no data payloads, DDL, identity secrets or role changes."""
    contract = contract or load_contract()
    validate_scope(scope)
    plan = operation_plan(contract, operation="api_read", environment="dev")
    database = plan["database"]
    if not IDENTIFIER.fullmatch(database) or not all(
        isinstance(role, str) and IDENTIFIER.fullmatch(role.replace("{ENV}", "DEV"))
        for role in contract["role_aliases"].values()
    ):
        raise ValueError("Unsafe contract identifiers")
    identity = _rows(
        query(
            "SELECT CURRENT_ROLE() AS ROLE, CURRENT_DATABASE() AS DATABASE, "
            "CURRENT_USER() IS NOT NULL AS USER_PRESENT, "
            "CURRENT_WAREHOUSE() IS NOT NULL AS WAREHOUSE_PRESENT"
        )
    )
    if len(identity) != 1 or identity[0] != {
        "ROLE": plan["expected_inspector_role"],
        "DATABASE": database,
        "USER_PRESENT": True,
        "WAREHOUSE_PRESENT": True,
    }:
        raise RuntimeError("Unexpected audit role or database; inspection stopped")
    facts: dict[str, Any] = {
        "objects": [],
        "columns": [],
        "grants": [],
        "future_grants": [],
        "procedures": [],
        "migrations": [],
        "unavailable": [],
        "identity": {"role": "read", "environment": "dev"},
        "source": "live",
        "ledger_complete": False,
    }

    def observe(label: str, sql: str) -> list[dict[str, Any]]:
        if facts["unavailable"]:
            facts["unavailable"].append(label)
            return []
        try:
            return _rows(query(sql))
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
            facts["unavailable"].append(label)
            return []

    for name, item in scope["objects"].items():
        schema, table = name.split(".")
        facts["objects"].extend(
            observe(
                "objects",
                f"SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE, "
                f"TABLE_OWNER FROM {database}.INFORMATION_SCHEMA.TABLES "
                f"WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{table}'",
            )
        )
        if item["columns"]:
            columns = ", ".join(f"'{x}'" for x in item["columns"])
            facts["columns"].extend(
                observe(
                    "columns",
                    f"SELECT TABLE_SCHEMA, TABLE_NAME, "
                    f"COLUMN_NAME, DATA_TYPE, IS_NULLABLE, ORDINAL_POSITION, "
                    f"CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE "
                    f"FROM {database}.INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = '{schema}' "
                    f"AND TABLE_NAME = '{table}' AND COLUMN_NAME IN ({columns})",
                )
            )
    for role in contract["role_aliases"].values():
        resolved = role.replace("{ENV}", "DEV")
        facts["grants"].extend(observe("grants", f"SHOW GRANTS TO ROLE {resolved}"))
        facts["future_grants"].extend(
            observe("future_grants", f"SHOW FUTURE GRANTS TO ROLE {resolved}")
        )
    facts["migrations"] = observe(
        "migrations",
        f"SELECT VERSION, SHA256 FROM {database}.GOVERNANCE.SCHEMA_MIGRATIONS ORDER BY VERSION",
    )
    facts["ledger_complete"] = not facts["unavailable"]
    # DESCRIBE contains bodies. Project safe rows server-side via the pipe operator.
    for signature in scope["procedures"]:
        rows = observe(
            "procedures",
            f"DESCRIBE PROCEDURE {database}.{signature} "
            '->> SELECT "property", "value" FROM $1 '
            "WHERE \"property\" IN ('returns', 'execute as')",
        )
        properties = {row.get("PROPERTY"): row.get("VALUE") for row in rows}
        facts["procedures"].append(
            {
                "SIGNATURE": signature,
                "DATA_TYPE": properties.get("returns"),
                "EXECUTE_AS": properties.get("execute as"),
            }
        )
    return facts


def snapshot(
    facts: dict[str, Any],
    *,
    environment: str,
    code_commit: str,
    generated_at: datetime,
    scope: dict[str, Any] | None = None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Public-field allowlist; arbitrary identifiers/values are discarded, never echoed."""
    scope = scope or load_scope()
    validate_scope(scope)
    contract = contract or load_contract()
    plan = operation_plan(contract, operation="api_read", environment=environment)
    if (
        facts.get("source") not in {"synthetic", "live"}
        or facts.get("identity") != {"role": "read", "environment": environment}
        or (facts.get("source") == "live" and environment != "dev")
    ):
        raise ValueError("Require verified scoped identity or explicitly synthetic fixtures")
    if not re.fullmatch(r"[0-9a-f]{40}", code_commit) or generated_at.tzinfo is None:
        raise ValueError("Require full commit and timezone-aware capture time")
    roles = {
        value.replace("{ENV}", environment.upper()): key
        for key, value in contract["role_aliases"].items()
    }
    database = plan["database"]
    objects = scope["objects"]
    schemas = {x.split(".")[0] for x in objects}
    content: dict[str, Any] = {
        "objects": [],
        "columns": [],
        "grants": [],
        "future_grants": [],
        "role_edges": [],
        "procedures": [],
        "migrations": [],
        "omissions": [
            "unreviewed_identifiers",
            "unreviewed_columns",
            "view_bodies",
            "procedure_bodies",
            "unreviewed_procedures",
            "external_role_hierarchy",
            "account_database_roles",
            "secondary_roles",
            "data_rows",
        ],
    }
    for row in _rows(facts.get("objects", [])):
        name = f"{row.get('TABLE_SCHEMA')}.{row.get('TABLE_NAME')}"
        if name in objects and row.get("TABLE_TYPE") in {"BASE TABLE", "VIEW"}:
            content["objects"].append(
                {
                    "name": name,
                    "kind": row["TABLE_TYPE"],
                    "owner": roles.get(row.get("TABLE_OWNER"), "unknown"),
                }
            )
    for row in _rows(facts.get("columns", [])):
        name = f"{row.get('TABLE_SCHEMA')}.{row.get('TABLE_NAME')}"
        if (
            name in objects
            and row.get("COLUMN_NAME") in objects[name]["columns"]
            and row.get("DATA_TYPE") in TYPES
            and row.get("IS_NULLABLE") in {"YES", "NO"}
        ):
            column = {
                "object": name,
                "name": row["COLUMN_NAME"],
                "type": row["DATA_TYPE"],
                "nullable": row["IS_NULLABLE"] == "YES",
            }
            for field in (
                "ORDINAL_POSITION",
                "CHARACTER_MAXIMUM_LENGTH",
                "NUMERIC_PRECISION",
                "NUMERIC_SCALE",
            ):
                value = row.get(field)
                if (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and 0 <= value <= 16777216
                ):
                    column[field.lower()] = value
            content["columns"].append(column)
    for category in ("grants", "future_grants"):
        for row in _rows(facts.get(category, [])):
            role = roles.get(row.get("GRANTEE_NAME"))
            kind = row.get("GRANTED_ON", row.get("GRANT_ON"))
            name = str(row.get("NAME")) if isinstance(row.get("NAME"), str) else ""
            if not role or not isinstance(name, str) or kind not in KINDS:
                continue
            if kind == "ROLE" and category == "grants" and name in roles:
                content["role_edges"].append({"parent": role, "child": roles[name]})
                continue
            prefix = f"{database}."
            safe_name = name[len(prefix) :] if name.startswith(prefix) else None
            if category == "future_grants":
                allowed = {f"{schema}.<{kind}>" for schema in schemas}
            else:
                allowed = set(objects) | schemas | set(scope["procedures"])
                if name == database:
                    safe_name = "database"
                    allowed.add("database")
            privilege = row.get("PRIVILEGE")
            if safe_name in allowed and privilege in PRIVILEGES:
                content[category].append(
                    {
                        "role": role,
                        "object": safe_name,
                        "kind": kind,
                        "privilege": privilege,
                        "grant_option": (
                            True
                            if row.get("GRANT_OPTION") in (True, "true", "TRUE")
                            else False
                            if row.get("GRANT_OPTION") in (False, "false", "FALSE")
                            else "unknown"
                        ),
                    }
                )
    for row in _rows(facts.get("procedures", [])):
        signature = row.get("SIGNATURE")
        if (
            signature in scope["procedures"]
            and row.get("EXECUTE_AS") in {"OWNER", "CALLER", "RESTRICTED CALLER"}
            and row.get("DATA_TYPE") in TYPES
        ):
            content["procedures"].append(
                {
                    "signature": signature,
                    "returns": row["DATA_TYPE"],
                    "execute_as": row["EXECUTE_AS"],
                    "owner": roles.get(row.get("PROCEDURE_OWNER"), "unknown"),
                }
            )
    known = {migration.version: migration for migration in load_migrations()}
    for row in _rows(facts.get("migrations", [])):
        version = row.get("VERSION")
        if version in known:
            content["migrations"].append(
                {
                    "version": version,
                    "checksum": "match"
                    if isinstance(row.get("SHA256"), str)
                    and is_line_ending_equivalent_checksum(known[version].source, row["SHA256"])
                    else "unverified_mismatch",
                }
            )
    for key, values in content.items():
        content[key] = sorted(
            {json.dumps(x, sort_keys=True): x for x in values}.values(),
            key=lambda x: json.dumps(x, sort_keys=True),
        )
    result = {
        "snapshot_version": 1,
        "exporter_version": 1,
        "environment": environment,
        "inspected_role": "read",
        "generated_at": generated_at.astimezone(UTC).isoformat(),
        "code_commit": code_commit,
        "contract_version": contract["version"],
        "contract_hash": digest(contract),
        "scope_hash": digest(scope),
        "scope": scope,
        "source": facts["source"],
        "ledger_complete": facts.get("ledger_complete") is True,
        "visibility": "partial",
        "unavailable": sorted(
            set(
                x
                for x in facts.get("unavailable", [])
                if x
                in {"objects", "columns", "grants", "future_grants", "migrations", "procedures"}
            )
        ),
        "content": content,
    }
    result["semantic_hash"] = evidence_hash(result)
    return result


def evidence_hash(value: dict[str, Any]) -> str:
    return digest(
        {
            key: value[key]
            for key in (
                "environment",
                "scope_hash",
                "contract_hash",
                "visibility",
                "unavailable",
                "source",
                "ledger_complete",
                "content",
            )
        }
    )


def snapshot_schema(scope: dict[str, Any] | None = None) -> dict[str, Any]:
    """Strict closed schema; identifiers are from reviewed scope, never arbitrary strings."""
    scope = scope or load_scope()
    validate_scope(scope)
    roles = {"enum": ["migration_deployer", "runtime", "read", "owner"]}
    owner = {"enum": [*roles["enum"], "unknown"]}
    names = list(scope["objects"])
    schemas = sorted({x.split(".")[0] for x in names})
    signatures = list(scope["procedures"])

    def closed(properties: dict[str, Any], optional: tuple[str, ...] = ()) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": [x for x in properties if x not in optional],
        }

    def array(item: dict[str, Any]) -> dict[str, Any]:
        return {"type": "array", "items": item, "uniqueItems": True}

    grant = closed(
        {
            "role": roles,
            "object": {"enum": [*names, *schemas, *signatures, "database"]},
            "kind": {"enum": sorted(KINDS)},
            "privilege": {"enum": sorted(PRIVILEGES)},
            "grant_option": {"enum": [True, False, "unknown"]},
        }
    )
    future = closed(
        {
            **grant["properties"],
            "object": {
                "enum": [f"{schema}.<{kind}>" for schema in schemas for kind in sorted(KINDS)]
            },
        }
    )
    integer = {"type": "integer", "minimum": 0, "maximum": 16777216}
    optional = (
        "ordinal_position",
        "character_maximum_length",
        "numeric_precision",
        "numeric_scale",
    )
    content = closed(
        {
            "objects": array(
                closed(
                    {
                        "name": {"enum": names},
                        "kind": {"enum": ["BASE TABLE", "VIEW"]},
                        "owner": owner,
                    }
                )
            ),
            "columns": array(
                closed(
                    {
                        "object": {"enum": names},
                        "name": {
                            "enum": sorted(
                                {x for item in scope["objects"].values() for x in item["columns"]}
                            )
                        },
                        "type": {"enum": sorted(TYPES)},
                        "nullable": {"type": "boolean"},
                        **dict.fromkeys(optional, integer),
                    },
                    optional,
                )
            ),
            "grants": array(grant),
            "future_grants": array(future),
            "role_edges": array(closed({"parent": roles, "child": roles})),
            "procedures": array(
                closed(
                    {
                        "signature": {"enum": signatures} if signatures else False,
                        "returns": {"enum": sorted(TYPES)},
                        "execute_as": {"enum": ["OWNER", "CALLER", "RESTRICTED CALLER"]},
                        "owner": owner,
                    }
                )
            ),
            "migrations": array(
                closed(
                    {
                        "version": {"enum": [x.version for x in load_migrations()]},
                        "checksum": {"enum": ["match", "unverified_mismatch"]},
                    }
                )
            ),
            "omissions": array(
                {
                    "enum": [
                        "unreviewed_identifiers",
                        "unreviewed_columns",
                        "view_bodies",
                        "procedure_bodies",
                        "unreviewed_procedures",
                        "external_role_hierarchy",
                        "account_database_roles",
                        "secondary_roles",
                        "data_rows",
                    ]
                }
            ),
        }
    )
    sha = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **closed(
            {
                "snapshot_version": {"const": 1},
                "exporter_version": {"const": 1},
                "environment": {"enum": ["dev", "prod"]},
                "inspected_role": {"const": "read"},
                "source": {"enum": ["live", "synthetic"]},
                "ledger_complete": {"type": "boolean"},
                "generated_at": {"type": "string", "format": "date-time"},
                "code_commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                "contract_version": {"const": 1},
                "contract_hash": sha,
                "scope_hash": sha,
                "scope": {"const": scope},
                "visibility": {"const": "partial"},
                "unavailable": array(
                    {
                        "enum": [
                            "objects",
                            "columns",
                            "grants",
                            "future_grants",
                            "migrations",
                            "procedures",
                        ]
                    }
                ),
                "content": content,
                "semantic_hash": sha,
            }
        ),
    }


def validate_snapshot(value: dict[str, Any], scope: dict[str, Any] | None = None) -> None:
    import jsonschema  # type: ignore[import-untyped]

    try:
        jsonschema.Draft202012Validator(
            snapshot_schema(scope), format_checker=jsonschema.FormatChecker()
        ).validate(value)
    except (jsonschema.ValidationError, jsonschema.SchemaError, TypeError, ValueError):
        raise ValueError("Snapshot rejected by reviewed public contract") from None


def report(
    observed: dict[str, Any],
    *,
    now: datetime,
    contract: dict[str, Any] | None = None,
    baseline: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evidence only; absent direct grants cannot disprove inherited privileges."""
    contract = contract or load_contract()
    scope = scope or load_scope()
    validate_snapshot(observed, scope)
    if baseline is not None:
        validate_snapshot(baseline, scope)
    findings: list[dict[str, str]] = []

    def add(category: str, subject: str, reason: str) -> None:
        findings.append({"category": category, "subject": subject, "reason": reason})

    captured = datetime.fromisoformat(observed["generated_at"])
    if now.tzinfo is None or captured.tzinfo is None:
        raise ValueError("Freshness requires timezone-aware timestamps")
    age = now - captured
    if age < timedelta(0) or age > timedelta(hours=observed["scope"]["maximum_age_hours"]):
        add("stale", "snapshot", "expired or future capture time; refresh before consequential use")
    if observed["semantic_hash"] != evidence_hash(observed):
        add("mismatched", "semantic_hash", "content integrity failed")
    if observed["contract_hash"] != digest(contract) or observed["scope_hash"] != digest(scope):
        add("mismatched", "contract_or_scope", "current reviewed contract differs")
    content = observed["content"]
    for name, expected in observed["scope"]["objects"].items():
        found = [x for x in content["objects"] if x["name"] == name]
        if not found:
            add("unknown", name, "not visible; empty role-filtered result cannot prove absence")
        elif any(x["kind"] != expected["kind"] for x in found):
            add("mismatched", name, "object kind differs from reviewed scope")
        for column in expected["columns"]:
            if not any(x["object"] == name and x["name"] == column for x in content["columns"]):
                add(
                    "unknown",
                    f"{name}.{column}",
                    "reviewed column not visible or unsupported metadata",
                )
    for signature, expected in observed["scope"]["procedures"].items():
        found = [x for x in content["procedures"] if x["signature"] == signature]
        if not found:
            add("unknown", signature, "reviewed signature not visible")
        elif any(
            x["execute_as"] != expected["execute_as"] or x["returns"] != expected["returns"]
            for x in found
        ):
            add("mismatched", signature, "execution mode or return type differs")
    for operation in sorted(contract["operations"]):
        item = contract["operations"][operation]
        dependencies = operation_plan(
            contract, operation=operation, environment=observed["environment"]
        )["required_migrations"]
        for version in dependencies:
            if not any(x["version"] == version for x in content["migrations"]):
                add(
                    "missing" if observed["ledger_complete"] else "unknown",
                    f"{operation}:{version}",
                    "required migration not in complete ledger"
                    if observed["ledger_complete"]
                    else "ledger inspection incomplete",
                )
        reachable = {item["executor"]}
        for _ in range(len(contract["role_aliases"])):
            reachable |= {x["child"] for x in content["role_edges"] if x["parent"] in reachable}
        for capability in item["object_capabilities"]:
            name, privilege = capability.rsplit(":", 1)
            if not any(
                x["role"] in reachable and x["object"] == name and x["privilege"] == privilege
                for x in content["grants"]
            ):
                add(
                    "unknown",
                    f"{operation}:{capability}",
                    "direct/inherited evidence incomplete; no absence inference",
                )
    for grant in content["grants"]:
        if grant["kind"] in {"TABLE", "VIEW"} and not any(
            grant["role"] == item["executor"]
            and f"{grant['object']}:{grant['privilege']}" in item["object_capabilities"]
            for item in contract["operations"].values()
        ):
            add(
                "unexpected",
                f"{grant['role']}:{grant['object']}:{grant['privilege']}",
                "outside curated desired capabilities; not proof of unauthorized grant",
            )
    for migration in content["migrations"]:
        if migration["checksum"] == "unverified_mismatch":
            add(
                "unknown",
                migration["version"],
                "checksum differs; approved legacy reconciliation not inspected",
            )
    if baseline is not None:
        baseline_age = now - datetime.fromisoformat(baseline["generated_at"])
        if baseline["source"] != observed["source"]:
            add(
                "unknown",
                "baseline_source",
                "mixed live/synthetic observations cannot prove live drift; comparison skipped",
            )
        elif baseline["semantic_hash"] != evidence_hash(baseline):
            add("mismatched", "baseline", "baseline integrity failed; comparison skipped")
        elif baseline_age < timedelta(0) or baseline_age > timedelta(
            hours=scope["maximum_age_hours"]
        ):
            add("stale", "baseline", "baseline expired or future; comparison skipped")
        elif baseline["contract_hash"] != digest(contract):
            add("unknown", "baseline", "baseline desired contract differs; comparison skipped")
        elif (
            baseline["environment"] != observed["environment"]
            or baseline["scope_hash"] != observed["scope_hash"]
        ):
            add("unknown", "baseline", "environment or reviewed scope differs; incomparable")
        else:
            for category in (
                "objects",
                "columns",
                "procedures",
                "grants",
                "future_grants",
                "role_edges",
            ):
                prior = {json.dumps(x, sort_keys=True) for x in baseline["content"][category]}
                current = {json.dumps(x, sort_keys=True) for x in content[category]}
                if prior - current:
                    add(
                        "unknown",
                        category,
                        "previous observation not seen; visibility may have changed",
                    )
                if current - prior:
                    add("mismatched", category, "observed metadata changed from baseline")
    add(
        "unknown",
        "desired_schema",
        "contract v1 defines capabilities, not comprehensive columns/procedures",
    )
    add("unknown", "visibility", "partial audit role; external inheritance/future scope omitted")
    for category in observed["unavailable"]:
        add("unknown", category, "inspection unavailable")
    return {
        "report_version": 1,
        "environment": observed["environment"],
        "semantic_hash": evidence_hash(observed),
        "source": observed["source"],
        "baseline_source": baseline["source"] if baseline is not None else None,
        "comparison_kind": (
            "mixed_source_non_live"
            if baseline is not None and baseline["source"] != observed["source"]
            else "synthetic_fixture"
            if observed["source"] == "synthetic"
            else "live_observation"
        ),
        "mutation_started": False,
        "consequential_use": "blocked" if findings else "eligible_evidence_only",
        "findings": findings,
    }


def render_report(result: dict[str, Any]) -> str:
    return (
        "\n".join(
            [
                f"Metadata evidence: {result['environment']} ({result['consequential_use']})",
                f"Source kind: {result['source']}; "
                f"baseline: {result['baseline_source'] or 'none'}; "
                f"comparison: {result['comparison_kind']}",
                *[
                    f"{x['category'].upper()} {x['subject']}: {x['reason']}"
                    for x in result["findings"]
                ],
            ]
        )
        + "\n"
    )
