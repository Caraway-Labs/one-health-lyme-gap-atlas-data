"""Exercise the actual reuse SQL against relational source/receipt fixtures."""

import sqlite3
from collections.abc import Iterator
from typing import Any

import pytest

from lyme_gap_atlas_data.semantic_release import (
    SemanticReleaseBlocked,
    _verify_restricted_final_copy_attestations,
)


class Cursor:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.cursor = connection.cursor()

    def execute(self, statement: str, parameters: tuple[str, ...]) -> None:
        self.cursor.execute(statement.replace("%s", "?"), parameters)

    def fetchone(self) -> Any:
        return self.cursor.fetchone()

    def fetchall(self) -> Any:
        return self.cursor.fetchall()


@pytest.fixture
def database() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:")
    connection.create_function("TO_JSON", 1, lambda value: value)
    connection.executescript(
        """ATTACH DATABASE ':memory:' AS PRESENTATION;
        ATTACH DATABASE ':memory:' AS GOVERNANCE;
        CREATE TABLE PRESENTATION.SEMANTIC_RELEASES
          (release_id TEXT, status TEXT, methodology_version TEXT, schema_version TEXT,
           bundle_sha256 TEXT);
        CREATE TABLE PRESENTATION.SEMANTIC_DATA_SOURCES
          (release_id TEXT, resource_key TEXT, source_key TEXT, source_version_id TEXT,
           source_id TEXT, dataset_id TEXT, ingestion_run_id TEXT, artifact_id TEXT,
           label TEXT, vintage TEXT, source_url TEXT, note TEXT);
        CREATE TABLE GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS
          (semantic_release_id TEXT, resource_key TEXT, data_source_version_id TEXT,
           delivery_reference TEXT, attested_by TEXT, delivered_at TEXT);
        CREATE TABLE PRESENTATION.SEMANTIC_OBSERVATIONS
          (release_id TEXT, observation_id TEXT, measure_id TEXT, fips TEXT, source_key TEXT,
           source_version_id TEXT, ingestion_run_id TEXT, artifact_id TEXT,
           source_record_id TEXT, source_row_hash TEXT, value TEXT, value_state TEXT,
           retrieved_at TEXT, geography_semantics TEXT, temporal_window TEXT,
           transformation_version TEXT, quality_state TEXT, limitations TEXT);
        CREATE TABLE PRESENTATION.SEMANTIC_MEASURES
          (release_id TEXT, measure_id TEXT, indicator_id TEXT, label TEXT, data_type TEXT,
           unit TEXT, geography_semantics TEXT, temporal_resolution TEXT,
           missingness_semantics TEXT, methodology TEXT, limitation TEXT);
        CREATE TABLE PRESENTATION.SEMANTIC_INDICATORS
          (release_id TEXT, indicator_id TEXT);
        INSERT INTO PRESENTATION.SEMANTIC_INDICATORS VALUES
          ('baseline','tick'), ('candidate','tick');
        INSERT INTO PRESENTATION.SEMANTIC_MEASURES VALUES
          ('baseline','status','tick','status','STRING','status','COUNTY','2025',
           'no records is not absence','method','no risk inference'),
          ('candidate','status','tick','status','STRING','status','COUNTY','2025',
           'no records is not absence','method','no risk inference');
        INSERT INTO PRESENTATION.SEMANTIC_RELEASES
          (release_id,status,methodology_version,schema_version) VALUES
          ('baseline','PUBLISHED','method-1','1'), ('candidate','CANDIDATE','method-1','1');
        """
    )
    for key, resource in (
        ("tick", "cdc_tick_ixodes_county_status"),
        ("pathogen", "cdc_tick_ixodes_pathogen_status"),
    ):
        for release in ("baseline", "candidate"):
            connection.execute(
                "INSERT INTO PRESENTATION.SEMANTIC_DATA_SOURCES VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    release,
                    resource,
                    key,
                    "v1",
                    "source",
                    "dataset",
                    "run",
                    "artifact",
                    "label",
                    "2025",
                    "https://cdc.example",
                    "unchanged interpretation",
                ),
            )
            connection.execute(
                "INSERT INTO PRESENTATION.SEMANTIC_OBSERVATIONS VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    release,
                    release + key,
                    "status",
                    "51013",
                    key,
                    "v1",
                    "run",
                    "artifact",
                    "record",
                    "hash",
                    "0",
                    "ZERO",
                    "time",
                    "COUNTY",
                    "2025",
                    "transform",
                    "COMPLETE",
                    "no risk inference",
                ),
            )
        connection.execute(
            "INSERT INTO GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS "
            "VALUES (?,?,?,?,?,?)",
            ("baseline", resource, "v1", "retained-receipt", "verified-human", "time"),
        )
    yield connection
    connection.close()


