"""Synthetic prerequisites only, installed exclusively through fixed fixture SQL routing."""

import json
from pathlib import Path

from run_release_integrity_fixture import BUNDLE, FROZEN, MARKER, OLD, OLD_BUNDLE, SOURCES


def seed_prerequisites(fixture, connection):
    def q(label, sql, params=()):
        return fixture.query(connection, label, sql, params)

    q("seed_receipt_schema", "CREATE TABLE GOVERNANCE.SEED_RECEIPT(marker VARCHAR)")
    q(
        "seed_releases",
        "CREATE TABLE PRESENTATION.SEMANTIC_RELEASES "
        "(release_id VARCHAR,bundle_sha256 VARCHAR,status VARCHAR,source_manifest VARIANT)",
    )
    q(
        "seed_pointer",
        "CREATE TABLE PRESENTATION.SEMANTIC_RELEASE_POINTER "
        "(pointer_key VARCHAR,current_release_id VARCHAR)",
    )
    q(
        "seed_counties",
        (
            "CREATE TABLE PRESENTATION.SEMANTIC_COUNTY_ATLAS (release_id VARCH"
            "AR,fips VARCHAR,state VARCHAR,population NUMBER,human_status VARC"
            "HAR,case_count_floor_2023 NUMBER,tick_status VARCHAR,scapularis_s"
            "tatus VARCHAR,pacificus_status VARCHAR,burgdorferi_status VARCHAR"
            ",svi_percentile FLOAT,rucc_2023 NUMBER)"
        ),
    )
    q(
        "seed_sources",
        (
            "CREATE TABLE PRESENTATION.SEMANTIC_DATA_SOURCES (release_id VARCH"
            "AR,source_key VARCHAR,resource_key VARCHAR,source_id VARCHAR,data"
            "set_id VARCHAR,source_version_id VARCHAR,ingestion_run_id VARCHAR"
            ",artifact_id VARCHAR,vintage VARCHAR,note VARCHAR,source_url VARC"
            "HAR,label VARCHAR)"
        ),
    )
    q(
        "seed_observations",
        (
            "CREATE TABLE PRESENTATION.SEMANTIC_OBSERVATIONS (release_id VARCH"
            "AR,fips VARCHAR,measure_id VARCHAR,temporal_window VARCHAR,source"
            "_key VARCHAR,source_version_id VARCHAR,ingestion_run_id VARCHAR,a"
            "rtifact_id VARCHAR,source_record_id VARCHAR,source_row_hash VARCH"
            "AR)"
        ),
    )
    manifest = {
        "sources": [
            {
                "source_key": source,
                "artifact_sha256": "a" * 64,
                "definition_version": 1,
                "field_map": {"fips": ["fips"]},
            }
            for source in SOURCES
        ]
    }
    for release, bundle in (
        (OLD, OLD_BUNDLE),
        (FROZEN, BUNDLE),
        ("synthetic-ri706-target", "a" * 64),
    ):
        q(
            "seed_release",
            "INSERT INTO PRESENTATION.SEMANTIC_RELEASES SELECT %s,%s,'PUBLISHED',PARSE_JSON(%s)",
            (release, bundle, json.dumps(manifest)),
        )
        for source in SOURCES:
            q(
                "seed_source",
                "INSERT INTO PRESENTATION.SEMANTIC_DATA_SOURCES SELECT "
                "%s,%s,%s,%s,%s,%s,%s,%s,'synthetic','SYNTHETIC_TEST_NOT_APPROVAL',"
                "'https://example.invalid/ri706','synthetic'",
                (release, source, source, source, source, source, source, source),
            )
    canonical = (
        (Path(__file__).parents[1] / "src/lyme_gap_atlas_data/data/canonical-county-fips-2022.txt")
        .read_text()
        .split()
    )
    q("seed_fips", "CREATE TABLE GOVERNANCE.CANONICAL_FIPS(fips VARCHAR)")
    for start in range(0, len(canonical), 200):
        chunk = canonical[start : start + 200]
        q(
            "seed_canonical_chunk",
            "INSERT INTO GOVERNANCE.CANONICAL_FIPS VALUES " + ",".join(["(%s)"] * len(chunk)),
            tuple(chunk),
        )
    q(
        "seed_county_rows",
        "INSERT INTO PRESENTATION.SEMANTIC_COUNTY_ATLAS "
        "SELECT r.release_id,c.fips,SUBSTR(c.fips,1,2),1,'Unknown',0,'Unknown','Unknown',"
        "'Unknown','Unknown',0.5,1 FROM PRESENTATION.SEMANTIC_RELEASES r "
        "CROSS JOIN GOVERNANCE.CANONICAL_FIPS c",
    )
    q(
        "seed_observation_rows",
        "INSERT INTO PRESENTATION.SEMANTIC_OBSERVATIONS "
        "SELECT c.release_id,c.fips,'synthetic','2023',s.source_key,s.source_version_id,"
        "s.ingestion_run_id,s.artifact_id,c.fips,SHA2(c.fips||s.source_key,256) "
        "FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS c JOIN PRESENTATION.SEMANTIC_DATA_SOURCES s "
        "ON s.release_id=c.release_id",
    )
    q(
        "seed_current",
        "INSERT INTO PRESENTATION.SEMANTIC_RELEASE_POINTER VALUES ('ATLAS',%s)",
        (FROZEN,),
    )
    q(
        "seed_release_view",
        "CREATE VIEW PRESENTATION.CURRENT_RELEASE_V AS SELECT r.* FROM "
        "PRESENTATION.SEMANTIC_RELEASES r JOIN PRESENTATION.SEMANTIC_RELEASE_POINTER p "
        "ON r.release_id=p.current_release_id WHERE p.pointer_key='ATLAS'",
    )
    q(
        "seed_county_view",
        (
            "CREATE VIEW PRESENTATION.CURRENT_COUNTY_ATLAS_V AS SELECT c.* FRO"
            "M PRESENTATION.SEMANTIC_COUNTY_ATLAS c JOIN PRESENTATION.CURRENT_"
            "RELEASE_V r ON r.release_id=c.release_id"
        ),
    )
    q(
        "seed_tier1",
        (
            "CREATE VIEW PRESENTATION.CURRENT_TIER1_COUNTY_REVIEW_V AS SELECT "
            "c.fips AS county_fips,c.release_id,r.bundle_sha256,'tier1-review-"
            "priority-5536b5caad95cf47' AS prediction_batch_version,'tier1-sta"
            "tistical-reference-v1' AS model_version,'MEDIUM' AS priority_tier"
            " FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS c JOIN PRESENTATION.SEMA"
            "NTIC_RELEASES r ON r.release_id=c.release_id WHERE c.release_id='"
        )
        + OLD
        + "'",
    )
    q("seed_complete", "INSERT INTO GOVERNANCE.SEED_RECEIPT VALUES (%s)", (MARKER,))
    connection.commit()
