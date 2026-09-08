from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest

from lyme_gap_atlas_data import cdc_operations


def connection_fixture(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    monkeypatch.setattr(cdc_operations, "connect", lambda _: connection)
    monkeypatch.setattr(cdc_operations, "cdc_operation", lambda: nullcontext("lease"))
    return connection


@pytest.mark.parametrize("recent", [0, 1])
def test_readiness_requires_quality_and_recent_metadata(
    monkeypatch: pytest.MonkeyPatch, recent: int
) -> None:
    connection = connection_fixture(monkeypatch)
    connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (recent,)
    monkeypatch.setattr(cdc_operations, "require_publication_enabled", lambda: None)
    quality = MagicMock()
    monkeypatch.setattr(cdc_operations, "record_cdc_quality", quality)
    if recent:
        assert cdc_operations.verify_cdc_ready("source")["status"] == "READY"
    else:
        with pytest.raises(ValueError):
            cdc_operations.verify_cdc_ready("source")
    quality.assert_called_once_with("source")


@pytest.mark.parametrize(
    "previous,expected", [(None, "BASELINE"), (("abc",), "UNCHANGED"), (("old",), "CHANGED")]
)
def test_metadata_check_records_signal_without_full_ingestion(
    monkeypatch: pytest.MonkeyPatch, previous: object, expected: str
) -> None:
    connection = connection_fixture(monkeypatch)
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = previous
    monkeypatch.setattr(cdc_operations, "current_metadata_fingerprint", lambda: "abc")
    ingestion = MagicMock()
    monkeypatch.setattr(cdc_operations, "ingest_approved_cdc", ingestion)
    result = cdc_operations.check_cdc_metadata()
    assert result["status"] == expected
    assert cursor.execute.call_args.args[1][2] == expected
    connection.commit.assert_called_once()
    ingestion.assert_not_called()


def test_metadata_failure_is_committed_and_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = connection_fixture(monkeypatch)
    monkeypatch.setattr(
        cdc_operations, "current_metadata_fingerprint", MagicMock(side_effect=TimeoutError)
    )
    incident = MagicMock()
    monkeypatch.setattr(cdc_operations, "record_incident", incident)
    with pytest.raises(TimeoutError):
        cdc_operations.check_cdc_metadata()
    connection.commit.assert_called_once()
    statement = connection.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
    assert "'FAILED','CDC_METADATA_FAILED'" in statement
    assert incident.call_args.args[0] == "METADATA_FAILED"


def test_refresh_rejects_changed_metadata_before_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = connection_fixture(monkeypatch)
    connection.cursor.return_value.__enter__.return_value.fetchone.side_effect = [
        ("source",),
        ("old",),
    ]
    monkeypatch.setattr(cdc_operations, "require_publication_enabled", lambda: None)
    monkeypatch.setattr(cdc_operations, "current_metadata_fingerprint", lambda: "changed")
    ingestion = MagicMock()
    monkeypatch.setattr(cdc_operations, "ingest_approved_cdc", ingestion)
    with pytest.raises(ValueError, match="Publisher metadata changed"):
        cdc_operations.operator_refresh("check")
    ingestion.assert_not_called()


def test_refresh_pins_source_and_reports_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = connection_fixture(monkeypatch)
    connection.cursor.return_value.__enter__.return_value.fetchone.side_effect = [
        ("source",),
        ("abc",),
    ]
    monkeypatch.setattr(cdc_operations, "require_publication_enabled", lambda: None)
    monkeypatch.setattr(cdc_operations, "current_metadata_fingerprint", lambda: "abc")
    ingestion = MagicMock(return_value={"ingestion_run_id": "run", "source_version_id": "source"})
    monkeypatch.setattr(cdc_operations, "ingest_approved_cdc", ingestion)
    monkeypatch.setattr(
        cdc_operations, "build_approved_cdc_models", MagicMock(side_effect=ValueError("quality"))
    )
    incident = MagicMock()
    monkeypatch.setattr(cdc_operations, "record_incident", incident)
    with pytest.raises(ValueError, match="quality"):
        cdc_operations.operator_refresh("check")
    ingestion.assert_called_once_with(expected_metadata="abc", expected_source_version_id="source")
    incident.assert_called_once_with("VALIDATION_FAILED", "validation:run", "run")
