"""Handoff revalidates pinned evidence and reviewed hard-policy attribution."""

from pathlib import Path

from lyme_gap_atlas_data.migrations import load_migrations, migration_plan, render_migration

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "migrations" / "V113__dataset_discovery_handoff_snapshot_validation.sql"


def test_handoff_hardening_is_a_protected_forward_migration() -> None:
    migration = next(item for item in load_migrations() if item.version == "V113")
    assert migration.filename == SQL.name
    for environment in ("DEV", "PROD"):
        database = f"ONE_HEALTH_LYME_GAP_ATLAS_{environment}"
        item = next(item for item in migration_plan(database) if item["version"] == "V113")
        assert item["filename"] == SQL.name
        assert len(item["sha256"]) == 64
        rendered = render_migration(migration, database)
        assert f"USE DATABASE {database};" in rendered
        assert f"OH_LYME_{environment}_DATASET_DISCOVERY_REVIEWER" in rendered
        assert "{{ DATABASE }}" not in rendered


def test_handoff_requires_snapshot_and_nonempty_reviewed_rights_evidence() -> None:
    sql = SQL.read_text(encoding="utf-8")
    assert "AND o.ingestion_run_id = ?" in sql
    assert "resource_key, snapshot_id]);" in sql
    assert "LENGTH(TRIM(reviewed_by)) > 0" in sql
    assert "LENGTH(TRIM(evidence_reference)) > 0" in sql
    assert "BEGIN TRANSACTION" in sql
    assert "WRITE_SERIALIZATION" in sql
    assert "CONFLICTING_HANDOFF_REPLAY" in sql
    assert "COMMIT" in sql and "ROLLBACK" in sql
    assert "SP_APPROVE" not in sql.upper()
    statements = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    assert "GRANT " not in statements.upper()


def test_missing_or_foreign_evidence_fails_before_investigation_intake() -> None:
    sql = SQL.read_text(encoding="utf-8")
    intake = sql.index("INSERT INTO GOVERNANCE.DATASET_DISCOVERY_INVESTIGATION_REQUESTS")
    assert sql.index("if (evidence_ids.length < 1 || evidence_ids.length > 100)") < intake
    assert sql.index("throw new Error('MISSING_EVIDENCE')") < intake
    assert sql.index("throw new Error('AMBIGUOUS_EVIDENCE')") < intake
    assert sql.index("throw new Error('EVIDENCE_CATALOG_MISMATCH')") < intake
    assert "o.catalog_dataset_id = ?" in sql
    assert "o.catalog_resource_id = ?" in sql
    assert "o.canonical_resource_key = ?" in sql


def test_stale_snapshot_fails_before_investigation_intake() -> None:
    sql = SQL.read_text(encoding="utf-8")
    intake = sql.index("INSERT INTO GOVERNANCE.DATASET_DISCOVERY_INVESTIGATION_REQUESTS")
    assert "o.ingestion_run_id = ?" in sql
    assert "resource_key, snapshot_id]);" in sql
    assert sql.index("throw new Error('EVIDENCE_CATALOG_MISMATCH')") < intake
    assert sql.index("snowflake.execute({sqlText: 'ROLLBACK'});") > intake
