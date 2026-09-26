"""Static grant and state-machine contracts for Data #130 feedback triage."""

from __future__ import annotations

from pathlib import Path

from lyme_gap_atlas_data.migrations import DEV_ONLY_MIGRATION_VERSIONS, load_migrations

REPO = Path(__file__).resolve().parents[1]
MIGRATION_VERSION = "V105"
MIGRATION_NAME = "V105__user_feedback_triage.sql"
TRIAGE_DOC = REPO / "docs" / "operations" / "user-feedback-triage.md"


def _migration_source() -> str:
    migration = next(item for item in load_migrations() if item.version == MIGRATION_VERSION)
    return migration.source


def _section(source: str, start_marker: str, end_marker: str | None = None) -> str:
    start = source.index(start_marker)
    if end_marker is None:
        return source[start:]
    end = source.index(end_marker, start)
    return source[start:end]


def _triage_view_sql(source: str) -> str:
    return _section(
        source,
        "CREATE OR REPLACE VIEW GOVERNANCE.V_USER_FEEDBACK_TRIAGE",
        "CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_TRANSITION_USER_FEEDBACK",
    )


def _transition_sql(source: str) -> str:
    return _section(
        source,
        "CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_TRANSITION_USER_FEEDBACK",
        "CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_REVEAL_FEEDBACK_CONTACT",
    )


def _reveal_contact_sql(source: str) -> str:
    return _section(
        source,
        "CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_REVEAL_FEEDBACK_CONTACT",
        "CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_REVEAL_FEEDBACK_ACCOUNT",
    )


def _reveal_account_sql(source: str) -> str:
    return _section(
        source,
        "CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_REVEAL_FEEDBACK_ACCOUNT",
        "CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_REDACT_USER_FEEDBACK",
    )


def _redact_sql(source: str) -> str:
    return _section(
        source,
        "CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_REDACT_USER_FEEDBACK",
        "GRANT SELECT ON VIEW GOVERNANCE.V_USER_FEEDBACK_TRIAGE",
    )


def _assert_explicit_transaction(procedure_sql: str) -> None:
    begin_at = procedure_sql.index("BEGIN TRANSACTION")
    commit_at = procedure_sql.index("COMMIT", begin_at)
    rollback_at = procedure_sql.index("ROLLBACK", commit_at)
    assert begin_at < commit_at < rollback_at
    assert "SQLERRM" not in procedure_sql
    assert "persistence_failed" in procedure_sql
    failed_return = procedure_sql.index(
        "OBJECT_CONSTRUCT('status', 'failed', 'reason', 'persistence_failed')"
    )
    assert "SQLERRM" not in procedure_sql[failed_return : failed_return + 120]


def test_user_feedback_triage_migration_is_not_dev_only() -> None:
    assert MIGRATION_VERSION not in DEV_ONLY_MIGRATION_VERSIONS
    assert (REPO / "migrations" / MIGRATION_NAME).exists()
    versions = [item.version for item in load_migrations()]
    assert MIGRATION_VERSION in versions
    assert versions.index("V104") < versions.index(MIGRATION_VERSION)


def test_triage_procedures_use_execute_as_owner() -> None:
    source = _migration_source()
    assert source.count("EXECUTE AS OWNER") == 4


def test_triage_grants_usage_and_select_to_owner_only() -> None:
    source = _migration_source()
    assert "GRANT SELECT ON VIEW GOVERNANCE.V_USER_FEEDBACK_TRIAGE" in source
    assert "GRANT USAGE ON PROCEDURE GOVERNANCE.SP_TRANSITION_USER_FEEDBACK" in source
    assert "GRANT USAGE ON PROCEDURE GOVERNANCE.SP_REVEAL_FEEDBACK_CONTACT" in source
    assert "GRANT USAGE ON PROCEDURE GOVERNANCE.SP_REVEAL_FEEDBACK_ACCOUNT" in source
    assert "GRANT USAGE ON PROCEDURE GOVERNANCE.SP_REDACT_USER_FEEDBACK" in source
    assert source.count("TO ROLE OH_LYME_{{ ENV }}_OWNER") == 5
    assert "TO ROLE OH_LYME_{{ ENV }}_READ" not in source
    assert "TO ROLE OH_LYME_{{ ENV }}_RUNTIME" not in source
    assert "API_RUNTIME" not in source
    assert "API_READER" not in source


