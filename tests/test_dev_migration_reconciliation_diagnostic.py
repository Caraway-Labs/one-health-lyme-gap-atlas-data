"""Credential-free proof of the fixed reconciliation diagnostic boundary."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/diagnose_dev_migration_reconciliations.py"
SPEC = importlib.util.spec_from_file_location("diagnose_dev_migration_reconciliations", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostic)


def _rows() -> list[dict[str, str]]:
    expected = {item.version: item.sha256 for item in diagnostic.load_migrations()}
    return [
        {
            "MIGRATION_VERSION": version,
            "LEGACY_SHA256": legacy,
            "SOURCE_SHA256": expected[version],
            "RECONCILIATION_SCOPE": "DEV",
            "RATIONALE": diagnostic.RECONCILIATION_REASON,
            "APPROVED_BY": diagnostic.USER,
        }
        for version, legacy in diagnostic.LEGACY_DEV_MIGRATION_CHECKSUMS.items()
    ]


def _query(
    rows: list[dict[str, str]], *, wrong_identity: bool = False, wrong_owner: bool = False
) -> tuple[Any, list[str]]:
    calls: list[str] = []

    def query(sql: str) -> list[dict[str, Any]]:
        calls.append(sql)
        assert sql in diagnostic.ALLOWED_SQL
        if sql == diagnostic.IDENTITY_SQL:
            return [
                {
                    "USER_NAME": "WRONG" if wrong_identity else diagnostic.USER,
                    "ROLE_NAME": diagnostic.ROLE,
                    "DATABASE_NAME": diagnostic.DEV_DATABASE,
                    "WAREHOUSE_NAME": diagnostic.WAREHOUSE,
                }
            ]
        if sql == diagnostic.TABLE_SQL:
            return [
                {
                    "name": "SCHEMA_MIGRATION_RECONCILIATIONS",
                    "owner": "WRONG" if wrong_owner else diagnostic.ROLE,
                }
            ]
        if sql == diagnostic.GRANTS_SQL:
            return [
                {
                    "grantee_name": diagnostic.ROLE,
                    "granted_to": "ROLE",
                    "privilege": "OWNERSHIP",
                    "grant_option": True,
                }
            ]
        if sql == diagnostic.ROLE_ASSIGNMENTS_SQL:
            return [
                {
                    "grantee_name": diagnostic.USER,
                    "granted_to": "USER",
                    "role": diagnostic.ROLE,
                }
            ]
        return rows

    return query, calls


def test_exact_rows_pass_with_owner_and_grants() -> None:
    query, calls = _query(_rows())
    result = diagnostic.diagnose(query, diagnostic.WAREHOUSE)
    assert result["disposition"] == "PASS"
    assert result["dev_row_count"] == 3
    assert result["table_owner"] == diagnostic.ROLE
    assert calls == [
        diagnostic.IDENTITY_SQL,
        diagnostic.TABLE_SQL,
        diagnostic.GRANTS_SQL,
        diagnostic.ROLE_ASSIGNMENTS_SQL,
        diagnostic.ROWS_SQL,
    ]


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "mismatched", "unexpected"])
def test_bad_rows_fail(mutation: str) -> None:
    rows = _rows()
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows.append(dict(rows[0]))
    elif mutation == "mismatched":
        rows[0]["SOURCE_SHA256"] = "0" * 64
    else:
        rows.append({**rows[0], "MIGRATION_VERSION": "V999"})
    query, _ = _query(rows)
    assert diagnostic.diagnose(query, diagnostic.WAREHOUSE)["disposition"] == "FAIL"


def test_wrong_identity_fails_before_table_reads() -> None:
    query, calls = _query(_rows(), wrong_identity=True)
    result = diagnostic.diagnose(query, diagnostic.WAREHOUSE)
    assert result["reason"] == "IDENTITY_MISMATCH"
    assert calls == [diagnostic.IDENTITY_SQL]


def test_wrong_expected_warehouse_fails_before_table_reads() -> None:
    query, calls = _query(_rows())
    result = diagnostic.diagnose(query, "WRONG_WH")
    assert result["reason"] == "IDENTITY_MISMATCH"
    assert calls == [diagnostic.IDENTITY_SQL]


def test_wrong_table_owner_fails() -> None:
    query, _ = _query(_rows(), wrong_owner=True)
    assert diagnostic.diagnose(query, diagnostic.WAREHOUSE)["disposition"] == "FAIL"


def test_unexpected_table_grant_fails() -> None:
    query, _ = _query(_rows())

    def extra_grant(sql: str) -> list[dict[str, Any]]:
        rows = query(sql)
        if sql == diagnostic.GRANTS_SQL:
            return rows + [{"grantee_name": "OTHER", "privilege": "SELECT", "grant_option": True}]
        return rows

    assert diagnostic.diagnose(extra_grant, diagnostic.WAREHOUSE)["disposition"] == "FAIL"


@pytest.mark.parametrize("field,value", [("granted_to", "USER"), ("grant_option", "UNKNOWN")])
def test_incorrect_owner_grant_fails(field: str, value: Any) -> None:
    query, _ = _query(_rows())

    def changed_grant(sql: str) -> list[dict[str, Any]]:
        rows = query(sql)
        if sql == diagnostic.GRANTS_SQL:
            rows[0][field] = value
        return rows

    assert diagnostic.diagnose(changed_grant, diagnostic.WAREHOUSE)["disposition"] == "FAIL"


def test_extra_table_grantee_fails_even_without_grant_option() -> None:
    query, _ = _query(_rows())

    def extra_grantee(sql: str) -> list[dict[str, Any]]:
        rows = query(sql)
        if sql == diagnostic.GRANTS_SQL:
            return rows + [
                {
                    "grantee_name": "OTHER",
                    "granted_to": "ROLE",
                    "privilege": "SELECT",
                    "grant_option": False,
                }
            ]
        return rows

    assert diagnostic.diagnose(extra_grantee, diagnostic.WAREHOUSE)["disposition"] == "FAIL"


def test_nonownership_grant_option_fails() -> None:
    query, _ = _query(_rows())

    def extra_option(sql: str) -> list[dict[str, Any]]:
        rows = query(sql)
        if sql == diagnostic.GRANTS_SQL:
            return rows + [
                {
                    "grantee_name": diagnostic.ROLE,
                    "granted_to": "ROLE",
                    "privilege": "SELECT",
                    "grant_option": True,
                }
            ]
        return rows

    assert diagnostic.diagnose(extra_option, diagnostic.WAREHOUSE)["disposition"] == "FAIL"


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong_role"])
def test_unexpected_role_assignment_fails(mutation: str) -> None:
    query, _ = _query(_rows())

    def changed_assignments(sql: str) -> list[dict[str, Any]]:
        rows = query(sql)
        if sql == diagnostic.ROLE_ASSIGNMENTS_SQL:
            if mutation == "missing":
                return []
            if mutation == "extra":
                return rows + [
                    {"grantee_name": "OTHER", "granted_to": "USER", "role": diagnostic.ROLE}
                ]
            rows[0]["role"] = "WRONG"
        return rows

    assert diagnostic.diagnose(changed_assignments, diagnostic.WAREHOUSE)["disposition"] == "FAIL"


@pytest.mark.parametrize("column", ["RATIONALE", "APPROVED_BY"])
def test_missing_or_changed_approval_evidence_fails(column: str) -> None:
    rows = _rows()
    rows[0][column] = ""
    query, _ = _query(rows)
    assert diagnostic.diagnose(query, diagnostic.WAREHOUSE)["disposition"] == "FAIL"


@pytest.mark.parametrize(
    "failing_sql",
    [
        diagnostic.TABLE_SQL,
        diagnostic.GRANTS_SQL,
        diagnostic.ROLE_ASSIGNMENTS_SQL,
        diagnostic.ROWS_SQL,
    ],
)
def test_missing_table_or_permission_fails_closed(failing_sql: str) -> None:
    query, _ = _query(_rows())

    def denied(sql: str) -> list[dict[str, Any]]:
        if sql == failing_sql:
            raise RuntimeError("permission denied")
        return query(sql)

    assert diagnostic.diagnose(denied, diagnostic.WAREHOUSE)["disposition"] == "FAIL"


def test_unlisted_sql_is_rejected_before_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diagnostic.subprocess, "run", lambda *a, **k: pytest.fail("executed"))
    for sql in (
        "CREATE TABLE X (Y NUMBER)",
        "INSERT INTO X VALUES (1)",
        "UPDATE X SET Y=1",
        "DELETE FROM X",
        "MERGE INTO X USING Y",
        "GRANT SELECT ON TABLE X TO ROLE Y",
        "REVOKE SELECT ON TABLE X FROM ROLE Y",
        "SELECT * FROM GOVERNANCE.SCHEMA_MIGRATIONS",
    ):
        with pytest.raises(ValueError):
            diagnostic._snow_query(Path("unused"), sql)
    assert all(sql.startswith(("SELECT ", "SHOW ")) for sql in diagnostic.ALLOWED_SQL)
    source = SCRIPT.read_text()
    assert "reconcile_legacy_dev_migrations(" not in source
    assert "apply_migrations(" not in source


def test_workflow_diagnostic_exits_before_reconciliation_or_migration() -> None:
    workflow = (Path(__file__).parents[1] / ".github/workflows/deploy-dev.yml").read_text()
    diagnostic_branch = workflow.index(
        'if [ "$DIAGNOSE_LEGACY_DEV_RECONCILIATIONS" = "true" ]; then'
    )
    branch_exit = workflow.index("exit 0", diagnostic_branch)
    selector = workflow.index('feed_batch="$(uv run python', diagnostic_branch)
    apply = workflow.index("pipeline apply-reviewed-dev-migrations", diagnostic_branch)
    assert diagnostic_branch < branch_exit < selector < apply
    assert (
        "timeout 120s uv run python scripts/diagnose_dev_migration_reconciliations.py" in workflow
    )
    branch = workflow[diagnostic_branch:branch_exit]
    assert '[ -n "$EXPECTED_PENDING_JSON" ]' in branch
    assert '"$DIAGNOSE_INTELLIGENCE_DEV" = "true"' in branch