def test_unchanged_published_copy_reuses_receipts_without_writes(
    database: sqlite3.Connection,
) -> None:
    before = database.total_changes
    _verify_restricted_final_copy_attestations(Cursor(database), "candidate")
    assert database.total_changes == before


@pytest.mark.parametrize("legacy_release", ["baseline", "candidate"])
def test_v124_legacy_measure_identity_reuses_unchanged_copy(
    database: sqlite3.Connection, legacy_release: str
) -> None:
    database.execute(
        "UPDATE PRESENTATION.SEMANTIC_MEASURES "
        "SET measure_id=indicator_id, indicator_id=measure_id WHERE release_id=?",
        (legacy_release,),
    )
    before = database.total_changes
    _verify_restricted_final_copy_attestations(Cursor(database), "candidate")
    assert database.total_changes == before


@pytest.mark.parametrize("column", ["unit", "label", "methodology", "missingness_semantics"])
def test_legacy_identity_does_not_hide_changed_interpretation(
    database: sqlite3.Connection, column: str
) -> None:
    database.execute(
        "UPDATE PRESENTATION.SEMANTIC_MEASURES "
        "SET measure_id=indicator_id, indicator_id=measure_id WHERE release_id='baseline'"
    )
    database.execute(
        f"UPDATE PRESENTATION.SEMANTIC_MEASURES SET {column}='changed' WHERE release_id='candidate'"
    )
    with pytest.raises(SemanticReleaseBlocked):
        _verify_restricted_final_copy_attestations(Cursor(database), "candidate")


@pytest.mark.parametrize(
    "mutation",
    [
        "DELETE FROM PRESENTATION.SEMANTIC_INDICATORS WHERE release_id='baseline'",
        "UPDATE PRESENTATION.SEMANTIC_MEASURES SET indicator_id='unknown' "
        "WHERE release_id='candidate'",
        "INSERT INTO PRESENTATION.SEMANTIC_MEASURES SELECT * "
        "FROM PRESENTATION.SEMANTIC_MEASURES WHERE release_id='candidate'",
    ],
)
def test_incomplete_or_duplicate_measure_identity_fails_closed(
    database: sqlite3.Connection, mutation: str
) -> None:
    database.execute(mutation)
    with pytest.raises(SemanticReleaseBlocked):
        _verify_restricted_final_copy_attestations(Cursor(database), "candidate")


@pytest.mark.parametrize(
    "column",
    [
        "source_version_id",
        "artifact_id",
        "ingestion_run_id",
        "source_id",
        "dataset_id",
        "source_key",
        "label",
        "vintage",
        "source_url",
        "note",
    ],
)
def test_changed_source_copy_cannot_reuse(database: sqlite3.Connection, column: str) -> None:
    database.execute(
        f"UPDATE PRESENTATION.SEMANTIC_DATA_SOURCES SET {column}='changed' "
        "WHERE release_id='candidate' AND source_key='tick'"
    )
    with pytest.raises(SemanticReleaseBlocked):
        _verify_restricted_final_copy_attestations(Cursor(database), "candidate")


@pytest.mark.parametrize(
    "column",
    [
        "value",
        "value_state",
        "source_row_hash",
        "limitations",
        "quality_state",
        "transformation_version",
        "geography_semantics",
        "retrieved_at",
    ],
)
def test_changed_output_requires_new_delivery(database: sqlite3.Connection, column: str) -> None:
    database.execute(
        f"UPDATE PRESENTATION.SEMANTIC_OBSERVATIONS SET {column}='changed' "
        "WHERE release_id='candidate' AND source_key='tick'"
    )
    with pytest.raises(SemanticReleaseBlocked):
        _verify_restricted_final_copy_attestations(Cursor(database), "candidate")