def test_read_and_runtime_have_no_triage_usage() -> None:
    source = _migration_source().lower()
    for proc in (
        "sp_transition_user_feedback",
        "sp_reveal_feedback_contact",
        "sp_reveal_feedback_account",
        "sp_redact_user_feedback",
    ):
        grant_idx = source.index(f"grant usage on procedure governance.{proc}")
        grant_chunk = source[grant_idx : grant_idx + 220]
        assert "_owner" in grant_chunk
        assert "_read" not in grant_chunk
        assert "_runtime" not in grant_chunk


def test_triage_view_includes_message_and_excludes_identity() -> None:
    view_sql = _triage_view_sql(_migration_source()).lower()
    for required in (
        "message",
        "category",
        "triage_state",
        "received_at",
        "route_id",
        "app_version",
        "schema_version",
        "duplicate_of_feedback_id",
        "state",
        "county_fips",
    ):
        assert required in view_sql
    for forbidden in ("email", "account_id", "submission_token", "payload_fingerprint"):
        assert forbidden not in view_sql


def test_transition_guards_terminal_and_duplicate_rules() -> None:
    transition = _transition_sql(_migration_source())
    assert "'duplicate', 'resolved', 'dismissed'" in transition
    assert "terminal_state" in transition
    assert "canonical_required" in transition
    assert "canonical_self" in transition
    assert "canonical_is_duplicate" in transition
    assert "invalid_transition" in transition
    assert "does not change state" in transition.lower() or "unchanged" in transition
    assert "SET message" not in transition
    assert "UPDATE GOVERNANCE.USER_FEEDBACK" in transition
    assert "triage_state" in transition
    # new -> reviewed|needs_follow_up|duplicate|dismissed
    assert "'reviewed', 'needs_follow_up', 'duplicate', 'dismissed'" in transition
    # reviewed/needs_follow_up may reach resolved
    assert "'reviewed', 'needs_follow_up', 'duplicate', 'resolved', 'dismissed'" in transition


def test_transition_and_reveal_and_redact_are_transactional() -> None:
    source = _migration_source()
    _assert_explicit_transaction(_transition_sql(source))
    _assert_explicit_transaction(_reveal_contact_sql(source))
    _assert_explicit_transaction(_reveal_account_sql(source))
    _assert_explicit_transaction(_redact_sql(source))


def test_reveal_procedures_return_single_field_without_logging_email() -> None:
    contact = _reveal_contact_sql(_migration_source())
    account = _reveal_account_sql(_migration_source())
    assert "contact_revealed" in contact
    assert "account_revealed" in account
    assert "OBJECT_CONSTRUCT('email'" in contact
    assert "OBJECT_CONSTRUCT('account_id'" in account
    assert "invalid_purpose" in contact
    assert "LENGTH(TRIM(PURPOSE)) > 200" in contact
    # Event rationale is purpose only; do not bind email into the insert.
    event_insert = contact.index("INSERT INTO GOVERNANCE.USER_FEEDBACK_EVENTS")
    commit_at = contact.index("COMMIT", event_insert)
    event_block = contact[event_insert:commit_at]
    assert ":purpose_trim" in event_block.lower() or ":PURPOSE" in event_block
    assert ":email" not in event_block.lower()
    assert "email_value" not in event_block


def test_operator_redaction_replaces_message_and_removes_linkage() -> None:
    redact = _redact_sql(_migration_source())
    assert "SET message = '[redacted]'" in redact
    assert "DELETE FROM GOVERNANCE.USER_FEEDBACK_CONTACT" in redact
    assert "DELETE FROM GOVERNANCE.USER_FEEDBACK_ACCOUNT" in redact
    assert "'redacted'" in redact
    assert "UPDATE GOVERNANCE.USER_FEEDBACK_EVENTS" not in redact
    assert "invalid_reason" in redact
    assert "LENGTH(TRIM(REASON)) > 500" in redact


def test_triage_runbook_documents_owner_surface_and_untrusted_text() -> None:
    text = TRIAGE_DOC.read_text(encoding="utf-8")
    assert "ATLAS_DEV_OWNER" in text
    assert "ATLAS_PROD_OWNER" in text
    assert "no scheduled job" in text.lower() or "not by a scheduled job" in text.lower()
    assert "feedback_id" in text
    assert "Do not paste contact email" in text or "without pasting email" in text.lower()
    assert "untrusted" in text.lower()
    assert "must not be executed as SQL" in text.lower() or "Do not execute it as SQL" in text
    assert "24-month" in text
    assert "SP_REDACT_FEEDBACK_FOR_ACCOUNT" in text
    assert "SP_REDACT_USER_FEEDBACK" in text
    assert "streamlit_approval" in text
    assert "streamlit_explorer" in text
