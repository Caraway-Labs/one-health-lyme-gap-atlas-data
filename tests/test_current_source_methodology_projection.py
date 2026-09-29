"""Data #515: the reviewed public source and methodology mapping is closed."""

from pathlib import Path

from lyme_gap_atlas_data.migrations import (
    load_migrations,
    migration_execution_role,
    render_migration,
)

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "migrations/V128__current_source_methodology_metadata.sql").read_text()
PRIOR = (ROOT / "migrations/V127__current_county_observation_projection.sql").read_text()


def test_source_identity_and_publisher_are_exact_tuple_bound() -> None:
    assert "s.source_key, s.label, s.vintage, s.source_url, s.note," in SQL
    assert "s.source_id, s.dataset_id," in SQL
    for predicate in (
        "s.source_key = 'human'",
        "s.source_id = 'cdc_lyme'",
        "s.dataset_id = 'x5j9-wybp'",
        "THEN 'Centers for Disease Control and Prevention'",
        "ELSE NULL END AS publisher",
    ):
        assert predicate in SQL
    assert "CAST(NULL AS TIMESTAMP_LTZ) AS upstream_updated_at" in SQL
    assert "CAST(NULL AS TIMESTAMP_LTZ) AS source_retrieved_at" in SQL
    assert "s.label AS publisher" not in SQL


def test_method_id_meaning_and_release_binding_are_explicit() -> None:
    mappings = (
        (
            "human_status",
            "human_source_native_status_mapping_v1",
            "source-native status mapping",
            "Published floors are not complete incidence.",
        ),
        (
            "case_count_floor_2023",
            "human_confirmed_probable_case_floor_v1",
            "x5j9 confirmed plus probable",
            "Privacy-protected floor.",
        ),
        (
            "incidence_floor_2023",
            "human_case_floor_population_incidence_v1",
            "case floor divided by population",
            "Not complete incidence.",
        ),
    )
    for measure, method_id, text, limitation in mappings:
        assert all(value in SQL for value in (measure, method_id, text, limitation))
    assert "a.approved_text = m.methodology" in SQL
    assert "a.approved_limitation = m.limitation" in SQL
    assert "r.methodology_version" in SQL
    assert "r.status = 'PUBLISHED'" in SQL
    assert "p.current_release_id" in SQL
    assert "transformation_version AS methodology_id" not in SQL


def test_observation_contract_is_additive_and_preserves_rows() -> None:
    for predicate in (
        "o.measure_id IN ('human_status', 'case_count_floor_2023', 'incidence_floor_2023')",
        "o.source_key = 'human'",
        "o.temporal_window = '2023'",
        "REGEXP_LIKE(o.fips, '[0-9]{5}')",
        "o.value,",
        "o.value_state,",
        "o.retrieved_at,",
        "o.transformation_version,",
        "o.limitations AS observation_limitations,",
        "m.limitation AS measure_limitation,",
        "r.limitations AS release_limitations",
    ):
        assert predicate in PRIOR and predicate in SQL
    assert "LEFT JOIN PRESENTATION.CURRENT_METHODOLOGY_METADATA_V mm" in SQL
    assert "mm.release_version = r.release_id AND mm.measure_id = m.measure_id" in SQL
    assert "s.source_id,\n       s.dataset_id,\n       mm.methodology_id" in SQL


def test_only_consumer_safe_views_receive_new_grants() -> None:
    assert SQL.count("COPY GRANTS AS") == 2
    assert SQL.count("TO ROLE OH_LYME_{{ ENV }}_READ") == 3
    assert "GRANT SELECT ON TABLE" not in SQL
    assert "GRANT SELECT ON ALL" not in SQL
    for forbidden in (
        "artifact_id",
        "ingestion_run_id",
        "source_row_hash",
        "source_version_id",
        "created_by",
        "approved_by",
    ):
        assert forbidden not in SQL


def test_migration_uses_narrow_owner_in_both_environments() -> None:
    migration = next(item for item in load_migrations() if item.version == "V128")
    for env in ("DEV", "PROD"):
        database = f"ONE_HEALTH_LYME_GAP_ATLAS_{env}"
        assert migration_execution_role(migration, database) == f"OH_LYME_{env}_OWNER"
        assert f"OH_LYME_{env}_READ" in render_migration(migration, database)
