"""Static grant and ADR contracts for Data #129 user-feedback persistence."""

from __future__ import annotations

from pathlib import Path

from lyme_gap_atlas_data.migrations import DEV_ONLY_MIGRATION_VERSIONS, load_migrations

REPO = Path(__file__).resolve().parents[1]
MIGRATION_VERSION = "V104"
MIGRATION_NAME = "V104__user_feedback_submission.sql"
ADR_PATH = REPO / "docs" / "adr" / "0040-user-feedback-write-boundary.md"
ROLE_MODEL_PATH = REPO / "docs" / "operations" / "snowflake-stable-role-model.md"


def _migration_source() -> str:
    migration = next(item for item in load_migrations() if item.version == MIGRATION_VERSION)
    return migration.source


def _analyst_view_sql(source: str) -> str:
    marker = "CREATE OR REPLACE VIEW GOVERNANCE.V_USER_FEEDBACK_ANALYST"
    start = source.index(marker)
    grant_at = source.index("GRANT USAGE ON PROCEDURE", start)
    return source[start:grant_at]


def _redact_procedure_sql(source: str) -> str:
    marker = "CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_REDACT_FEEDBACK_FOR_ACCOUNT"
    start = source.index(marker)
    view_at = source.index("CREATE OR REPLACE VIEW GOVERNANCE.V_USER_FEEDBACK_ANALYST", start)
    return source[start:view_at]


def test_user_feedback_migration_uses_execute_as_owner() -> None:
    source = _migration_source()
    assert "EXECUTE AS OWNER" in source
    assert source.count("EXECUTE AS OWNER") >= 2


def test_user_feedback_grants_usage_to_read_for_both_procedures() -> None:
    source = _migration_source()
    assert "GRANT USAGE ON PROCEDURE GOVERNANCE.SP_SUBMIT_USER_FEEDBACK" in source
    assert "GRANT USAGE ON PROCEDURE GOVERNANCE.SP_REDACT_FEEDBACK_FOR_ACCOUNT" in source
    assert "TO ROLE OH_LYME_{{ ENV }}_READ" in source
    assert source.count("TO ROLE OH_LYME_{{ ENV }}_READ") >= 3


def test_user_feedback_migration_has_no_table_dml_grants() -> None:
    source = _migration_source()
    assert "GRANT INSERT" not in source
    assert "GRANT UPDATE" not in source
    assert "GRANT DELETE" not in source


def test_user_feedback_migration_has_no_base_table_select_to_read_or_runtime() -> None:
    source = _migration_source()
    assert "GRANT SELECT ON TABLE GOVERNANCE.USER_FEEDBACK" not in source
    assert "GRANT SELECT ON TABLE GOVERNANCE.USER_FEEDBACK_CONTACT" not in source
    assert "GRANT SELECT ON TABLE GOVERNANCE.USER_FEEDBACK_ACCOUNT" not in source
    assert "GRANT SELECT ON TABLE GOVERNANCE.USER_FEEDBACK_EVENTS" not in source
    assert "TO ROLE OH_LYME_{{ ENV }}_RUNTIME" not in source
    assert "API_RUNTIME" not in source
    assert "API_READER" not in source
    assert "PIPELINE_RUNTIME" not in source


def test_analyst_view_excludes_protected_columns() -> None:
    view_sql = _analyst_view_sql(_migration_source()).lower()
    for forbidden in ("email", "account_id", "message", "submission_token", "payload_fingerprint"):
        assert forbidden not in view_sql


def test_account_redaction_does_not_update_message() -> None:
    redact_sql = _redact_procedure_sql(_migration_source()).lower()
    assert "update governance.user_feedback" not in redact_sql
    assert "set message" not in redact_sql
    assert "linkage_removed" in redact_sql


def test_adr_states_five_exception_points_and_single_process_idempotency() -> None:
    text = ADR_PATH.read_text(encoding="utf-8")
    assert "Status: Accepted" in text
    assert "No sixth role" in text
    assert "EXECUTE AS OWNER" in text
    assert "SP_SUBMIT_USER_FEEDBACK" in text
    assert "SP_REDACT_FEEDBACK_FOR_ACCOUNT" in text
    assert "V_USER_FEEDBACK_ANALYST" in text
    assert "does not permit arbitrary future mutation" in text
    assert "dedicated API mutation role" in text
    assert "exactly one process" in text
    assert "Distributed idempotency" in text
    assert "hybrid tables were rejected" in text
    assert "No 24-month retention" in text or "no 24-month retention" in text.lower()


def test_role_model_documents_read_feedback_exception() -> None:
    doc = ROLE_MODEL_PATH.read_text(encoding="utf-8")
    assert "SP_SUBMIT_USER_FEEDBACK" in doc
    assert "SP_REDACT_FEEDBACK_FOR_ACCOUNT" in doc
    assert "not a general write grant" in doc
    assert "remains forbidden from table DML" in doc


def test_user_feedback_migration_is_not_dev_only() -> None:
    assert MIGRATION_VERSION not in DEV_ONLY_MIGRATION_VERSIONS
    assert (REPO / "migrations" / MIGRATION_NAME).exists()
    versions = [item.version for item in load_migrations()]
    assert MIGRATION_VERSION in versions
