"""Guard the draft create-run transaction boundary before live Snowflake proof."""

from pathlib import Path

from lyme_gap_atlas_data.migrations import migration_plan

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "migrations" / "V107__dataset_discovery_runtime_procedures.sql"


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


def test_candidate_outcome_reuses_lock_and_checks_snapshot_identity() -> None:
    sql = SQL.read_text(encoding="utf-8").upper()
    marker = "CREATE OR REPLACE PROCEDURE DATASET_DISCOVERY.SP_RECORD_CANDIDATE_OUTCOME"
    outcome = sql.split(marker)[1]
    assert "BEGIN TRANSACTION" in outcome
    assert "UPDATE DATASET_DISCOVERY.WRITE_SERIALIZATION" in outcome
    assert "WHERE OPERATION_KEY = ?" in outcome
    assert "CANDIDATE_NOT_IN_SNAPSHOT" in outcome
    assert "CANDIDATE_IDENTITY_MISMATCH" in outcome
    assert "RUN_ALREADY_TERMINAL" in outcome
    assert "CANDIDATE_ALREADY_RECORDED" in outcome
    assert "CANDIDATE_ALREADY_RECOMMENDED" in outcome
    assert "SHA2(?, 256)" in outcome
    assert "ROLLBACK" in outcome


def test_finalization_recomputes_durable_counts_and_preserves_usage() -> None:
    sql = SQL.read_text(encoding="utf-8").upper()
    marker = "CREATE OR REPLACE PROCEDURE DATASET_DISCOVERY.SP_FINALIZE_RUN"
    finalization = sql.split(marker)[1].split(
        "CREATE OR REPLACE PROCEDURE DATASET_DISCOVERY.SP_RECORD_CANDIDATE_OUTCOME"
    )[0]
    assert "BEGIN TRANSACTION" in finalization
    assert "UPDATE DATASET_DISCOVERY.WRITE_SERIALIZATION" in finalization
    assert "CONFLICTING_FINALIZATION_REPLAY" in finalization
    assert "DURABLE_COUNTER_MISMATCH" in finalization
    assert "CANDIDATE_OUTCOMES" in finalization
    assert "RECOMMENDATIONS" in finalization
    assert "BUDGET_USAGE" in finalization
    assert "ROLLBACK" in finalization
