"""Protect the narrow, draft data-owned investigation handoff boundary."""

from pathlib import Path

from lyme_gap_atlas_data.migrations import load_migrations, migration_plan, render_migration

SQL = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "V110__dataset_discovery_governed_handoff.sql"
)


def test_v110_uses_protected_migration_ledger_and_environment_role() -> None:
    migration = next(item for item in load_migrations() if item.version == "V110")
    for environment in ("DEV", "PROD"):
        database = f"ONE_HEALTH_LYME_GAP_ATLAS_{environment}"
        assert any(
            item["version"] == "V110" and item["filename"] == SQL.name
            for item in migration_plan(database)
        )
        assert f"OH_LYME_{environment}_DATASET_DISCOVERY_REVIEWER" in render_migration(
            migration, database
        )


def test_handoff_has_no_approval_or_ingestion_write_path() -> None:
    sql = SQL.read_text(encoding="utf-8").upper()
    assert "EXECUTE AS OWNER" in sql
    assert "SYS_CONTEXT('SNOWFLAKE$SESSION', 'PRINCIPAL_NAME')" in sql
    assert "USER_PERSON" in sql
    assert "REVIEWER_NOT_ALLOWLISTED" in sql
    assert "BEGIN TRANSACTION" in sql
    assert "UPDATE DATASET_DISCOVERY.WRITE_SERIALIZATION" in sql
    assert "CONFLICTING_HANDOFF_REPLAY" in sql
    assert "REJECTED_OR_STALE_HANDOFF" in sql
    assert "INSERT INTO GOVERNANCE.DATASET_DISCOVERY_INVESTIGATION_REQUESTS" in sql
    for table in ("DATA_SOURCE_VERSIONS", "MANUAL_REVIEW_DECISIONS", "INGESTION_RUNS"):
        assert f"INSERT INTO GOVERNANCE.{table}" not in sql
        assert f"UPDATE GOVERNANCE.{table}" not in sql
    assert "GRANT USAGE" not in sql


def test_unknown_rights_can_be_investigated_without_acquisition() -> None:
    sql = SQL.read_text(encoding="utf-8").upper()
    assert "KNOWN_PROHIBITED" in sql
    assert "KNOWN_RESTRICTED" in sql
    assert "CONTROLLED_ACCESS" in sql
    assert "NO_AUTOMATED_ACQUISITION" in sql
    assert "RIGHTS_ASSERTION" in sql
    assert "POLICY_BLOCKED" in sql
    assert "V_HANDOFF_RECEIPTS" in sql
    assert "V_DATASET_DISCOVERY_INVESTIGATION_QUEUE" in sql
    assert "RELATIONSHIP_TYPE" in sql


def test_already_governed_reuses_authoritative_resource_identity_without_onboarding() -> None:
    foundation = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "V106__dataset_discovery_persistence_foundation.sql"
    ).read_text(encoding="utf-8")
    sql = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "V113__dataset_discovery_handoff_snapshot_validation.sql"
    ).read_text(encoding="utf-8")
    assert (
        "LEFT JOIN GOVERNANCE.DATA_SOURCE_VERSIONS v ON v.resource_key = r.resource_key"
        in foundation
    )
    assert "v.retired_at IS NULL AND v.status IN ('APPROVED','CONDITIONAL')" in foundation
    assert "SELECT already_governed FROM DATASET_DISCOVERY.V_CANDIDATE_GOVERNED_STATUS" in sql
    assert "'WHERE resource_key = ?', [resource_key]" in sql
    assert "governed ? 'ALREADY_GOVERNED' : 'HANDED_OFF'" in sql
    assert "var investigation_status = disposition === 'HANDED_OFF' ? 'PENDING' :" in sql
    assert "resource_key, catalog_dataset_id, " in sql
    assert "catalog_resource_id, evidence_snapshot_id" in sql
    assert "DATA_SOURCE_VERSIONS" not in sql
    assert "MANUAL_REVIEW_DECISIONS" not in sql
    assert "INGESTION_RUNS" not in sql
