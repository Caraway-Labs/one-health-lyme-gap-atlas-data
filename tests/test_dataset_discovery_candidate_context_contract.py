"""Prior assessment and artifact metadata stay in bounded data-owned views."""

from pathlib import Path

from lyme_gap_atlas_data.migrations import load_migrations, migration_plan, render_migration

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "migrations" / "V112__dataset_discovery_candidate_context_views.sql"


def test_candidate_context_views_are_in_both_protected_plans() -> None:
    migration = next(item for item in load_migrations() if item.version == "V112")
    assert migration.filename == SQL.name
    for environment in ("DEV", "PROD"):
        database = f"ONE_HEALTH_LYME_GAP_ATLAS_{environment}"
        item = next(item for item in migration_plan(database) if item["version"] == "V112")
        assert item["filename"] == SQL.name
        assert len(item["sha256"]) == 64
        rendered = render_migration(migration, database)
        assert f"USE DATABASE {database};" in rendered
        assert "{{ DATABASE }}" not in rendered


def test_views_preserve_snapshot_cutoff_without_exposing_private_artifacts() -> None:
    sql = SQL.read_text(encoding="utf-8").upper()
    assert "CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CANDIDATE_PRIOR_ASSESSMENT" in sql
    assert "ASSESSMENT.ASSESSED_AT <= EVIDENCE.OBSERVED_AT" in sql
    assert "ROW_NUMBER() OVER" in sql
    assert "CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CANDIDATE_ARTIFACT_METADATA" in sql
    assert "ARTIFACT.ARTIFACT_ID = EVIDENCE.ARTIFACT_ID" in sql
    assert "ARTIFACT.INGESTION_RUN_ID = EVIDENCE.DISCOVERY_RUN_ID" in sql
    statements = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    for forbidden in (
        "ARTIFACT_URI",
        "RESOURCE_PAYLOAD",
        "METADATA_PAYLOAD",
        "APPROVED_DECISION_ID",
        "GRANT ",
        "CREATE ROLE",
        "SELECT *",
    ):
        assert forbidden not in statements
