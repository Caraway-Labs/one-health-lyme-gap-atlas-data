"""Guard the draft atomic recommendation boundary before live DEV proof."""

from pathlib import Path

from lyme_gap_atlas_data.migrations import migration_plan

SQL = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "V108__dataset_discovery_recommendation_commit.sql"
)


def test_v108_is_ledger_managed_in_both_environments() -> None:
    for environment in ("DEV", "PROD"):
        database = f"ONE_HEALTH_LYME_GAP_ATLAS_{environment}"
        item = next(item for item in migration_plan(database) if item["version"] == "V108")
        assert item["filename"] == SQL.name
        assert len(item["sha256"]) == 64


def test_recommendation_evidence_and_proposals_commit_atomically() -> None:
    sql = SQL.read_text(encoding="utf-8").upper()
    assert "CREATE OR REPLACE PROCEDURE DATASET_DISCOVERY.SP_COMMIT_RECOMMENDATION" in sql
    assert "EXECUTE AS OWNER" in sql
    assert "BEGIN TRANSACTION" in sql
    assert "UPDATE DATASET_DISCOVERY.WRITE_SERIALIZATION" in sql
    assert "GETNUMROWSAFFECTED() !== 1" in sql
    for table in (
        "RECOMMENDATIONS",
        "RECOMMENDATION_EVIDENCE",
        "SEARCH_EXPANSION_PROPOSALS",
    ):
        assert f"INSERT INTO DATASET_DISCOVERY.{table}" in sql
    assert "SNOWFLAKE.EXECUTE({SQLTEXT: 'COMMIT'})" in sql
    assert "SNOWFLAKE.EXECUTE({SQLTEXT: 'ROLLBACK'})" in sql
    assert "CREATE ROLE" not in sql
    assert "GRANT " not in sql


def test_replay_and_evidence_are_checked_before_write() -> None:
    sql = SQL.read_text(encoding="utf-8").upper()
    for marker in (
        "CONFLICTING_OPERATION_REPLAY",
        "INCOMPLETE_RECOMMENDATION_STATE",
        "CANDIDATE_NOT_IN_SNAPSHOT",
        "OBSERVATION_NOT_IN_SNAPSHOT",
        "OBSERVED_FACT_NOT_RETAINED",
        "RANKING_EVIDENCE_MISMATCH",
        "DIMENSION_EVIDENCE_MISMATCH",
        "PRIORITY_FORMULA_MISMATCH",
        "ASSERTION_HASH_MISMATCH",
        "RUNTIME_CANNOT_ASSERT_RIGHTS_CLEARANCE",
        "RUN_ALREADY_TERMINAL",
    ):
        assert marker in sql
