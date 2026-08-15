from snowflake.connector.cursor import SnowflakeCursor

from lyme_gap_atlas_data.database import COUNTY_FINALIZE_SQL, COUNTY_STAGE_INSERT_SQL


def test_county_insert_supports_connector_multirow_rewrite() -> None:
    """Keep bulk loading on the connector's supported INSERT ... VALUES path."""
    assert SnowflakeCursor.INSERT_SQL_VALUES_RE.match(COUNTY_STAGE_INSERT_SQL)
    assert "PARSE_JSON" not in COUNTY_STAGE_INSERT_SQL
    assert "PARSE_JSON" in COUNTY_FINALIZE_SQL
    assert "TO_GEOGRAPHY(PARSE_JSON(GEOMETRY_JSON_TEXT), TRUE)" in COUNTY_FINALIZE_SQL