@pytest.mark.parametrize(
    "mutation",
    [
        "DELETE FROM GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS",
        "UPDATE GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS SET attested_by=''",
        "UPDATE GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS SET delivery_reference=''",
        "UPDATE GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS SET delivered_at=NULL",
        "UPDATE GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS "
        "SET data_source_version_id='v2'",
        "UPDATE PRESENTATION.SEMANTIC_RELEASES SET status='CANDIDATE' WHERE release_id='baseline'",
        "UPDATE PRESENTATION.SEMANTIC_RELEASES SET methodology_version='v2' "
        "WHERE release_id='candidate'",
        "DELETE FROM PRESENTATION.SEMANTIC_OBSERVATIONS WHERE release_id='candidate'",
        "DELETE FROM PRESENTATION.SEMANTIC_MEASURES WHERE release_id='candidate'",
        "UPDATE PRESENTATION.SEMANTIC_MEASURES SET unit='changed' WHERE release_id='candidate'",
        "INSERT INTO PRESENTATION.SEMANTIC_OBSERVATIONS SELECT * "
        "FROM PRESENTATION.SEMANTIC_OBSERVATIONS WHERE release_id='candidate'",
    ],
)
def test_invalid_evidence_fails_closed(database: sqlite3.Connection, mutation: str) -> None:
    database.execute(mutation)
    with pytest.raises(SemanticReleaseBlocked):
        _verify_restricted_final_copy_attestations(Cursor(database), "candidate")


def test_candidate_receipt_can_mix_with_retired_prior_receipt(database: sqlite3.Connection) -> None:
    database.execute(
        "UPDATE GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS "
        "SET semantic_release_id='candidate' WHERE resource_key='cdc_tick_ixodes_county_status'"
    )
    database.execute(
        "UPDATE PRESENTATION.SEMANTIC_RELEASES SET status='RETIRED' WHERE release_id='baseline'"
    )
    _verify_restricted_final_copy_attestations(Cursor(database), "candidate")


JANUARY = "governed-2026-10-15-january-climate-prod"
DONOR = "governed-2026-10-06-nlcd-demo-cohort"
JANUARY_BUNDLE = "53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d"
DONOR_BUNDLE = "603afb135a1a5c958d1d56d48d580d9942c67eb38986caf8b4b3acf69fcde2c9"


@pytest.fixture
def january_database(database: sqlite3.Connection) -> sqlite3.Connection:
    for table in (
        "SEMANTIC_RELEASES",
        "SEMANTIC_DATA_SOURCES",
        "SEMANTIC_OBSERVATIONS",
        "SEMANTIC_MEASURES",
        "SEMANTIC_INDICATORS",
    ):
        for old, new in (("candidate", JANUARY), ("baseline", DONOR)):
            database.execute(
                f"UPDATE PRESENTATION.{table} SET release_id=? WHERE release_id=?", (new, old)
            )
    database.execute(
        "UPDATE GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS "
        "SET semantic_release_id=? WHERE semantic_release_id='baseline'",
        (DONOR,),
    )
    for release, bundle, schema, method in (
        (JANUARY, JANUARY_BUNDLE, "2.0.0", "semantic-2.0.0"),
        (DONOR, DONOR_BUNDLE, "1.0.0", "semantic-1.0.0"),
    ):
        database.execute(
            "UPDATE PRESENTATION.SEMANTIC_RELEASES SET bundle_sha256=?,schema_version=?,"
            "methodology_version=? WHERE release_id=?",
            (bundle, schema, method, release),
        )
    for source, resource, version in (
        ("tick", "cdc_tick_ixodes_county_status", "b81c116f-d93d-4c6b-9d11-ac2477e0e242"),
        ("pathogen", "cdc_tick_ixodes_pathogen_status", "92b22f19-0d5d-4576-a7c6-6c9af9343edf"),
    ):
        database.execute(
            "UPDATE PRESENTATION.SEMANTIC_DATA_SOURCES SET source_version_id=? WHERE source_key=?",
            (version, source),
        )
        database.execute(
            "UPDATE PRESENTATION.SEMANTIC_OBSERVATIONS SET source_version_id=? WHERE source_key=?",
            (version, source),
        )
        database.execute(
            "UPDATE GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS "
            "SET data_source_version_id=? WHERE resource_key=?",
            (version, resource),
        )
    return database


