"""Data #513: the public observation view has a closed publication boundary."""

from pathlib import Path

from lyme_gap_atlas_data.migrations import (
    load_migrations,
    migration_execution_role,
    migration_plan,
    render_migration,
)

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "migrations/V127__current_county_observation_projection.sql").read_text()


def test_projection_is_current_release_only_and_additive() -> None:
    assert "CREATE VIEW IF NOT EXISTS PRESENTATION.CURRENT_COUNTY_OBSERVATIONS_V" in SQL
    assert "p.current_release_id" in SQL
    assert "r.status = 'PUBLISHED'" in SQL
    assert "p.pointer_key = 'ATLAS'" in SQL
    assert "m.release_version = r.release_id" in SQL
    assert "m.measure_id = o.measure_id" in SQL
    assert "CURRENT_MEASURE_METADATA_V" in SQL  # V124 canonicalizes legacy IDs.
    assert "CREATE TABLE" not in SQL
    assert "UPDATE " not in SQL


def test_closed_measure_and_period_scope() -> None:
    assert (
        "o.measure_id IN ('human_status', 'case_count_floor_2023', 'incidence_floor_2023')" in SQL
    )
    assert "o.source_key = 'human'" in SQL
    assert "o.temporal_window = '2023'" in SQL
    assert "m.temporal_grain = '2023'" in SQL
    assert "DATE '2023-01-01'" in SQL
    assert "DATE '2023-12-31'" in SQL
    assert "state_unallocated_records_2023" not in SQL
    assert "through 2025-12-31" not in SQL
    assert "TRY_TO_DATE" not in SQL


def test_county_identity_and_source_safe_fields() -> None:
    assert "c.fips = o.fips" in SQL
    assert "REGEXP_LIKE(o.fips, '[0-9]{5}')" in SQL
    assert "o.geography_semantics = 'COUNTY_FIPS_5'" in SQL
    assert "o.observation_id" in SQL
    assert "o.value," in SQL
    assert "o.value_state," in SQL
    assert "o.retrieved_at," in SQL
    assert "CAST(NULL" not in SQL  # Unknown metadata stays null from the governed view.
    for internal in ("o.artifact_id", "o.ingestion_run_id", "o.source_row_hash"):
        assert internal not in SQL


def test_read_role_gets_only_view_select() -> None:
    assert "GRANT SELECT ON VIEW PRESENTATION.CURRENT_COUNTY_OBSERVATIONS_V" in SQL
    assert "TO ROLE OH_LYME_{{ ENV }}_READ" in SQL
    assert "GRANT SELECT ON TABLE" not in SQL
    assert "GRANT SELECT ON ALL" not in SQL


def test_migration_uses_narrow_owner_and_both_environments() -> None:
    migration = next(item for item in load_migrations() if item.version == "V127")
    for env in ("DEV", "PROD"):
        database = f"ONE_HEALTH_LYME_GAP_ATLAS_{env}"
        assert migration_execution_role(migration, database) == f"OH_LYME_{env}_OWNER"
        assert "V127" in {item["version"] for item in migration_plan(database)}
        assert f"OH_LYME_{env}_READ" in render_migration(migration, database)
