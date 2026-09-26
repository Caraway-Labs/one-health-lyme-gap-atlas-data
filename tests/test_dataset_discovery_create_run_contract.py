"""Guard the draft create-run transaction boundary before live Snowflake proof."""

from pathlib import Path

from lyme_gap_atlas_data.migrations import migration_plan

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "migrations" / "V107__dataset_discovery_create_run_procedure.sql"


def test_v107_is_ledger_managed_for_both_environments() -> None:
    for environment in ("DEV", "PROD"):
        database = f"ONE_HEALTH_LYME_GAP_ATLAS_{environment}"
        item = next(item for item in migration_plan(database) if item["version"] == "V107")
        assert item["filename"] == SQL.name
        assert len(item["sha256"]) == 64


def test_create_run_has_serialized_transaction_and_no_role_grants() -> None:
    sql = SQL.read_text(encoding="utf-8").upper()
    assert "BEGIN TRANSACTION" in sql
    assert "UPDATE DATASET_DISCOVERY.WRITE_SERIALIZATION" in sql
    assert "COMMIT" in sql and "ROLLBACK" in sql
    assert "WHERE OPERATION_KEY = ?" in sql
    assert "CONFLICTING_OPERATION_REPLAY" in sql
    assert "RETRY_PARENT_NOT_TERMINAL" in sql
    assert "CREATE ROLE" not in sql
    assert "GRANT " not in sql
