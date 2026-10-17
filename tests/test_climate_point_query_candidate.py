"""Offline SQL equivalence only; no Snowflake optimizer/performance assertion."""

import json
import re
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
BASE = (ROOT / "migrations/V152__prod_january_climate_consumer_views.sql").read_text()
CANDIDATE = (ROOT / "sql/january_climate_point_query_candidate.sql").read_text()
MEMBERSHIP = (ROOT / "sql/january_climate_membership_probe_candidate.sql").read_text()
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


def test_membership_candidate_preserves_entire_scientific_projection() -> None:
    end = BASE.index("\nCREATE OR REPLACE VIEW PRESENTATION.CURRENT_CLIMATE_MEASURE_METADATA_V")
    assert (
        MEMBERSHIP[MEMBERSHIP.index("\nSELECT release_id,") :].strip()
        == BASE[BASE.index("\nSELECT release_id,") : end].strip()
    )
    assert "c.extension:capture_ids) member" not in MEMBERSHIP
    assert "ARRAY_CONTAINS(TO_VARIANT(v.capture_record_id), c.extension:capture_ids)" in MEMBERSHIP
    assert "CREATE " not in MEMBERSHIP and "GRANT " not in MEMBERSHIP


@pytest.mark.parametrize("sql", [CANDIDATE, MEMBERSHIP], ids=["projection", "membership"])
@pytest.mark.parametrize("supported", [True, False])
@pytest.mark.parametrize("published", [True, False])
@pytest.mark.parametrize("measure", ["PRCP", "TMIN", "TMAX", "TAVG", "OTHER"])
def test_executable_join_and_measure_equivalence(
    sql: str, supported: bool, published: bool, measure: str
) -> None:
    query = sql[sql.index("WITH current_climate") : sql.index("\nSELECT release_id,")]
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
    query = query.replace("TO_VARIANT(v.capture_record_id)", "v.capture_record_id")
    query += """ SELECT json_extract(metadata, '$.measure.measure_id'),
        'nclimgrid_' || LOWER(json_extract(record, '$.measure')) || '_county_day',
        record FROM records"""
    extension = {
        "contract_version": "atlas-january-climate-release-extension-v2" if supported else "other",
        "capture_ids": [
            "accepted",
            "wrong-run",
            "wrong-artifact",
            "wrong-hash",
            "wrong-resource",
            "wrong-version",
        ],
        "ingestion_run_id": "run",
        "sources": {"noaa": {"artifact_id": "artifact", "sha256": "sha"}},
        "metadata": [
            {"measure": {"measure_id": f"nclimgrid_{m}_county_day"}}
            for m in ("prcp", "tmin", "tmax", "tavg")
        ],
    }
    with sqlite3.connect(":memory:") as db:
        # SQLite executes the relational guards, not Snowflake's optimizer or
        # VARIANT engine. Accepted manifests require unique string capture IDs.
        db.create_function(
            "ARRAY_CONTAINS",
            2,
            lambda value, array: value in json.loads(array) if array is not None else None,
        )
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
            ("wrong-resource", "run", "artifact", "sha"),
            ("wrong-version", "run", "artifact", "sha"),
        ):
            db.execute(
                "INSERT INTO GOVERNED_SOURCE_RECORD_REVISIONS VALUES (?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    run,
                    "other" if identifier == "wrong-resource" else "noaa_nclimgrid_daily_202501",
                    1 if identifier == "wrong-version" else 2,
                    artifact,
                    sha,
                    json.dumps(
                        {"record": {"measure": measure, "value": 0, "coverage_status": "COMPLETE"}}
                    ),
                    "retrieved",
                ),
            )
        rows = db.execute(query).fetchall()
        assert len(rows) == (1 if published and supported and measure != "OTHER" else 0)
        assert all(old == proposed for old, proposed, _ in rows)


def test_retained_profile_complete_graph_and_observed_costs() -> None:
    profile = json.loads(
        (ROOT / "tests/fixtures/climate/prod_point_query_profile.json").read_text()
    )
    assert profile["query_id"] == "01c7c3ed-030c-3e2e-0064-2d0701278042"
    operators = {row["operator_id"]: row for row in profile["operators"]}
    assert set(operators) == set(range(22))
    assert all(row["step_id"] == 1 for row in operators.values())
    assert all(parent in operators for row in operators.values() for parent in row["parents"])
    assert operators[6]["parents"] == [5, 18]  # one shared release CTE, not two scans
    assert operators[15]["statistics"] == {"input_rows": 1, "output_rows": 389856}
    assert operators[14]["statistics"] == {"input_rows": 389856, "output_rows": 389856}
    assert operators[13]["statistics"] == {"input_rows": 389857, "output_rows": 1}
    assert operators[21]["statistics"]["pruning"] == {
        "partitions_scanned": 29,
        "partitions_total": 29,
    }
    assert operators[21]["statistics"]["output_rows"] == 1
    condition = operators[19]["attributes"]["filter_condition"]
    assert all(term in condition for term in ("48277", "2025-01-17", "nclimgrid_prcp_county_day"))
    assert operators[17]["statistics"]["spilling"]["bytes_spilled_local_storage"] == 23601152
    # Preserve the discrepancy with aggregate history; do not silently reconcile
    # scan-level bytes to the distinct 141499392 history metric.
    assert (
        sum(row["statistics"].get("io", {}).get("bytes_scanned", 0) for row in operators.values())
        == 30435376
    )


