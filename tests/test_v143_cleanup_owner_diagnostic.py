"""Credential-free checks for the fixed V143 owner-only diagnostic."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/diagnose_v143_cleanup_owner.py"
SPEC = importlib.util.spec_from_file_location("diagnose_v143_cleanup_owner", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostic)


def _evidence() -> dict[str, list[dict[str, Any]]]:
    body, view = diagnostic._reviewed_source()
    return {
        diagnostic.IDENTITY_SQL: [
            {
                "USER_NAME": diagnostic.USER,
                "ROLE_NAME": diagnostic.ROLE,
                "DATABASE_NAME": diagnostic.DEV_DATABASE,
                "WAREHOUSE_NAME": diagnostic.WAREHOUSE,
            }
        ],
        diagnostic.LEDGER_SQL: [
            {
                "VERSION": diagnostic.VERSION,
                "FILENAME": diagnostic.FILENAME,
                "SHA256": diagnostic.MIGRATION_SHA256,
            }
        ],
        diagnostic.PROCEDURE_SQL: [
            {
                "name": "PURGE_INTELLIGENCE_RAW_CHECKPOINT",
                "catalog_name": diagnostic.DEV_DATABASE,
                "schema_name": "GOVERNANCE",
                "min_num_arguments": 4,
                "max_num_arguments": 4,
                "arguments": diagnostic.SIGNATURE,
                "created_on": diagnostic.CREATED_ON,
            }
        ],
        diagnostic.GRANTS_SQL: [
            {
                "privilege": "OWNERSHIP",
                "grantee_name": diagnostic.ROLE,
                "granted_to": "ROLE",
                "grant_option": "true",
            }
        ],
        diagnostic.DEFINITION_SQL: [
            {
                "PROCEDURE_OWNER": diagnostic.ROLE,
                "PROCEDURE_DEFINITION": body,
            }
        ],
        diagnostic.DDL_SQL: [
            {
                "DDL": "CREATE PROCEDURE ... EXECUTE AS OWNER AS '" + body + "'",
            }
        ],
        diagnostic.VIEW_SQL: [
            {
                "name": "INTELLIGENCE_RAW_CLEANUP_EXPECTED_HANDOFF_V",
                "owner": diagnostic.ROLE,
                "text": view,
            }
        ],
        diagnostic.APPROVALS_SQL: [{"ROW_COUNT": 0}],
        diagnostic.ATTESTATIONS_SQL: [{"ROW_COUNT": 0}],
    }


def _run(rows: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, Any], list[str]]:
    calls: list[str] = []

    def query(sql: str) -> list[dict[str, Any]]:
        calls.append(sql)
        assert sql in diagnostic.ALLOWED_SQL
        return rows[sql]

    return diagnostic.diagnose(query, diagnostic.WAREHOUSE), calls


def test_exact_owner_readback_passes_without_exposing_body() -> None:
    result, calls = _run(_evidence())
    assert result["disposition"] == "PASS"
    assert result["observed_body_sha256"] == diagnostic.BODY_SHA256
    assert result["approval_rows"] == result["attestation_rows"] == 0
    assert calls[0] == diagnostic.IDENTITY_SQL
    assert len(calls) == len(diagnostic.ALLOWED_SQL)
    output = json.dumps(result)
    assert "INTELLIGENCE_RAW_DELETE_SCOPE_INVALID" not in output
    assert "PLAN_CANONICAL_JSON" not in output


def test_snowflake_show_timestamp_format_passes() -> None:
    rows = _evidence()
    rows[diagnostic.PROCEDURE_SQL][0]["created_on"] = "2026-10-08 21:30:14.635 -0700"
    assert _run(rows)[0]["disposition"] == "PASS"


@pytest.mark.parametrize("timestamp", ["2026-10-08 21:30:14.636 -0700", "2026-10-08 21:30:14.635"])
def test_changed_or_naive_creation_timestamp_fails(timestamp: str) -> None:
    rows = _evidence()
    rows[diagnostic.PROCEDURE_SQL][0]["created_on"] = timestamp
    assert _run(rows)[0]["disposition"] == "FAIL"


@pytest.mark.parametrize("field", ["USER_NAME", "ROLE_NAME", "DATABASE_NAME", "WAREHOUSE_NAME"])
def test_wrong_identity_stops_before_object_reads(field: str) -> None:
    rows = _evidence()
    rows[diagnostic.IDENTITY_SQL][0][field] = "WRONG"
    result, calls = _run(rows)
    assert result["disposition"] == "FAIL"
    assert calls == [diagnostic.IDENTITY_SQL]


def test_wrong_expected_warehouse_stops_before_object_reads() -> None:
    rows = _evidence()
    calls: list[str] = []

    def query(sql: str) -> list[dict[str, Any]]:
        calls.append(sql)
        return rows[sql]

    assert diagnostic.diagnose(query, "WRONG")["disposition"] == "FAIL"
    assert calls == [diagnostic.IDENTITY_SQL]


@pytest.mark.parametrize("mutation", ["redacted", "changed", "missing", "duplicate"])
def test_body_mismatch_or_redaction_fails(mutation: str) -> None:
    rows = _evidence()
    definitions = rows[diagnostic.DEFINITION_SQL]
    if mutation == "redacted":
        definitions[0]["PROCEDURE_DEFINITION"] = ""
    elif mutation == "changed":
        definitions[0]["PROCEDURE_DEFINITION"] += " SELECT 1;"
    elif mutation == "missing":
        definitions.clear()
    else:
        definitions.append(dict(definitions[0]))
    assert _run(rows)[0]["disposition"] == "FAIL"


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_incomplete_or_duplicate_ledger_fails(mutation: str) -> None:
    rows = _evidence()
    if mutation == "missing":
        rows[diagnostic.LEDGER_SQL].clear()
    else:
        rows[diagnostic.LEDGER_SQL].append(dict(rows[diagnostic.LEDGER_SQL][0]))
    assert _run(rows)[0]["disposition"] == "FAIL"


@pytest.mark.parametrize("sql", [diagnostic.APPROVALS_SQL, diagnostic.ATTESTATIONS_SQL])
@pytest.mark.parametrize("count", [1, 2])
def test_nonempty_cleanup_tables_fail(sql: str, count: int) -> None:
    rows = _evidence()
    rows[sql][0]["ROW_COUNT"] = count
    assert _run(rows)[0]["disposition"] == "FAIL"


@pytest.mark.parametrize("sql", [diagnostic.APPROVALS_SQL, diagnostic.ATTESTATIONS_SQL])
def test_missing_count_fails(sql: str) -> None:
    rows = _evidence()
    rows[sql] = []
    assert _run(rows)[0]["disposition"] == "FAIL"


@pytest.mark.parametrize(
    "sql,key,value",
    [
        (diagnostic.LEDGER_SQL, "SHA256", "0" * 64),
        (
            diagnostic.PROCEDURE_SQL,
            "arguments",
            "PURGE_INTELLIGENCE_RAW_CHECKPOINT(VARCHAR) RETURN VARCHAR",
        ),
        (diagnostic.PROCEDURE_SQL, "created_on", "2026-10-09T00:00:00.000000-07:00"),
        (diagnostic.GRANTS_SQL, "grantee_name", "OTHER"),
        (diagnostic.DEFINITION_SQL, "PROCEDURE_OWNER", "OTHER"),
        (diagnostic.DDL_SQL, "DDL", "CREATE PROCEDURE ... EXECUTE AS CALLER AS ''"),
        (diagnostic.VIEW_SQL, "text", "CREATE VIEW WRONG AS SELECT 1"),
    ],
)
def test_changed_ledger_procedure_owner_rights_or_view_fails(
    sql: str, key: str, value: str
) -> None:
    rows = _evidence()
    rows[sql][0][key] = value
    assert _run(rows)[0]["disposition"] == "FAIL"


def test_early_executor_usage_fails() -> None:
    rows = _evidence()
    rows[diagnostic.GRANTS_SQL].append(
        {
            "privilege": "USAGE",
            "grantee_name": "OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP",
            "granted_to": "ROLE",
            "grant_option": "false",
        }
    )
    assert _run(rows)[0]["disposition"] == "FAIL"


@pytest.mark.parametrize("sql", list(diagnostic.ALLOWED_SQL - {diagnostic.IDENTITY_SQL}))
def test_object_permission_error_fails_closed(sql: str) -> None:
    rows = _evidence()

    def query(requested: str) -> list[dict[str, Any]]:
        if requested == sql:
            raise RuntimeError("permission denied")
        return rows[requested]

    assert diagnostic.diagnose(query, diagnostic.WAREHOUSE)["disposition"] == "FAIL"


def test_no_unlisted_sql_or_mutation_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diagnostic.subprocess, "run", lambda *a, **k: pytest.fail("executed"))
    for sql in (
        "CALL GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT('a','b','c','d')",
        "CREATE TABLE X (Y NUMBER)",
        "INSERT INTO X VALUES (1)",
        "UPDATE X SET Y=1",
        "DELETE FROM X",
        "GRANT USAGE ON PROCEDURE X TO ROLE Y",
        "SELECT * FROM GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_APPROVALS",
    ):
        with pytest.raises(ValueError):
            diagnostic._snow_query(Path("unused"), sql)
    assert all(sql.startswith(("SELECT ", "SHOW ")) for sql in diagnostic.ALLOWED_SQL)
    source = SCRIPT.read_text()
    assert "reconcile_legacy_dev_migrations(" not in source
    assert "apply_migrations(" not in source


def test_changed_reviewed_source_fails_before_live_object_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _evidence()
    calls: list[str] = []

    def changed_source() -> tuple[str, str]:
        raise ValueError("source changed")

    monkeypatch.setattr(diagnostic, "_reviewed_source", changed_source)

    def query(sql: str) -> list[dict[str, Any]]:
        calls.append(sql)
        return rows[sql]

    assert diagnostic.diagnose(query, diagnostic.WAREHOUSE)["disposition"] == "FAIL"
    assert calls == [diagnostic.IDENTITY_SQL]


def test_workflow_mode_exits_before_migration_and_rejects_pending_inputs() -> None:
    workflow = (ROOT / ".github/workflows/deploy-dev.yml").read_text()
    start = workflow.index('if [ "$DIAGNOSE_V143_CLEANUP_OWNER" = "true" ]; then')
    end = workflow.index('if [ "$DIAGNOSE_JANUARY_RUNTIME_INIT" = "true" ]; then', start)
    branch = workflow[start:end]
    assert 'test -z "$EXPECTED_PENDING_JSON"' in branch
    assert 'test "$GITHUB_REF" = refs/heads/main' in branch
    assert "scripts/diagnose_v143_cleanup_owner.py" in branch
    assert "exit 0" in branch
    assert workflow.index("apply-reviewed-dev-migrations", end) > end
