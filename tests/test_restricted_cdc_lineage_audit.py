"""Synthetic relational regressions for the existing PROD audit surface."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    PROD_DATABASE,
    load_migrations,
    migration_plan,
    render_migration,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "migrations/V147__prod_restricted_cdc_lineage_audit.sql").read_text()
SELECT = SOURCE.split(" COPY GRANTS AS\n", 1)[1].rstrip().removesuffix(";")


@pytest.fixture
def db() -> Iterator[sqlite3.Connection]:
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        for schema in ("PRESENTATION", "GOVERNANCE", "CONFORMED"):
            connection.execute(f"ATTACH DATABASE ':memory:' AS {schema}")
        tables = {
            "PRESENTATION.SEMANTIC_OBSERVATIONS": "observation_id,release_id,measure_id,fips,"
            "temporal_window,source_key,source_version_id,ingestion_run_id,artifact_id,"
            "source_record_id,source_row_hash",
            "PRESENTATION.SEMANTIC_RELEASES": "release_id,bundle_sha256",
            "PRESENTATION.SEMANTIC_DATA_SOURCES": "release_id,source_key,source_version_id,"
            "ingestion_run_id,artifact_id,source_id,dataset_id,resource_key",
            "GOVERNANCE.DATA_SOURCE_VERSIONS": "data_source_version_id,resource_key,"
            "ingestion_run_id,artifact_id",
            "GOVERNANCE.INGESTION_RUNS": "ingestion_run_id,resource_key",
            "GOVERNANCE.RAW_ARTIFACTS": "artifact_id,ingestion_run_id,sha256",
            "GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS": "capture_record_id,record_revision,"
            "record_id,source_id,dataset_id,resource_key,ingestion_run_id,artifact_id,"
            "artifact_sha256,source_record_id,source_row_hash",
            "CONFORMED.GOVERNED_SOURCE_RECORDS": "record_id,source_id,dataset_id,resource_key,"
            "ingestion_run_id,source_record_id,source_row_hash",
        }
        restricted = "conformed_record_id,resource_key,ingestion_run_id,evidence_run_id,"
        restricted += "county_fips,source_record_id,source_row_hash,workbook_sha256"
        for family in ("TICK", "PATHOGEN"):
            tables[f"CONFORMED.RESTRICTED_CDC_{family}_COUNTY_STATUS"] = restricted
        for table, columns in tables.items():
            connection.execute(f"CREATE TABLE {table} ({columns})")
        yield connection


def seed(db: sqlite3.Connection, family: str) -> str:
    tick = family == "tick"
    resource = "cdc_tick_ixodes_county_status" if tick else "cdc_tick_ixodes_pathogen_status"
    dataset = "cdc-ixodes-county-status-2025" if tick else "cdc-ixodes-pathogen-status-2025"
    db.execute("INSERT INTO PRESENTATION.SEMANTIC_RELEASES VALUES (?,?)", ("fixture", "a" * 64))
    db.execute(
        "INSERT INTO PRESENTATION.SEMANTIC_OBSERVATIONS VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            "fixture-observation",
            "fixture",
            "fixture-measure",
            "01001",
            "fixture-period",
            family,
            "fixture-version",
            "fixture-derivation",
            "fixture-artifact",
            "fixture-native",
            "b" * 64,
        ),
    )
    db.execute(
        "INSERT INTO PRESENTATION.SEMANTIC_DATA_SOURCES VALUES (?,?,?,?,?,?,?,?)",
        (
            "fixture",
            family,
            "fixture-version",
            "fixture-derivation",
            "fixture-artifact",
            "cdc_arbonet_tick_module",
            dataset,
            resource,
        ),
    )
    db.execute(
        "INSERT INTO GOVERNANCE.DATA_SOURCE_VERSIONS VALUES (?,?,?,?)",
        ("fixture-version", resource, "fixture-derivation", "fixture-artifact"),
    )
    db.execute(
        "INSERT INTO GOVERNANCE.INGESTION_RUNS VALUES (?,?)", ("fixture-derivation", resource)
    )
    db.execute(
        "INSERT INTO GOVERNANCE.RAW_ARTIFACTS VALUES (?,?,?)",
        ("fixture-artifact", "fixture-evidence", "c" * 64),
    )
    table = f"CONFORMED.RESTRICTED_CDC_{family.upper()}_COUNTY_STATUS"
    db.execute(
        f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?)",
        (
            "fixture-conformed",
            resource,
            "fixture-derivation",
            "fixture-evidence",
            "01001",
            "fixture-native",
            "b" * 64,
            "c" * 64,
        ),
    )
    return table


def test_prod_only_migration_preserves_existing_permissions_and_fields() -> None:
    migrations = {item.version: item for item in load_migrations()}
    assert "V147" not in {row["version"] for row in migration_plan(DEV_DATABASE)}
    assert "V147" in {row["version"] for row in migration_plan(PROD_DATABASE)}
    rendered = render_migration(migrations["V147"], PROD_DATABASE).upper()
    rendered = "\n".join(line for line in rendered.splitlines() if not line.startswith("--"))
    assert "CREATE OR REPLACE SECURE VIEW" in rendered
    assert "COPY GRANTS AS" in rendered
    for forbidden in ("GRANT ", "REVOKE ", "INSERT ", "UPDATE ", "DELETE ", "PAYLOAD", "STATUS,"):
        assert forbidden not in rendered


@pytest.mark.parametrize("family", ["tick", "pathogen"])
def test_restricted_record_uses_earlier_evidence_run_without_inventing_revision(db, family) -> None:
    seed(db, family)
    rows = [dict(row) for row in db.execute(SELECT)]
    assert len(rows) == 1
    result = rows[0]
    assert result["record_match_kind"] == "RESTRICTED_CDC_CONFORMED"
    assert result["governed_source_row_hash"] == result["semantic_source_row_hash"] == "b" * 64
    assert result["conformed_record_id"] == "fixture-conformed"
    assert result["artifact_sha256"] == "c" * 64
    assert result["capture_record_id"] is None
    assert result["record_revision"] is None
    assert result["revision_artifact_sha256"] is None


@pytest.mark.parametrize(
    "field",
    ["resource_key", "ingestion_run_id", "county_fips", "source_record_id", "source_row_hash"],
)
def test_wrong_restricted_identity_remains_unmatched(db, field) -> None:
    table = seed(db, "tick")
    db.execute(f"UPDATE {table} SET {field} = 'fixture-mismatch'")
    result = dict(db.execute(SELECT).fetchone())
    assert result["record_match_kind"] == "UNMATCHED"
    assert result["governed_source_row_hash"] is None
    assert result["artifact_sha256"] is None


@pytest.mark.parametrize("field", ["source_id", "dataset_id"])
def test_restricted_table_does_not_prove_other_publisher_tuple(db, field) -> None:
    seed(db, "pathogen")
    db.execute(f"UPDATE PRESENTATION.SEMANTIC_DATA_SOURCES SET {field} = 'fixture-other'")
    assert db.execute(SELECT).fetchone()["record_match_kind"] == "UNMATCHED"


@pytest.mark.parametrize("field", ["evidence_run_id", "workbook_sha256"])
def test_wrong_restricted_artifact_proof_stays_unverified(db, field) -> None:
    table = seed(db, "pathogen")
    db.execute(f"UPDATE {table} SET {field} = 'fixture-mismatch'")
    result = db.execute(SELECT).fetchone()
    assert result["record_match_kind"] == "RESTRICTED_CDC_CONFORMED"
    assert (
        result["artifact_sha256"] is None
    )  # Existing acceptance must reject this incomplete chain.


def test_parity_classification_is_not_a_publisher_record_and_duplicates_stay_visible(db) -> None:
    table = seed(db, "tick")
    db.execute(f"INSERT INTO {table} SELECT * FROM {table}")
    assert len(db.execute(SELECT).fetchall()) == 2
    db.execute("UPDATE PRESENTATION.SEMANTIC_OBSERVATIONS SET source_record_id = 'fixture-parity'")
    assert db.execute(SELECT).fetchone()["record_match_kind"] == "UNMATCHED"


@pytest.mark.parametrize("revision", [False, True])
def test_existing_generic_precedence_and_derivation_artifact_are_unchanged(db, revision) -> None:
    seed(db, "tick")
    db.execute("UPDATE GOVERNANCE.RAW_ARTIFACTS SET ingestion_run_id = 'fixture-derivation'")
    db.execute(
        "INSERT INTO CONFORMED.GOVERNED_SOURCE_RECORDS VALUES (?,?,?,?,?,?,?)",
        (
            "fixture-generic",
            "cdc_arbonet_tick_module",
            "cdc-ixodes-county-status-2025",
            "cdc_tick_ixodes_county_status",
            "fixture-derivation",
            "fixture-native",
            "b" * 64,
        ),
    )
    if revision:
        db.execute(
            "INSERT INTO GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "fixture-capture",
                "fixture-revision",
                "fixture-generic",
                "cdc_arbonet_tick_module",
                "cdc-ixodes-county-status-2025",
                "cdc_tick_ixodes_county_status",
                "fixture-derivation",
                "fixture-artifact",
                "c" * 64,
                "fixture-native",
                "b" * 64,
            ),
        )
    result = db.execute(SELECT).fetchone()
    assert result["record_match_kind"] == ("IMMUTABLE_REVISION" if revision else "LEGACY_CONFORMED")
    assert result["artifact_sha256"] == "c" * 64
    assert result["conformed_record_id"] == (None if revision else "fixture-generic")
    legacy = (ROOT / "migrations/V137__semantic_lineage_audit_view.sql").read_text()
    legacy_select = "SELECT o.observation_id," + legacy.split(" AS\nSELECT o.observation_id,", 1)[1]
    legacy_select = legacy_select.split(";\n\nGRANT", 1)[0]
    assert dict(result) == dict(db.execute(legacy_select).fetchone())
