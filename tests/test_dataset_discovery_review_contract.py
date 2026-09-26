"""Guard the draft authenticated review event boundary before live DEV proof."""

from pathlib import Path

from lyme_gap_atlas_data.migrations import load_migrations, migration_plan, render_migration

SQL = (
    Path(__file__).resolve().parents[1] / "migrations" / "V109__dataset_discovery_review_events.sql"
)


def test_v109_is_ledger_managed_and_role_name_is_environment_local() -> None:
    for environment in ("DEV", "PROD"):
        database = f"ONE_HEALTH_LYME_GAP_ATLAS_{environment}"
        item = next(item for item in migration_plan(database) if item["version"] == "V109")
        assert item["filename"] == SQL.name
        assert len(item["sha256"]) == 64
        migration = next(item for item in load_migrations() if item.version == "V109")
        rendered = render_migration(migration, database)
        assert f"OH_LYME_{environment}_DATASET_DISCOVERY_REVIEWER" in rendered


def test_owner_rights_review_uses_authenticated_session_not_supplied_identity() -> None:
    sql = SQL.read_text(encoding="utf-8").upper()
    assert "EXECUTE AS OWNER" in sql
    for property_name in ("PRINCIPAL_NAME", "PRINCIPAL_TYPE", "ROLE"):
        assert f"SYS_CONTEXT('SNOWFLAKE$SESSION', '{property_name}')" in sql
    assert "PRINCIPAL_TYPE !== 'USER_PERSON'" in sql
    assert "REVIEWER_NOT_ALLOWLISTED" in sql
    assert "REVIEWER_USER: TRUE" not in sql
    assert "REVIEWER_ROLE: TRUE" not in sql
    assert "CREATE ROLE" not in sql
    assert "GRANT " not in sql


def test_review_transition_is_serialized_append_only_and_replay_safe() -> None:
    sql = SQL.read_text(encoding="utf-8").upper()
    assert "BEGIN TRANSACTION" in sql
    assert "UPDATE DATASET_DISCOVERY.WRITE_SERIALIZATION" in sql
    assert "INSERT INTO DATASET_DISCOVERY.REVIEW_EVENTS" in sql
    assert "UPDATE DATASET_DISCOVERY.REVIEW_EVENTS" not in sql
    assert "DELETE FROM DATASET_DISCOVERY.REVIEW_EVENTS" not in sql
    assert "CONFLICTING_REVIEW_REPLAY" in sql
    assert "STALE_REVIEW_STATE" in sql
    assert "TERMINAL_REVIEW_REQUIRES_CORRECTION" in sql
    assert "ACCEPTED_REVIEW_IS_TERMINAL" in sql
    assert "COMMIT" in sql and "ROLLBACK" in sql


def test_review_views_expose_current_state_and_exact_version() -> None:
    sql = SQL.read_text(encoding="utf-8").upper()
    for view in (
        "V_CURRENT_REVIEW_STATE",
        "V_PENDING_RECOMMENDATIONS",
        "V_RECOMMENDATION_HISTORY",
        "V_ACCEPTED_RECOMMENDATIONS_FOR_HANDOFF",
        "V_REVIEW_EVENT_RECEIPTS",
    ):
        assert f"CREATE OR REPLACE VIEW DATASET_DISCOVERY.{view}" in sql
    assert "PARTITION BY RECOMMENDATION_VERSION_ID" in sql
    assert "ORDER BY EVENT_SEQUENCE DESC" in sql
    assert "ACCEPTED_FOR_INVESTIGATION" in sql
