"""Data #499 migration contract checks; live grants require separate Snowflake proof."""

import sqlite3

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    PROD_DATABASE,
    load_migrations,
    migration_execution_role,
    render_migration,
)


def test_current_metadata_migration_is_bounded() -> None:
    migration = next(item for item in load_migrations() if item.version == "V123")
    for database, env in ((DEV_DATABASE, "DEV"), (PROD_DATABASE, "PROD")):
        sql = render_migration(migration, database).upper()
        assert migration_execution_role(migration, database) == f"OH_LYME_{env}_OWNER"
        assert f"TO ROLE OH_LYME_{env}_READ" in sql
        assert sql.count("GRANT SELECT ON VIEW") == 2
        assert "GRANT SELECT ON TABLE" not in sql
        assert "SEMANTIC_OBSERVATIONS" not in sql
        assert "CURRENT_INDICATOR_METADATA_V" in sql
        assert "CURRENT_MEASURE_METADATA_V" in sql
        assert sql.count("P.POINTER_KEY = 'ATLAS'") == 2
        assert sql.count("R.STATUS = 'PUBLISHED'") == 2
        assert sql.count("R.RELEASE_ID = P.CURRENT_RELEASE_ID") == 2
        for restricted in ("ARTIFACT_ID", "INGESTION_RUN_ID", "SOURCE_ROW_HASH", "RAW_PAYLOAD"):
            assert restricted not in sql


def test_measure_identity_correction_is_view_only() -> None:
    migration = next(item for item in load_migrations() if item.version == "V124")
    for database, env in ((DEV_DATABASE, "DEV"), (PROD_DATABASE, "PROD")):
        sql = render_migration(migration, database).upper()
        assert migration_execution_role(migration, database) == f"OH_LYME_{env}_OWNER"
        assert f"TO ROLE OH_LYME_{env}_READ" in sql
        assert "UPDATE " not in sql
        assert "SEMANTIC_OBSERVATIONS" not in sql
        assert "DIRECT_INDICATOR.INDICATOR_ID = M.INDICATOR_ID" in sql
        assert "LEGACY_INDICATOR.INDICATOR_ID = M.MEASURE_ID" in sql


def test_current_pointer_excludes_candidate_and_follows_rollback() -> None:
    migration = next(item for item in load_migrations() if item.version == "V123")
    correction = next(item for item in load_migrations() if item.version == "V124")
    connection = sqlite3.connect(":memory:")
    connection.execute("ATTACH DATABASE ':memory:' AS PRESENTATION")
    connection.executescript(
        """
        CREATE TABLE PRESENTATION.SEMANTIC_RELEASE_POINTER
          (pointer_key TEXT, current_release_id TEXT);
        CREATE TABLE PRESENTATION.SEMANTIC_RELEASES
          (release_id TEXT, status TEXT, schema_version TEXT);
        CREATE TABLE PRESENTATION.SEMANTIC_INDICATORS
          (release_id TEXT, indicator_id TEXT, label TEXT, description TEXT, limitation TEXT);
        CREATE TABLE PRESENTATION.SEMANTIC_MEASURES
          (release_id TEXT, measure_id TEXT, indicator_id TEXT, label TEXT,
           data_type TEXT, unit TEXT, geography_semantics TEXT,
           temporal_resolution TEXT, missingness_semantics TEXT,
           methodology TEXT, limitation TEXT);
        INSERT INTO PRESENTATION.SEMANTIC_RELEASES VALUES
          ('old', 'RETIRED', 'v1'), ('current', 'PUBLISHED', 'v2'),
          ('candidate', 'CANDIDATE', 'v3');
        INSERT INTO PRESENTATION.SEMANTIC_RELEASE_POINTER VALUES ('ATLAS', 'current');
        INSERT INTO PRESENTATION.SEMANTIC_INDICATORS VALUES
          ('old', 'old-id', 'Old', 'Old definition', 'Old limit'),
          ('current', 'stable-id', 'Current', 'Current definition', 'Current limit'),
          ('candidate', 'candidate-id', 'Candidate', 'Candidate definition', 'Candidate limit');
        INSERT INTO PRESENTATION.SEMANTIC_MEASURES VALUES
          ('old', 'old-id', 'old-measure', 'Old', 'number', 'cases', 'STATE', '2020', '', '', ''),
          ('current', 'stable-measure', 'stable-id', 'Current', 'number', 'cases',
           'COUNTY_FIPS_5', '2023', '', '', ''),
          ('candidate', 'candidate-measure', 'candidate-id', 'Candidate', 'number',
           'cases', 'STATE', '2024', '', '', '');
        """
    )
    definitions = migration.source.split("CREATE VIEW IF NOT EXISTS ")[1:]
    for definition in definitions:
        statement = definition.split(";", maxsplit=1)[0]
        connection.execute("CREATE VIEW IF NOT EXISTS " + statement)
    connection.execute("DROP VIEW PRESENTATION.CURRENT_MEASURE_METADATA_V")
    corrected_view = correction.source.split("CREATE OR REPLACE VIEW ", maxsplit=1)[1]
    connection.execute("CREATE VIEW " + corrected_view.split(";", maxsplit=1)[0])

    def ids() -> tuple[list[str], list[str]]:
        indicator_ids = [
            row[0]
            for row in connection.execute(
                "SELECT indicator_id FROM PRESENTATION.CURRENT_INDICATOR_METADATA_V"
            )
        ]
        measure_ids = [
            row[0]
            for row in connection.execute(
                "SELECT measure_id FROM PRESENTATION.CURRENT_MEASURE_METADATA_V"
            )
        ]
        return indicator_ids, measure_ids

    assert ids() == (["stable-id"], ["stable-measure"])
    connection.execute(
        "UPDATE PRESENTATION.SEMANTIC_RELEASE_POINTER SET current_release_id='candidate'"
    )
    assert ids() == ([], [])
    connection.execute(
        "UPDATE PRESENTATION.SEMANTIC_RELEASES SET status=? WHERE release_id=?",
        ("RETIRED", "current"),
    )
    connection.execute(
        "UPDATE PRESENTATION.SEMANTIC_RELEASES SET status=? WHERE release_id=?",
        ("PUBLISHED", "old"),
    )
    connection.execute("UPDATE PRESENTATION.SEMANTIC_RELEASE_POINTER SET current_release_id='old'")
    assert ids() == (["old-id"], ["old-measure"])
