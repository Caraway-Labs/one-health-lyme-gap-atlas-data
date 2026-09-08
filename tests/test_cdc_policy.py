from urllib.error import HTTPError

import pytest

from lyme_gap_atlas_data.cdc_policy import (
    metadata_fingerprint,
    publication_decision,
    snapshot_checksum,
    transient_source_error,
)


def test_checksum_is_order_independent_but_detects_duplicates() -> None:
    a, b = "a" * 64, "b" * 64
    assert snapshot_checksum([a, b]) == snapshot_checksum([b, a])
    assert snapshot_checksum([a, b]) != snapshot_checksum([a, b, b])


def test_empty_snapshot_is_rejected() -> None:
    with pytest.raises(ValueError):
        snapshot_checksum([])


def test_popularity_is_not_a_data_change() -> None:
    metadata = {
        "id": "x5j9-wybp",
        "rowsUpdatedAt": 123,
        "columns": [{"fieldName": "year", "dataTypeName": "number"}],
    }
    assert metadata_fingerprint(metadata) == metadata_fingerprint({**metadata, "viewCount": 999})
    assert metadata_fingerprint(metadata) != metadata_fingerprint(
        {**metadata, "rowsUpdatedAt": 124}
    )


@pytest.mark.parametrize("code,retry", [(429, True), (503, True), (400, False), (401, False)])
def test_retry_is_limited_to_transient_responses(code: int, retry: bool) -> None:
    assert transient_source_error(HTTPError("https://data.cdc.gov", code, "", None, None)) == retry


def test_unchanged_does_not_advance_publication() -> None:
    assert (
        publication_decision(
            current_revision=2,
            expected_revision=2,
            current_checksum="same",
            candidate_checksum="same",
            failed_checks=0,
            check_count=8,
        )
        == "UNCHANGED"
    )


@pytest.mark.parametrize("revision,failed,count", [(3, 0, 8), (2, 1, 8), (2, 0, 7)])
def test_stale_or_unvalidated_candidate_cannot_publish(
    revision: int, failed: int, count: int
) -> None:
    with pytest.raises(ValueError):
        publication_decision(
            current_revision=revision,
            expected_revision=2,
            current_checksum="old",
            candidate_checksum="new",
            failed_checks=failed,
            check_count=count,
        )