@pytest.mark.parametrize("point", [False, True])
def test_v154_multirow_record_metadata_and_retrieval_parity(point):
    """Execute both relational branches; final Snowflake projection is byte-identical.

    SQLite does not establish Snowflake numeric/VARIANT runtime acceptance.
    Compare complete projection inputs, preserving nulls, zero and negatives.
    """

    def relational(sql):
        query = sql[sql.index("WITH current_climate") : sql.index("\nSELECT release_id,")]
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
        query = query.replace("TO_VARIANT(v.capture_record_id)", "v.capture_record_id")
        query += " SELECT release_id,record,metadata,retrieved_at FROM records"
        if point:
            query += (
                " WHERE json_extract(record, '$.county_fips')='48277'"
                " AND json_extract(record, '$.measure')='PRCP'"
            )
        return query

    records = []
    for county in ("48277", "02013"):
        for measure, value, unit in (
            ("PRCP", 0, "mm"),
            ("TMIN", -1.992, "degrees C"),
            ("TMAX", 16.299, "degrees C"),
            ("TAVG", 7.153, "degrees C"),
        ):
            for coverage in ("COMPLETE", "PARTIAL", "OUT_OF_SOURCE_COVERAGE"):
                records.append(
                    {
                        "county_fips": county,
                        "measure": measure,
                        "value": value if coverage == "COMPLETE" else None,
                        "coverage_status": coverage,
                        "unit": unit,
                        "observation_date": "2025-01-17",
                        "source_time_present": coverage != "OUT_OF_SOURCE_COVERAGE",
                        "expected_area_m2": 123.45,
                        "intersected_area_m2": 120,
                        "source_supported_area_m2": 119,
                        "valid_area_m2": None,
                        "source_coverage_fraction": 0.99,
                        "valid_fraction_of_supported_area": None,
                        "transformation_version": "native",
                        "weight_version": "weight",
                        "geometry_version": "TIGER2025",
                        "upstream_date_modified": None,
                    }
                )
    metadata = [
        {
            "measure": {"measure_id": f"nclimgrid_{m}_county_day", "semantic_version": "2.0.0"},
            "revision_id": m,
            "limitations": ["not midnight"],
            "provenance": {"publisher": {"value": "NOAA"}},
        }
        for m in ("prcp", "tmin", "tmax", "tavg")
    ]
    ids = [f"{i:064x}" for i in range(len(records))]
    ext = {
        "contract_version": "atlas-january-climate-release-extension-v2",
        "capture_ids": ids,
        "metadata": metadata,
        "ingestion_run_id": "run",
        "sources": {"noaa": {"artifact_id": "artifact", "sha256": "sha"}},
    }
    with sqlite3.connect(":memory:") as db:
        db.create_function("ARRAY_CONTAINS", 2, lambda value, array: value in json.loads(array))
        db.execute("CREATE TABLE SEMANTIC_RELEASE_POINTER(pointer_key,current_release_id)")
        db.execute("INSERT INTO SEMANTIC_RELEASE_POINTER VALUES ('ATLAS','release')")
        db.execute("CREATE TABLE SEMANTIC_RELEASES(release_id,status,source_manifest)")
        db.execute(
            "INSERT INTO SEMANTIC_RELEASES VALUES ('release','PUBLISHED',?)",
            (json.dumps({"climate_extension": ext}),),
        )
        db.execute(
            "CREATE TABLE GOVERNED_SOURCE_RECORD_REVISIONS("
            "capture_record_id,ingestion_run_id,resource_key,source_definition_version,"
            "artifact_id,artifact_sha256,payload,retrieved_at)"
        )
        for i, record in enumerate(records):
            db.execute(
                "INSERT INTO GOVERNED_SOURCE_RECORD_REVISIONS "
                "VALUES (?,'run','noaa_nclimgrid_daily_202501',2,'artifact','sha',?,'retrieved')",
                (ids[i], json.dumps({"record": record})),
            )
        # Exact copied record and lineage but excluded from frozen membership.
        db.execute(
            "INSERT INTO GOVERNED_SOURCE_RECORD_REVISIONS "
            "VALUES (?,'run','noaa_nclimgrid_daily_202501',2,'artifact','sha',?,'retrieved')",
            ("f" * 64, json.dumps({"record": records[0]})),
        )
        baseline = sorted(db.execute(relational(BASE)).fetchall())
        proposed = sorted(db.execute(relational(MEMBERSHIP)).fetchall())
        assert baseline == proposed
        assert len(proposed) == (3 if point else 24)


def test_v154_is_exact_b_with_copy_grants_and_prod_only():
    from lyme_gap_atlas_data import migrations

    migration = next(m for m in migrations.load_migrations() if m.version == "V154")
    assert "V154" in migrations.PROD_ONLY_MIGRATION_VERSIONS
    assert (
        migration.source[migration.source.index("WITH current_climate") :]
        == MEMBERSHIP[MEMBERSHIP.index("WITH current_climate") :]
    )
    assert migration.source.count("CREATE OR REPLACE VIEW") == 1
    assert "COPY GRANTS AS" in migration.source
    assert not any(
        token in migration.source for token in ("GRANT ", "INSERT ", "DELETE ", "UPDATE ", "DROP ")
    )
