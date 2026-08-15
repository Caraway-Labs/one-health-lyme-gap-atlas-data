"""Idempotent Snowflake operations."""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect
from snowflake.connector import SnowflakeConnection

from . import RELEASE_ID
from .bundle import EXPECTED_SHA256, load_bundle

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def _execute_statements(connection: SnowflakeConnection, sql: str) -> None:
    with connection.cursor() as cursor:
        for statement in (part.strip() for part in sql.split(";")):
            if statement:
                cursor.execute(statement)


def provision(settings: SnowflakeSettings, dry_run: bool = False) -> None:
    sql = (SQL_DIR / "001_atlas.sql").read_text(encoding="utf-8")
    if dry_run:
        print(sql)
        return
    with connect(settings, include_database=False) as connection:
        _execute_statements(connection, sql)


def _county_rows(bundle: dict[str, Any]) -> Iterable[tuple[Any, ...]]:
    for feature in bundle["feature_collection"]["features"]:
        p = feature["properties"]
        geometry = json.dumps(feature["geometry"], separators=(",", ":"))
        yield (
            RELEASE_ID,
            p["fips"],
            p["county"],
            p["state"],
            p["state_name"],
            p["population"],
            p["in_contiguous_tick_scope"],
            p["human_status"],
            p["case_count_floor_2023"],
            p["incidence_floor_2023"],
            p["state_unallocated_records_2023"],
            p["tick_status"],
            p["scapularis_status"],
            p["pacificus_status"],
            p["burgdorferi_status"],
            p["svi_percentile"],
            p["uninsured_percentile"],
            p["uninsured_percent"],
            p["rucc_2023"],
            p["evidence_completeness"],
            json.dumps(p["default"], separators=(",", ":")),
            geometry,
            geometry,
        )


def load(settings: SnowflakeSettings, release: str, dry_run: bool = False) -> None:
    if release != RELEASE_ID:
        raise ValueError(f"Only {RELEASE_ID} is packaged")
    bundle = load_bundle()
    if dry_run:
        print(f"Would load {len(bundle['feature_collection']['features'])} counties for {release}")
        return
    with connect(settings) as connection:
        connection.autocommit(False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM LANDING.SOURCE_METADATA WHERE RELEASE_ID = %s", (release,)
                )
                cursor.execute("DELETE FROM LANDING.COUNTY_ATLAS WHERE RELEASE_ID = %s", (release,))
                cursor.execute(
                    "DELETE FROM LANDING.DATASET_RELEASE WHERE RELEASE_ID = %s", (release,)
                )
                cursor.execute(
                    """INSERT INTO LANDING.DATASET_RELEASE
                    (RELEASE_ID, SCHEMA_VERSION, GENERATED_AT, SCOPE, BUNDLE_SHA256,
                     SCORE_DEFAULTS, METHODOLOGY_VERSION, LIMITATIONS, IS_CURRENT)
                    SELECT %s, %s, TO_TIMESTAMP_TZ(%s), %s, %s, PARSE_JSON(%s), %s, %s, FALSE""",
                    (
                        release,
                        bundle["schema_version"],
                        bundle["generated_at"],
                        bundle["scope"],
                        EXPECTED_SHA256,
                        json.dumps(bundle["score_defaults"], separators=(",", ":")),
                        "alpha-0.2.0",
                        "Population-level hypothesis generator; not diagnosis, exposure "
                        "location, true incidence, or individual risk.",
                    ),
                )
                source_rows = [
                    (
                        release,
                        source["key"],
                        source["label"],
                        source["vintage"],
                        source["url"],
                        source["note"],
                    )
                    for source in bundle["sources"]
                ]
                cursor.executemany(
                    "INSERT INTO LANDING.SOURCE_METADATA VALUES (%s,%s,%s,%s,%s,%s)", source_rows
                )
                cursor.executemany(
                    """INSERT INTO LANDING.COUNTY_ATLAS
                    (RELEASE_ID,FIPS,COUNTY,STATE,STATE_NAME,POPULATION,IN_CONTIGUOUS_TICK_SCOPE,
                     HUMAN_STATUS,CASE_COUNT_FLOOR_2023,INCIDENCE_FLOOR_2023,
                     STATE_UNALLOCATED_RECORDS_2023,TICK_STATUS,SCAPULARIS_STATUS,PACIFICUS_STATUS,
                     BURGDORFERI_STATUS,SVI_PERCENTILE,UNINSURED_PERCENTILE,UNINSURED_PERCENT,
                     RUCC_2023,EVIDENCE_COMPLETENESS,DEFAULT_SCORE,GEOMETRY_JSON,GEOGRAPHY)
                    SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                           PARSE_JSON(%s),PARSE_JSON(%s),TO_GEOGRAPHY(PARSE_JSON(%s))""",
                    list(_county_rows(bundle)),
                )
                cursor.execute("UPDATE LANDING.DATASET_RELEASE SET IS_CURRENT = FALSE")
                cursor.execute(
                    "UPDATE LANDING.DATASET_RELEASE SET IS_CURRENT = TRUE WHERE RELEASE_ID = %s",
                    (release,),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def validate_loaded(settings: SnowflakeSettings, release: str) -> dict[str, Any]:
    with connect(settings) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT COUNT(*), COUNT(DISTINCT FIPS),
                      COUNT_IF(LENGTH(FIPS) <> 5), COUNT_IF(GEOMETRY_JSON IS NULL)
               FROM LANDING.COUNTY_ATLAS WHERE RELEASE_ID = %s""",
            (release,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError("Snowflake validation returned no result")
        count, distinct_count, invalid_fips, missing_geometry = row
        result = {
            "release_id": release,
            "count": count,
            "distinct_fips": distinct_count,
            "invalid_fips": invalid_fips,
            "missing_geometry": missing_geometry,
        }
        if result != {
            "release_id": release,
            "count": 3_144,
            "distinct_fips": 3_144,
            "invalid_fips": 0,
            "missing_geometry": 0,
        }:
            raise ValueError(f"Snowflake validation failed: {result}")
        return result


def status(settings: SnowflakeSettings) -> list[dict[str, Any]]:
    with connect(settings) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT RELEASE_ID, SCHEMA_VERSION, GENERATED_AT, LOADED_AT, IS_CURRENT "
            "FROM LANDING.DATASET_RELEASE ORDER BY LOADED_AT DESC"
        )
        columns = [item[0].lower() for item in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