def test_exact_january_addition_reuses_real_unchanged_copies_without_writes(january_database):
    before = january_database.total_changes
    _verify_restricted_final_copy_attestations(Cursor(january_database), JANUARY)
    assert january_database.total_changes == before
    assert january_database.execute(
        "SELECT COUNT(*) FROM GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS "
        "WHERE semantic_release_id=?",
        (JANUARY,),
    ).fetchone() == (0,)


@pytest.mark.parametrize("release", [JANUARY, DONOR])
@pytest.mark.parametrize(
    "field", ["bundle_sha256", "schema_version", "methodology_version", "status"]
)
def test_january_exception_requires_exact_release_contract(january_database, release, field):
    january_database.execute(
        f"UPDATE PRESENTATION.SEMANTIC_RELEASES SET {field}='changed' WHERE release_id=?",
        (release,),
    )
    with pytest.raises(SemanticReleaseBlocked):
        _verify_restricted_final_copy_attestations(Cursor(january_database), JANUARY)


@pytest.mark.parametrize("release", [JANUARY, DONOR])
def test_january_exception_does_not_apply_to_other_release_ids(january_database, release):
    january_database.execute(
        "UPDATE PRESENTATION.SEMANTIC_RELEASES SET release_id='other' WHERE release_id=?",
        (release,),
    )
    with pytest.raises(SemanticReleaseBlocked):
        _verify_restricted_final_copy_attestations(Cursor(january_database), JANUARY)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE PRESENTATION.SEMANTIC_DATA_SOURCES SET artifact_id='changed' WHERE release_id=?",
        "UPDATE PRESENTATION.SEMANTIC_DATA_SOURCES SET note='changed' WHERE release_id=?",
        "UPDATE PRESENTATION.SEMANTIC_DATA_SOURCES "
        "SET source_version_id='changed' WHERE release_id=?",
        "UPDATE PRESENTATION.SEMANTIC_OBSERVATIONS SET value='changed' WHERE release_id=?",
        "UPDATE PRESENTATION.SEMANTIC_OBSERVATIONS SET source_row_hash='changed' "
        "WHERE release_id=?",
        "UPDATE PRESENTATION.SEMANTIC_OBSERVATIONS SET transformation_version='changed' "
        "WHERE release_id=?",
        "UPDATE PRESENTATION.SEMANTIC_MEASURES SET unit='changed' WHERE release_id=?",
        "UPDATE PRESENTATION.SEMANTIC_MEASURES SET methodology='changed' WHERE release_id=?",
        "DELETE FROM PRESENTATION.SEMANTIC_MEASURES WHERE release_id=?",
        "DELETE FROM PRESENTATION.SEMANTIC_OBSERVATIONS WHERE release_id=?",
    ],
)
def test_january_exception_never_hides_changed_copy(january_database, mutation):
    january_database.execute(mutation, (JANUARY,))
    with pytest.raises(SemanticReleaseBlocked):
        _verify_restricted_final_copy_attestations(Cursor(january_database), JANUARY)


@pytest.mark.parametrize(
    "mutation",
    [
        "DELETE FROM GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS",
        "UPDATE GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS SET delivered_at=NULL",
        "UPDATE GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS SET delivery_reference=''",
        "UPDATE GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS SET attested_by=''",
    ],
)
def test_january_exception_still_requires_real_prior_delivery(january_database, mutation):
    january_database.execute(mutation)
    with pytest.raises(SemanticReleaseBlocked):
        _verify_restricted_final_copy_attestations(Cursor(january_database), JANUARY)


def test_january_exception_cannot_reuse_other_matching_source_versions(january_database):
    for table in ("SEMANTIC_DATA_SOURCES", "SEMANTIC_OBSERVATIONS"):
        january_database.execute(
            f"UPDATE PRESENTATION.{table} SET source_version_id='another-matching-version'"
        )
    january_database.execute(
        "UPDATE GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS "
        "SET data_source_version_id='another-matching-version'"
    )
    with pytest.raises(SemanticReleaseBlocked):
        _verify_restricted_final_copy_attestations(Cursor(january_database), JANUARY)
