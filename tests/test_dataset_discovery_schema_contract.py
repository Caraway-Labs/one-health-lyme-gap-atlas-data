"""Static guardrails for the proposed Dataset Discovery Snowflake boundary."""

from pathlib import Path

from lyme_gap_atlas_data.migrations import load_migrations, migration_plan, render_migration

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "migrations" / "V106__dataset_discovery_persistence_foundation.sql"


def test_v106_is_part_of_both_environment_plans() -> None:
    for environment in ("DEV", "PROD"):
        database = f"ONE_HEALTH_LYME_GAP_ATLAS_{environment}"
        plan = migration_plan(database)
        item = next(item for item in plan if item["version"] == "V106")
        assert item["filename"] == SQL.name
        assert len(item["sha256"]) == 64


def test_v106_has_required_record_and_bounded_read_surfaces() -> None:
    source = SQL.read_text(encoding="utf-8")
    for name in (
        "RUNS",
        "CANDIDATE_OUTCOMES",
        "RECOMMENDATIONS",
        "RECOMMENDATION_EVIDENCE",
        "SEARCH_EXPANSION_PROPOSALS",
        "REVIEW_EVENTS",
        "V_CANDIDATE_SUMMARY",
        "V_CANDIDATE_EVIDENCE",
        "V_CANDIDATE_OBSERVATION_FIELDS",
        "V_CANDIDATE_GOVERNED_STATUS",
        "V_PENDING_RECOMMENDATIONS",
        "V_RECOMMENDATION_HISTORY",
        "V_ACCEPTED_RECOMMENDATIONS_FOR_HANDOFF",
        "V_DISCOVERY_RUN_SUMMARY",
    ):
        assert f"DATASET_DISCOVERY.{name}" in source
    assert "recommendation_version_id" in source
    assert "retry_of_run_id" in source
    summary = source.split("CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CANDIDATE_SUMMARY")[1]
    summary = summary.split("CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CANDIDATE_EVIDENCE")[0]
    assert "PARTITION BY o.ingestion_run_id, r.resource_key" in summary
    assert "ORDER BY o.observed_at DESC, d.discovered_at DESC" in summary
    assert "o.ingestion_run_id AS discovery_run_id" in summary
    assert (
        "resource_payload"
        not in source.split("CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CANDIDATE_EVIDENCE")[
            1
        ].split("CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CANDIDATE_OBSERVATION_FIELDS")[0]
    )
    projection = source.split(
        "CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CANDIDATE_OBSERVATION_FIELDS"
    )[1].split("CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CANDIDATE_GOVERNED_STATUS")[0]
    assert "OBJECT_CONSTRUCT_KEEP_NULL" in projection
    assert "SELECT *" not in projection
    assert "AS field_values" in projection


def test_v106_does_not_create_role_or_grant_privilege_before_adr_review() -> None:
    source = SQL.read_text(encoding="utf-8").upper()
    assert "CREATE ROLE" not in source
    assert "GRANT " not in source
    assert "MANAGE GRANTS" not in source
    for environment in ("DEV", "PROD"):
        database = f"ONE_HEALTH_LYME_GAP_ATLAS_{environment}"
        migration = next(item for item in load_migrations() if item.version == "V106")
        rendered = render_migration(migration, database)
        assert f"USE DATABASE {database};" in rendered
        assert "{{ DATABASE }}" not in rendered
