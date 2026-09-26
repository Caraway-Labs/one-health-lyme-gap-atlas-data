"""Keep V103 grants aligned with the protected worker's actual V103 SQL."""

import re
from pathlib import Path

from lyme_gap_atlas_data.migrations import load_migrations, render_migration

ROOT = Path(__file__).resolve().parents[1]
V103 = ROOT / "migrations/V103__bounded_ingestion_partitions_and_revisions.sql"
WORKFLOW = ROOT / ".github/workflows/run-ingestion.yml"
CHECKPOINTS = ROOT / "src/lyme_gap_atlas_data/ingestion/checkpoints.py"
RUNTIME = ROOT / "src/lyme_gap_atlas_data/ingestion/runtime.py"
TABLES = (
    "INGESTION_RUN_NORMALIZED_PARTITIONS",
    "INGESTION_RUN_PARTITION_COMPLETIONS",
    "GOVERNED_SOURCE_RECORD_REVISIONS",
)


def test_v103_runtime_role_matches_protected_worker_in_both_environments() -> None:
    source = V103.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    migration = next(item for item in load_migrations() if item.version == "V103")

    assert "PIPELINE_RUNTIME" not in source
    for environment in ("DEV", "PROD"):
        role = f"OH_LYME_{environment}_RUNTIME"
        assert f'"{environment}": "{role}"' in workflow
        rendered = render_migration(migration, f"ONE_HEALTH_LYME_GAP_ATLAS_{environment}")
        assert "PIPELINE_RUNTIME" not in rendered
        for table in TABLES:
            assert (
                f"GRANT SELECT, INSERT ON TABLE GOVERNANCE.{table}\n    TO ROLE {role};"
            ) in rendered


def test_v103_grants_cover_only_actual_insert_and_read_operations() -> None:
    source = V103.read_text(encoding="utf-8")
    checkpoint_sql = CHECKPOINTS.read_text(encoding="utf-8")
    revision_sql = RUNTIME.read_text(encoding="utf-8")
    for table in TABLES:
        sql = revision_sql if table == "GOVERNED_SOURCE_RECORD_REVISIONS" else checkpoint_sql
        assert f"MERGE INTO GOVERNANCE.{table}" in sql
        if table == "GOVERNED_SOURCE_RECORD_REVISIONS":
            assert '"SELECT record_id, source_row_hash, normalized_sha256 FROM "' in sql
            assert f'"GOVERNANCE.{table} "' in sql
        else:
            assert re.search(rf"FROM\s+GOVERNANCE\.{table}\b", sql)
        start = sql.index(f"MERGE INTO GOVERNANCE.{table}")
        insert = sql.index("WHEN NOT MATCHED THEN INSERT", start)
        merge_before_insert = sql[start:insert]
        assert "WHEN MATCHED THEN UPDATE" not in merge_before_insert
        assert "WHEN MATCHED THEN DELETE" not in merge_before_insert
        assert (
            f"GRANT SELECT, INSERT ON TABLE GOVERNANCE.{table}\n"
            "    TO ROLE OH_LYME_{{ ENV }}_RUNTIME;"
        ) in source
        assert not re.search(
            rf"GRANT\s+[^;]*\b(?:UPDATE|DELETE|TRUNCATE)\b[^;]*ON TABLE GOVERNANCE\.{table}",
            source,
            re.IGNORECASE,
        )


def test_v103_remains_additive_without_historical_row_mutation() -> None:
    source = V103.read_text(encoding="utf-8")
    statements = re.sub(r"--[^\n]*", "", source).upper()
    assert statements.count("CREATE TABLE IF NOT EXISTS GOVERNANCE.") == 3
    assert not re.search(r"\b(?:DROP|ALTER|UPDATE|DELETE|TRUNCATE|REVOKE)\b", statements)
    assert "SCHEMA_MIGRATIONS" not in statements
