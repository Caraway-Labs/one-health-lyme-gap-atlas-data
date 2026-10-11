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
          (release_id TEXT, status TEXT, methodology_version TEXT, schema_version TEXT);
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
        INSERT INTO PRESENTATION.SEMANTIC_MEASURES VALUES
          ('baseline','status','tick','status','STRING','status','COUNTY','2025',
           'no records is not absence','method','no risk inference'),
          ('candidate','status','tick','status','STRING','status','COUNTY','2025',
           'no records is not absence','method','no risk inference');
        INSERT INTO PRESENTATION.SEMANTIC_RELEASES VALUES
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
