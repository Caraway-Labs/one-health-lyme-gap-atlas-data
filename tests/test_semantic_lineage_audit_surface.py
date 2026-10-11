"""DATA #604: the audit migration must preserve the role boundary."""

import sqlite3
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[1] / "migrations" / "V137__semantic_lineage_audit_view.sql"
).read_text(encoding="utf-8")
SQL = SOURCE.upper()


def test_only_bounded_secure_view_is_granted_to_read() -> None:
    assert "CREATE SECURE VIEW IF NOT EXISTS LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V" in SQL
    assert (
        "GRANT SELECT ON VIEW LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V\n"
        "  TO ROLE OH_LYME_{{ ENV }}_READ"
    ) in SQL
    assert SQL.count("GRANT ") == 2
    assert "GRANT USAGE ON SCHEMA LINEAGE_AUDIT TO ROLE OH_LYME_{{ ENV }}_READ" in SQL
    for forbidden in (
        "GRANT INSERT",
        "GRANT UPDATE",
        "GRANT DELETE",
        "GRANT OWNERSHIP",
        "GRANT SELECT ON TABLE",
        "FUTURE TABLES",
    ):
        assert forbidden not in SQL


def test_projection_contains_both_authority_paths_without_payload() -> None:
    assert "GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS V" in SQL
    assert "CONFORMED.GOVERNED_SOURCE_RECORDS C" in SQL
    assert "V.CAPTURE_RECORD_ID IS NULL" in SQL
    assert "V.SOURCE_ROW_HASH = O.SOURCE_ROW_HASH" in SQL
    assert "C.SOURCE_ROW_HASH = O.SOURCE_ROW_HASH" in SQL
    assert "'UNMATCHED'" in SQL
    for forbidden in ("V.PAYLOAD", "C.PAYLOAD", "ARTIFACT_URI", "SOURCE_URL", "SIGNED_URL"):
        assert forbidden not in SQL


def test_revision_precedes_legacy_fallback_and_unmatched_stays_visible() -> None:
    select = SOURCE.split(" AS\nSELECT o.observation_id,", 1)[1].split(";\n\nGRANT", 1)[0]
    select = "SELECT o.observation_id," + select
    with sqlite3.connect(":memory:") as db:
        for schema in ("PRESENTATION", "GOVERNANCE", "CONFORMED"):
            db.execute(f"ATTACH DATABASE ':memory:' AS {schema}")
        db.executescript(
            """
            CREATE TABLE PRESENTATION.SEMANTIC_OBSERVATIONS
              (observation_id TEXT, release_id TEXT, measure_id TEXT, fips TEXT,
               temporal_window TEXT, source_key TEXT, source_version_id TEXT,
               ingestion_run_id TEXT, artifact_id TEXT, source_record_id TEXT,
               source_row_hash TEXT);
            CREATE TABLE PRESENTATION.SEMANTIC_RELEASES
              (release_id TEXT, bundle_sha256 TEXT);
            CREATE TABLE PRESENTATION.SEMANTIC_DATA_SOURCES
              (release_id TEXT, source_key TEXT, source_version_id TEXT,
               ingestion_run_id TEXT, artifact_id TEXT, source_id TEXT,
               dataset_id TEXT, resource_key TEXT);
            CREATE TABLE GOVERNANCE.DATA_SOURCE_VERSIONS
              (data_source_version_id TEXT, resource_key TEXT,
               ingestion_run_id TEXT, artifact_id TEXT);
            CREATE TABLE GOVERNANCE.INGESTION_RUNS
              (ingestion_run_id TEXT, resource_key TEXT);
            CREATE TABLE GOVERNANCE.RAW_ARTIFACTS
              (artifact_id TEXT, ingestion_run_id TEXT, sha256 TEXT);
            CREATE TABLE GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS
              (capture_record_id TEXT, record_revision TEXT, record_id TEXT,
               source_id TEXT, dataset_id TEXT, resource_key TEXT,
               ingestion_run_id TEXT, artifact_id TEXT, artifact_sha256 TEXT,
               source_record_id TEXT, source_row_hash TEXT);
            CREATE TABLE CONFORMED.GOVERNED_SOURCE_RECORDS
              (record_id TEXT, source_id TEXT, dataset_id TEXT,
               resource_key TEXT, ingestion_run_id TEXT,
               source_record_id TEXT, source_row_hash TEXT);
            INSERT INTO PRESENTATION.SEMANTIC_RELEASES VALUES ('release', 'bundle');
            INSERT INTO GOVERNANCE.DATA_SOURCE_VERSIONS VALUES ('version', 'resource', NULL, NULL);
            INSERT INTO GOVERNANCE.INGESTION_RUNS VALUES ('run', 'resource');
            INSERT INTO GOVERNANCE.RAW_ARTIFACTS VALUES ('artifact', 'run', 'artifact-hash');
            INSERT INTO PRESENTATION.SEMANTIC_DATA_SOURCES VALUES
              ('release', 'source', 'version', 'run', 'artifact',
               'publisher', 'dataset', 'resource');
            INSERT INTO PRESENTATION.SEMANTIC_OBSERVATIONS VALUES
              ('revision', 'release', 'measure', '01001', '2023', 'source', 'version',
               'run', 'artifact', 'native-1', 'hash-1'),
              ('legacy', 'release', 'measure', '01001', '2023', 'source', 'version',
               'run', 'artifact', 'native-2', 'hash-2'),
              ('unmatched', 'release', 'measure', '01001', '2023', 'source', 'version',
               'run', 'artifact', 'native-3', 'hash-3');
            INSERT INTO GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS VALUES
              ('capture-1', 'revision-1', 'record-1', 'publisher', 'dataset',
               'resource', 'run', 'artifact', 'artifact-hash', 'native-1', 'hash-1');
            INSERT INTO CONFORMED.GOVERNED_SOURCE_RECORDS VALUES
              ('record-1', 'publisher', 'dataset', 'resource', 'run', 'native-1', 'hash-1'),
              ('record-2', 'publisher', 'dataset', 'resource', 'run', 'native-2', 'hash-2');
            """
        )
        rows = db.execute(select).fetchall()
        columns = [column[0].lower() for column in db.execute(select).description]
    result = {
        dict(zip(columns, row, strict=True))["observation_id"]: dict(zip(columns, row, strict=True))
        for row in rows
    }
    assert result["revision"]["record_match_kind"] == "IMMUTABLE_REVISION"
    assert result["revision"]["conformed_record_id"] is None
    assert result["legacy"]["record_match_kind"] == "LEGACY_CONFORMED"
    assert result["unmatched"]["record_match_kind"] == "UNMATCHED"
    assert all(row["governed_source_version_id"] == "version" for row in result.values())
