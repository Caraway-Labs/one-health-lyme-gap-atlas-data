"""DATA #787: API diagnostics views expose timings and never statement text."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    DEV_ONLY_MIGRATION_VERSIONS,
    PROD_DATABASE,
    PROD_ONLY_MIGRATION_VERSIONS,
    PROTECTED_INTELLIGENCE_MIGRATIONS,
    load_migrations,
    migration_plan,
    render_migration,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "migrations" / "V168__api_diagnostics_history_views.sql"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
API_USER = "OH_LYME_API_SVC"
QUERY_COLUMNS = (
    "QUERY_ID",
    "QUERY_PARAMETERIZED_HASH",
    "QUERY_TYPE",
    "USER_NAME",
    "ROLE_NAME",
    "WAREHOUSE_NAME",
    "WAREHOUSE_SIZE",
    "START_TIME",
    "END_TIME",
    "TOTAL_ELAPSED_TIME",
    "COMPILATION_TIME",
    "EXECUTION_TIME",
    "QUEUED_PROVISIONING_TIME",
    "QUEUED_OVERLOAD_TIME",
    "BYTES_SCANNED",
    "ROWS_PRODUCED",
    "EXECUTION_STATUS",
    "ERROR_CODE",
)
FORBIDDEN_TEXT = (
    "QUERY_TEXT",
    "ERROR_MESSAGE",
    "QUERY_TAG",
    "CLIENT_IP",
    "SESSION_ID",
    "LOGIN_HISTORY",
)


def _projection(view: str) -> list[str]:
    match = re.search(
        rf"CREATE SECURE VIEW IF NOT EXISTS {re.escape(view)} AS\nSELECT (.*?)\nFROM ",
        SOURCE,
        re.DOTALL,
    )
    assert match is not None, view
    columns = [part.strip() for part in match.group(1).split(",")]
    assert all(re.fullmatch(r"[a-z_]+", column) for column in columns)
    return [column.upper() for column in columns]


def _grants(sql: str) -> list[str]:
    return re.findall(r"GRANT .*?;", re.sub(r"\s+", " ", sql))


def test_secure_view_projects_only_allowed_columns_for_one_database() -> None:
    upper = SOURCE.upper()
    assert upper.count("CREATE SECURE VIEW IF NOT EXISTS ") == 1
    assert "CREATE VIEW " not in upper.replace("CREATE SECURE VIEW ", "")
    assert _projection("API_DIAGNOSTICS.API_QUERY_HISTORY_V") == list(QUERY_COLUMNS)
    assert "DATABASE_NAME" not in _projection("API_DIAGNOSTICS.API_QUERY_HISTORY_V")
    assert f"WHERE user_name = '{API_USER}'\n  AND database_name = '{{{{ DATABASE }}}}'" in SOURCE
    assert re.findall(r"^FROM \S+", SOURCE, re.MULTILINE) == [
        "FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
    ]
    for forbidden in FORBIDDEN_TEXT:
        assert forbidden not in upper
    assert "SELECT *" not in upper
    assert "CREATE ROLE" not in upper
    assert "CREATE USER" not in upper


def test_grants_are_select_on_the_query_view_for_the_read_role_only() -> None:
    assert _grants(SOURCE) == [
        "GRANT USAGE ON SCHEMA API_DIAGNOSTICS TO ROLE OH_LYME_{{ ENV }}_READ;",
        "GRANT SELECT ON VIEW API_DIAGNOSTICS.API_QUERY_HISTORY_V TO ROLE OH_LYME_{{ ENV }}_READ;",
    ]
    assert set(re.findall(r"TO ROLE (.+?);", re.sub(r"\s+", " ", SOURCE))) == {
        "OH_LYME_{{ ENV }}_READ"
    }
    for forbidden in (
        "GRANT INSERT",
        "GRANT UPDATE",
        "GRANT DELETE",
        "GRANT OWNERSHIP",
        "GRANT SELECT ON TABLE",
        "FUTURE TABLES",
        "IMPORTED PRIVILEGES",
        "ACCOUNT_USAGE TO",
    ):
        assert forbidden not in SOURCE.upper()


def test_rendered_view_keeps_the_other_environment_out() -> None:
    migration = next(item for item in load_migrations() if item.version == "V168")
    versions = [item.version for item in load_migrations()]
    assert versions.count("V168") == 1
    assert migration.filename == "V168__api_diagnostics_history_views.sql"
    assert migration.sha256 == hashlib.sha256(SOURCE.encode()).hexdigest()
    assert len(migration.sha256) == 64
    assert "V168" not in DEV_ONLY_MIGRATION_VERSIONS
    assert "V168" not in PROD_ONLY_MIGRATION_VERSIONS
    assert "V168" not in {item["version"] for item in PROTECTED_INTELLIGENCE_MIGRATIONS}
    for database, environment, other in (
        (DEV_DATABASE, "DEV", PROD_DATABASE),
        (PROD_DATABASE, "PROD", DEV_DATABASE),
    ):
        rendered = render_migration(migration, database)
        assert f"USE DATABASE {database};" in rendered
        assert f"TO ROLE OH_LYME_{environment}_READ;" in rendered
        assert f"WHERE user_name = '{API_USER}'" in rendered
        assert f"database_name = '{database}'" in rendered
        assert other not in rendered
        assert "{{" not in rendered
        for forbidden in FORBIDDEN_TEXT:
            assert forbidden not in rendered.upper()
    assert "V168" in {item["version"] for item in migration_plan(DEV_DATABASE)}
    assert "V168" in {item["version"] for item in migration_plan(PROD_DATABASE)}


def test_docs_keep_the_read_role_and_name_the_privacy_boundary() -> None:
    inventory = (ROOT / "docs/operations/connection-inventory.md").read_text(encoding="utf-8")
    role_model = (ROOT / "docs/operations/snowflake-stable-role-model.md").read_text(
        encoding="utf-8"
    )
    adr = (ROOT / "docs/adr/0048-api-diagnostics-history-views.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs/operations/api-diagnostics-history.md").read_text(encoding="utf-8")
    assert "API_DIAGNOSTICS.API_QUERY_HISTORY_V" in inventory
    assert "API_LOGIN_HISTORY_V" not in inventory
    assert "`ATLAS_DEV_READ`" in inventory
    assert "`ATLAS_PROD_READ`" in inventory
    assert "API_DIAGNOSTICS.API_QUERY_HISTORY_V" in role_model
    assert "API_LOGIN_HISTORY_V" not in role_model
    assert "API_DIAGNOSTICS_READER" not in role_model
    assert "Status: Proposed" in adr
    assert "SNOWFLAKE.GOVERNANCE_VIEWER" in adr
    assert "IMPORTED PRIVILEGES" in adr
    assert "database_name = '{{ DATABASE }}'" in adr
    assert "QUERY_TEXT" in adr
    assert "QUERY_TAG" in adr
    assert "LOGIN_HISTORY" in adr
    assert "SECURITY_VIEWER" not in adr
    assert "45 minutes" in adr
    assert "45 minutes" in runbook
    assert "held_back_migrations" in runbook
    assert "18fd6c1ec8b2b6bf483a2e76ce2be08074a31038d6131b7d2a23a8456676a3f6" in runbook
    assert API_USER in runbook
    assert "API_LOGIN_HISTORY_V" not in runbook
    sql_blocks = re.findall(r"```sql\n(.*?)```", runbook, re.DOTALL)
    assert len(sql_blocks) == 4
    assert all("query_tag" not in block.lower() for block in sql_blocks)
    assert "QUERY_TAG" in runbook
    for forbidden in ("QUERY_TEXT", "ERROR_MESSAGE", "CLIENT_IP", "SESSION_ID"):
        assert forbidden not in runbook
