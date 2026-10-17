"""Execute migration admission SQL on synthetic rows; not Snowflake runtime proof."""

import json
import re
import sqlite3
from pathlib import Path

import pytest
import sqlglot

ROOT = Path(__file__).parents[1]
SOURCE = (ROOT / "migrations/V155__county_context_consumer_observations.sql").read_text()
QUERY = SOURCE.split("WITH context AS (\n", 1)[1].split("\n), existing AS (", 1)[0]
RELEASE = "governed-2026-10-15-january-climate-prod"
BUNDLE = "53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d"
PACKET = json.loads(
    (
        ROOT / "docs/contracts/semantic-domain/data-199-200-metadata-reviewed-2026-10-04.json"
    ).read_text()
)


@pytest.fixture
def database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("ATTACH DATABASE ':memory:' AS PRESENTATION")
    db.create_function("TO_VARIANT", 1, lambda value: value)
    db.create_function("PARSE_JSON", 1, lambda value: value)
    db.create_function("IS_NULL_VALUE", 1, lambda value: value is None)
    db.create_function("REGEXP_LIKE", 2, lambda value, pattern: bool(re.fullmatch(pattern, value)))
    db.create_function(
        "TYPEOF", 1, lambda v: {int: "INTEGER", float: "DOUBLE"}.get(type(v), "OTHER")
    )
    db.create_function("IF", 3, lambda condition, yes, no: yes if condition else no)
    tables = {
        "SEMANTIC_RELEASE_POINTER": "pointer_key,current_release_id",
        "SEMANTIC_RELEASES": (
            "release_id,status,bundle_sha256,schema_version,methodology_version,limitations"
        ),
        "SEMANTIC_COUNTY_ATLAS": "release_id,fips",
        "SEMANTIC_DATA_SOURCES": (
            "release_id,source_key,source_id,dataset_id,"
            "resource_key,source_version_id,ingestion_run_id,artifact_id,label,"
            "vintage,source_url"
        ),
        "SEMANTIC_OBSERVATIONS": (
            "release_id,observation_id,measure_id,fips,"
            "source_key,source_version_id,ingestion_run_id,artifact_id,"
            "temporal_window,transformation_version,geography_semantics,"
            "quality_state,value,value_state,retrieved_at,limitations,"
            "source_record_id,source_row_hash"
        ),
    }
    for table, columns in tables.items():
        db.execute(f"CREATE TABLE PRESENTATION.{table} ({columns})")
    db.execute("INSERT INTO PRESENTATION.SEMANTIC_RELEASE_POINTER VALUES ('ATLAS',?)", (RELEASE,))
    db.execute(
        (
            "INSERT INTO PRESENTATION.SEMANTIC_RELEASES VALUES (?, 'PUBLISHED', ?, "
            "'2.0.0', 'semantic-2.0.0', 'release limits')"
        ),
        (RELEASE, BUNDLE),
    )
    db.execute("INSERT INTO PRESENTATION.SEMANTIC_COUNTY_ATLAS VALUES (?, '01001')", (RELEASE,))
    expression = sqlglot.parse_one(QUERY, read="snowflake")
    sources = next(cte for cte in expression.ctes if cte.alias == "sources")
    for row in sources.find(sqlglot.exp.Values).expressions:
        values = [item.this for item in row.expressions]
        db.execute(
            "INSERT INTO PRESENTATION.SEMANTIC_DATA_SOURCES VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (RELEASE, *values[:7], "publisher", values[7], "https://publisher.example"),
        )
    for metadata in PACKET:
        measure = metadata["measure"]["measure_id"]
        source = db.execute(
            "SELECT * FROM PRESENTATION.SEMANTIC_DATA_SOURCES WHERE source_version_id=?",
            (metadata["provenance"]["source_version_id"]["value"],),
        ).fetchone()
        db.execute(
            (
                "INSERT INTO PRESENTATION.SEMANTIC_OBSERVATIONS VALUES (?,?,?,?,?,?,?,"
                "?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                RELEASE,
                measure + ":01001",
                measure,
                "01001",
                source["source_key"],
                source["source_version_id"],
                source["ingestion_run_id"],
                source["artifact_id"],
                source["vintage"],
                "semantic_county_assembly_v1"
                if measure == "rucc_2023"
                else "svi_numeric_projection_v2",
                "COUNTY_FIPS_5",
                "PASSED",
                2 if measure == "rucc_2023" else 100 if measure == "population_2022" else 0.5,
                "OBSERVED",
                "2026-09-17",
                "observation limits",
                "private-record",
                "a" * 64,
            ),
        )
    yield db
    db.close()


def read(db):
    return [
        dict(row)
        for row in db.execute(sqlglot.transpile(QUERY, read="snowflake", write="sqlite")[0])
    ]


