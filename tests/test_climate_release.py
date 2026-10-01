"""Offline release activation checks; review/source identities are fixtures."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_climate_semantics import climate_metadata
from test_semantic_metadata import known, seal

from lyme_gap_atlas_data import climate_release as climate
from lyme_gap_atlas_data import semantic_release as releases


def extension() -> dict:
    metadata = [climate_metadata(index) for index in range(4)]
    for item in metadata:
        item["visibility"] = "CONSUMER_SAFE"
        item["steward_review"] = {"state": "REVIEWED", "reviewed_at": known("2026-10-01")}
        item["quality_evidence"]["evidence_basis"] = known("CURRENT_CODE_SOURCE_BACKED_REPLAY")
        seal(item)
    return {
        "contract_version": climate.CONTRACT,
        "period": climate.PERIOD,
        "ingestion_run_id": climate.RUN_ID,
        "candidate_sha256": climate.CANDIDATE_SHA,
        "capture_membership_sha256": "b" * 64,
        "row_count": climate.ROW_COUNT,
        "capture_ids": ["e" * 64]
        if climate.ROW_COUNT == 1
        else [f"{index:064x}" for index in range(climate.ROW_COUNT)],
        "metadata": metadata,
        "sources": {
            "noaa": {
                "source_version_id": "fixture-version-1",
                "artifact_id": climate.NOAA_ARTIFACT_ID,
                "sha256": climate.NOAA_SHA,
                "resource_key": climate.RESOURCE_KEY,
            },
            "tiger": {
                "source_version_id": "fixture-tiger-version",
                "artifact_id": "fixture-tiger-artifact",
                "sha256": climate.TIGER_SHA,
                "resource_key": "fixture-tiger-resource-2025",
            },
        },
        "review_evidence": {
            "commit": "a" * 40,
            "url": "https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/"
            "pull/1#pullrequestreview-1",
            "reviewer": "offline-review-fixture",
        },
    }


def test_exact_reviewed_consumer_metadata_and_source_pins_validate() -> None:
    climate.validate_extension(extension())


@pytest.mark.parametrize(
    "mutation",
    [
        "period",
        "digest",
        "pending",
        "method",
        "source",
        "extra",
        "review",
        "fixture_basis",
        "duplicate",
    ],
)
def test_release_contract_rejects_unapproved_or_changed_meaning(mutation: str) -> None:
    document = extension()
    if mutation == "period":
        document["period"] = "2024-01-01/2024-01-31"
    elif mutation == "digest":
        document["candidate_sha256"] = "0" * 64
    elif mutation == "pending":
        document["metadata"][0]["steward_review"]["state"] = "PENDING"
    elif mutation == "method":
        document["metadata"][0]["measure"]["methodology_version"] = "atlas-nclimgrid-county-day/1"
    elif mutation == "source":
        document["sources"]["noaa"]["source_version_id"] = "unrelated-source"
    elif mutation == "extra":
        document["new_month"] = "202502"
    elif mutation == "review":
        document["review_evidence"] = {}
    elif mutation == "fixture_basis":
        document["metadata"][0]["quality_evidence"]["evidence_basis"] = known("SYNTHETIC_FIXTURE")
    else:
        document["metadata"][1] = copy.deepcopy(document["metadata"][0])
    for item in document["metadata"]:
        seal(item)
    with pytest.raises(ValueError):
        climate.validate_extension(document)


def test_membership_is_recomputed_from_retained_revision_tuples(monkeypatch) -> None:
    monkeypatch.setattr(climate, "verify_payload_candidate", lambda cursor, digest: None)
    monkeypatch.setattr(climate, "ROW_COUNT", 1)
    document = extension()
    record = ("e" * 64, "revision-fixture", "record-fixture", "c" * 64, "d" * 64)
    document["capture_membership_sha256"] = hashlib.sha256(
        (json.dumps(list(record), separators=(",", ":")) + "\n").encode()
    ).hexdigest()

    class Cursor:
        def __init__(self):
            self.results = iter(
                [
                    [("APPROVED", "decision-noaa", None)],
                    [("APPROVED", "decision-tiger", None)],
                    [(climate.RESOURCE_KEY, "COMPLETED")],
                ]
            )
            self.singles = iter([(10, 0), (1,), (1, 0)])
            self.batches = iter([[record], []])

        def execute(self, query, parameters):
            assert query.lstrip().startswith("SELECT")
            assert "source_noaa_nclimgrid_daily" not in query
            if "v.status" in query:
                assert "v.resource_key=%s" in query
                assert parameters[-1] in {climate.RESOURCE_KEY, "fixture-tiger-resource-2025"}

        def fetchall(self):
            return next(self.results)

        def fetchone(self):
            return next(self.singles)

        def fetchmany(self, size):
            return next(self.batches)

    climate.verify_extension(Cursor(), document)
    document["capture_membership_sha256"] = "0" * 64
    with pytest.raises(climate.ClimateReleaseBlocked, match="MEMBERSHIP_DIGEST"):
        climate.verify_extension(Cursor(), document)


def test_revision_authority_is_never_returned_before_target_verification(monkeypatch):
    document = extension()
    calls = []
    monkeypatch.setattr(climate, "verify_extension", lambda cursor, value: calls.append(value))
    approved = climate.verified_climate_metadata_revisions(None, document)
    assert calls == [document]
    assert approved == {item["revision_id"] for item in document["metadata"]}

    def blocked(cursor, value):
        raise climate.ClimateReleaseBlocked("CLIMATE_TARGET_CANDIDATE_DIGEST")

    monkeypatch.setattr(climate, "verify_extension", blocked)
    with pytest.raises(climate.ClimateReleaseBlocked):
        climate.verified_climate_metadata_revisions(None, document)


@pytest.mark.parametrize("operation", ["publish", "rollback"])
def test_persisted_validation_precedes_every_pointer_mutation(monkeypatch, operation) -> None:
    class Cursor:
        def __init__(self):
            self.queries = []
            self.rows = iter(
                [("CANDIDATE", "b" * 64), (3144, 3144, 44016), ("DEV",)]
                if operation == "publish"
                else [("RETIRED",)]
            )

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, parameters=None):
            self.queries.append(query)

        def fetchone(self):
            return next(self.rows)

    cursor = Cursor()

    class Connection:
        rolled_back = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def autocommit(self, value):
            assert value is False

        def cursor(self):
            return cursor

        def rollback(self):
            self.rolled_back = True

        def commit(self):
            pytest.fail("Blocked extension must not commit")

    connection = Connection()
    monkeypatch.setattr(releases, "connect", lambda settings: connection)

    def blocked(cursor, release_id):
        assert release_id == "fixture-release"
        assert all(query.lstrip().startswith("SELECT") for query in cursor.queries)
        raise climate.ClimateReleaseBlocked("CLIMATE_MEMBERSHIP_DIGEST")

    monkeypatch.setattr(releases, "verify_persisted_extension", blocked)
    function = (
        releases.publish_semantic_release
        if operation == "publish"
        else releases.rollback_semantic_release
    )
    with pytest.raises(climate.ClimateReleaseBlocked):
        function(SimpleNamespace(), "fixture-release", reason="Offline fixture")
    assert connection.rolled_back


def test_sql_is_separate_daily_native_numeric_allowlist_without_grants() -> None:
    sql = (Path(__file__).parents[1] / "sql/january_climate_consumer_views.sql").read_text()
    assert "AS_DOUBLE(record:value)" in sql
    assert "TO_JSON(" not in sql
    assert "GRANT " not in sql
    assert "CURRENT_COUNTY_OBSERVATIONS_V" not in sql
    for column in (
        "expected_area_m2",
        "intersected_area_m2",
        "source_supported_area_m2",
        "valid_area_m2",
        "source_coverage_fraction",
        "valid_fraction_of_supported_area",
        "upstream_date_modified",
        "day_convention",
    ):
        assert f"AS {column}" in sql


@pytest.mark.parametrize(
    "field,value",
    [
        ("value", 17.0),
        ("unit", "inches"),
        ("county_fips", "99999"),
        ("coverage_status", "SOURCE_MISSING"),
        ("valid_area_m2", 17.0),
        ("valid_fraction_of_supported_area", 0.1),
    ],
)
def test_target_payload_corruption_with_unchanged_headers_is_rejected(monkeypatch, field, value):
    from test_climate_publication import fixture_capture

    from lyme_gap_atlas_data.climate_publication import ClimatePublicationBlocked

    capture = fixture_capture()
    original = json.loads(capture["payload"])
    changed = copy.deepcopy(original)
    changed["record"][field] = value
    capture["payload"] = changed
    if f"rendered_{field}" in capture:
        capture[f"rendered_{field}"] = json.dumps(value)
        if capture[f"stored_type_{field}"] == "DOUBLE":
            capture[f"native_{field}"] = value
    # Every persisted revision/header hash is deliberately unchanged.
    partition = SimpleNamespace(ordinal=0, records=[original])
    monkeypatch.setattr(climate, "canonical_partitions", lambda cursor: iter([partition]))

    class Cursor:
        description = [(key,) for key in capture]

        def execute(self, query, parameters):
            assert "GOVERNED_SOURCE_RECORD_REVISIONS" in query

        def fetchall(self):
            return [tuple(capture.values())]

    with pytest.raises(ClimatePublicationBlocked, match="REVISION_CONTENT"):
        climate.verify_payload_candidate(Cursor(), climate.CANDIDATE_SHA)
