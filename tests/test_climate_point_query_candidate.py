"""Offline SQL equivalence only; no Snowflake optimizer/performance assertion."""

import json
import re
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
BASE = (ROOT / "migrations/V152__prod_january_climate_consumer_views.sql").read_text()
CANDIDATE = (ROOT / "sql/january_climate_point_query_candidate.sql").read_text()
OLD_MEASURE = "metadata:measure:measure_id::VARCHAR AS measure_id"
NEW_MEASURE = "'nclimgrid_' || LOWER(record:measure::VARCHAR) || '_county_day' AS measure_id"


def test_only_measure_projection_changes_no_membership_or_scientific_rewrite() -> None:
    baseline = BASE[
        BASE.index("WITH current_climate") : BASE.index(
            "\nCREATE OR REPLACE VIEW PRESENTATION.CURRENT_CLIMATE_MEASURE_METADATA_V"
        )
    ].strip()
    candidate = CANDIDATE[CANDIDATE.index("WITH current_climate") :].strip()
    assert candidate.replace(NEW_MEASURE, OLD_MEASURE, 1) == baseline
    assert "CREATE " not in CANDIDATE and "GRANT " not in CANDIDATE
    assert "ARRAY_CONTAINS" not in CANDIDATE


@pytest.mark.parametrize("published", [True, False])
@pytest.mark.parametrize("measure", ["PRCP", "TMIN", "TMAX", "TAVG", "OTHER"])
def test_executable_join_and_measure_equivalence(published: bool, measure: str) -> None:
    query = CANDIDATE[
        CANDIDATE.index("WITH current_climate") : CANDIDATE.index("\nSELECT release_id,")
    ]
    query = re.sub(
        r"LATERAL FLATTEN\(INPUT => c.extension:(capture_ids|metadata)\)",
        r"json_each(c.extension, '$.\1')",
        query,
    )
    query = (
        re.sub(
            r"(\w+\.\w+)((?::\w+)+)",
            lambda m: f"json_extract({m[1]}, '$.{m[2][1:].replace(':', '.')}')",
            query.replace("::VARCHAR", ""),
        )
        .replace("PRESENTATION.", "")
        .replace("GOVERNANCE.", "")
    )
    query += """ SELECT json_extract(metadata, '$.measure.measure_id'),
        'nclimgrid_' || LOWER(json_extract(record, '$.measure')) || '_county_day',
        record FROM records"""
    extension = {
        "contract_version": "atlas-january-climate-release-extension-v2",
        "capture_ids": ["accepted", "wrong-run", "wrong-artifact", "wrong-hash"],
        "ingestion_run_id": "run",
        "sources": {"noaa": {"artifact_id": "artifact", "sha256": "sha"}},
        "metadata": [
            {"measure": {"measure_id": f"nclimgrid_{m}_county_day"}}
            for m in ("prcp", "tmin", "tmax", "tavg")
        ],
    }
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE SEMANTIC_RELEASE_POINTER(pointer_key, current_release_id)")
        db.execute("CREATE TABLE SEMANTIC_RELEASES(release_id, status, source_manifest)")
        db.execute("INSERT INTO SEMANTIC_RELEASE_POINTER VALUES ('ATLAS','release')")
        db.execute(
            "INSERT INTO SEMANTIC_RELEASES VALUES (?,?,?)",
            (
                "release",
                "PUBLISHED" if published else "CANDIDATE",
                json.dumps({"climate_extension": extension}),
            ),
        )
        db.execute("""CREATE TABLE GOVERNED_SOURCE_RECORD_REVISIONS(
            capture_record_id, ingestion_run_id, resource_key, source_definition_version,
            artifact_id, artifact_sha256, payload, retrieved_at)""")
        for identifier, run, artifact, sha in (
            ("accepted", "run", "artifact", "sha"),
            ("not-member", "run", "artifact", "sha"),
            ("wrong-run", "different", "artifact", "sha"),
            ("wrong-artifact", "run", "different", "sha"),
            ("wrong-hash", "run", "artifact", "different"),
        ):
            db.execute(
                "INSERT INTO GOVERNED_SOURCE_RECORD_REVISIONS VALUES (?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    run,
                    "noaa_nclimgrid_daily_202501",
                    2,
                    artifact,
                    sha,
                    json.dumps(
                        {"record": {"measure": measure, "value": 0, "coverage_status": "COMPLETE"}}
                    ),
                    "retrieved",
                ),
            )
        rows = db.execute(query).fetchall()
        assert len(rows) == (1 if published and measure != "OTHER" else 0)
        assert all(old == proposed for old, proposed, _ in rows)