def test_reviewed_metadata_temporal_semantics_and_closed_projection(database):
    rows = {row["measure_id"]: row for row in read(database)}
    assert len(rows) == 5
    for metadata in PACKET:
        row = rows[metadata["measure"]["measure_id"]]
        assert row["metadata_revision_id"] == metadata["revision_id"]
        assert row["semantic_version"] == metadata["measure"]["semantic_version"]
        assert row["unit"] == metadata["unit"]
        assert row["denominator"] == metadata["denominator"]
        assert json.loads(row["context_limitations"]) == metadata["limitations"]
        assert row["county_fips"] == "01001" and row["release_version"] == RELEASE
        assert row["source_published_at"] is None
        assert (
            not {
                "source_version_id",
                "ingestion_run_id",
                "artifact_id",
                "source_row_hash",
                "source_record_id",
            }
            & row.keys()
        )
    rucc = rows["rucc_2023"]
    assert rucc["period_start"] is None and rucc["period_end"] is None
    assert rucc["temporal_grain"] == "VINTAGE_YEAR" and rucc["vintage_year"] == 2023
    for name, row in rows.items():
        if name != "rucc_2023":
            assert (row["period_start"], row["period_end"], row["temporal_grain"]) == (
                "2018-01-01",
                "2022-12-31",
                "PERIOD",
            )


@pytest.mark.parametrize("code", range(1, 10))
def test_all_rucc_labels_match_frozen_data_codebook(database, code):
    database.execute(
        "UPDATE PRESENTATION.SEMANTIC_OBSERVATIONS SET value=? WHERE measure_id='rucc_2023'",
        (code,),
    )
    row = next(row for row in read(database) if row["measure_id"] == "rucc_2023")
    contract = (ROOT / "docs/contracts/semantic-domain/story-200-rucc-context-v1.md").read_text()
    assert f"| {code} | {row['category_label']} |" in contract
    assert row["value"] == code


@pytest.mark.parametrize("measure", [m["measure"]["measure_id"] for m in PACKET])
@pytest.mark.parametrize(
    "value,state,accepted",
    [
        (0, "ZERO", True),
        (None, "MISSING", True),
        (None, "UNAVAILABLE", False),
        (0, "OBSERVED", False),
        (-999, "OBSERVED", False),
        (None, "OBSERVED", False),
        (1.5, "OBSERVED", True),
        ("1", "OBSERVED", False),
    ],
)
def test_numeric_domains_and_states_are_not_coerced(database, measure, value, state, accepted):
    database.execute(
        "UPDATE PRESENTATION.SEMANTIC_OBSERVATIONS SET value=?,value_state=? WHERE measure_id=?",
        (value, state, measure),
    )
    if measure == "rucc_2023":
        accepted = False
    if value == 1.5 and measure != "uninsured_percent_2022":
        accepted = False
    rows = [row for row in read(database) if row["measure_id"] == measure]
    assert bool(rows) == accepted
    if rows:
        assert rows[0]["value"] == value and rows[0]["value_state"] == state


@pytest.mark.parametrize(
    "column,value",
    [
        ("fips", "1001"),
        ("source_key", "other"),
        ("source_version_id", "other"),
        ("ingestion_run_id", "other"),
        ("artifact_id", "other"),
        ("temporal_window", "2021"),
        ("quality_state", "FAILED"),
        ("transformation_version", "other"),
        ("source_record_id", ""),
        ("source_row_hash", "bad"),
    ],
)
def test_unadmitted_provenance_is_unavailable(database, column, value):
    database.execute(f"UPDATE PRESENTATION.SEMANTIC_OBSERVATIONS SET {column}=?", (value,))
    assert read(database) == []


@pytest.mark.parametrize("column,value", [("status", "STAGED"), ("bundle_sha256", "different")])
def test_release_fail_closed(database, column, value):
    database.execute(f"UPDATE PRESENTATION.SEMANTIC_RELEASES SET {column}=?", (value,))
    assert read(database) == []


def test_duplicate_observations_do_not_become_published(database):
    database.execute(
        "INSERT INTO PRESENTATION.SEMANTIC_OBSERVATIONS SELECT * FROM "
        "PRESENTATION.SEMANTIC_OBSERVATIONS"
    )
    assert read(database) == []


def test_existing_human_and_nlcd_admission_is_unchanged():
    old = (ROOT / "migrations/V138__bounded_nlcd_consumer_observations.sql").read_text()
    original = old.split("COPY GRANTS AS\n", 1)[1].strip().rstrip(";")
    preserved = SOURCE.split("), existing AS (\n", 1)[1].split("\n)\nSELECT existing.*", 1)[0]
    assert preserved == original
    assert "CURRENT_CLIMATE" not in SOURCE
    assert "GRANT SELECT ON TABLE" not in SOURCE
