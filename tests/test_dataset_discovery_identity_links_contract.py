"""The identity-link migration exposes only deterministic, bounded catalog joins."""

from pathlib import Path

from lyme_gap_atlas_data.migrations import load_migrations, migration_plan, render_migration

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "migrations" / "V111__dataset_discovery_identity_links.sql"


def test_identity_link_view_is_in_both_protected_migration_plans() -> None:
    migration = next(item for item in load_migrations() if item.version == "V111")
    assert migration.filename == SQL.name
    for environment in ("DEV", "PROD"):
        database = f"ONE_HEALTH_LYME_GAP_ATLAS_{environment}"
        item = next(item for item in migration_plan(database) if item["version"] == "V111")
        assert item["filename"] == SQL.name
        assert len(item["sha256"]) == 64
        rendered = render_migration(migration, database)
        assert f"USE DATABASE {database};" in rendered
        assert "{{ DATABASE }}" not in rendered


def test_link_view_has_canonical_equalities_and_no_unreviewed_authority() -> None:
    sql = SQL.read_text(encoding="utf-8").upper()
    assert "CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CANDIDATE_IDENTITY_LINKS" in sql
    assert "FROM DATASET_DISCOVERY.V_CANDIDATE_SUMMARY CANDIDATE" in sql
    assert "JOIN GOVERNANCE.CATALOG_RESOURCES LINKED" in sql
    assert "LINKED.CATALOG_RESOURCE_ID <> CANDIDATE.CATALOG_RESOURCE_ID" in sql
    assert "LINKED.RESOURCE_KEY = CANDIDATE.RESOURCE_KEY" in sql
    assert "LINKED.CANONICAL_SOURCE_URL = CANDIDATE.CANONICAL_SOURCE_URL" in sql
    assert "LINKED.CATALOG_DATASET_ID = CANDIDATE.CATALOG_DATASET_ID" in sql
    assert "'EXACT_DUPLICATE'" in sql
    assert "'ALTERNATE_DISTRIBUTION'" in sql
    projection = sql.split("FROM DATASET_DISCOVERY.V_CANDIDATE_SUMMARY")[0]
    assert "SELECT *" not in projection
    for unsafe in ("RESOURCE_PAYLOAD", "METADATA_PAYLOAD", "ARTIFACT_URI", "APPROVED_DECISION_ID"):
        assert unsafe not in projection
    for invented in ("'MIRROR'", "'REVISION'", "'SUPERSESSION'"):
        assert invented not in projection
    statements = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    assert "GRANT " not in statements
    assert "CREATE ROLE" not in statements
