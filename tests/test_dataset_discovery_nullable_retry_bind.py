"""Guard the DEV-only forward fix for nullable create-run retry IDs."""

from pathlib import Path

import pytest

from lyme_gap_atlas_data.migrations import load_migrations, migration_plan, render_migration

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "migrations/V116__dev_dataset_discovery_nullable_retry_bind.sql"


def test_v116_is_dev_only_and_keeps_existing_procedure_boundary() -> None:
    migration = next(item for item in load_migrations() if item.version == "V116")
    assert "V116" in {item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_DEV")}
    assert "V116" not in {
        item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    }
    with pytest.raises(ValueError, match="DEV-only"):
        render_migration(migration, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    sql = SQL.read_text(encoding="utf-8")
    assert "var retry_of_run_id = optional(P_RETRY_OF_RUN_ID, 200, 'RETRY_ID');" in sql
    assert "[P_REQUESTED_RUN_ID, P_OPERATION_KEY, retry_of_run_id, m.mode" in sql
    assert "if (original_retry !== retry_of_run_id ||" in sql
    assert "if (retry_of_run_id !== null)" in sql
    assert "COPY GRANTS" in sql
    assert "TO ROLE OH_LYME_DEV_DATASET_DISCOVERY_WRITE_OWNER COPY CURRENT GRANTS" in sql
    assert "UPDATE DATASET_DISCOVERY.WRITE_SERIALIZATION" in sql
    assert "BEGIN TRANSACTION" in sql and "ROLLBACK" in sql
