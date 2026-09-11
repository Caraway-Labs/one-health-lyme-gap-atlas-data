from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lyme_gap_atlas_data import cdc, cdc_quality


def quality_connection(monkeypatch: pytest.MonkeyPatch, checks: list[tuple]) -> MagicMock:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (1,)
    cursor.fetchall.return_value = checks
    monkeypatch.setattr(cdc_quality, "connect", lambda _: connection)
    return connection


def test_failed_checks_are_committed_before_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = quality_connection(
        monkeypatch,
        [("run-1", "row_reconciliation", 5045, 5044), ("run-1", "source_hash_integrity", 0, 0)],
    )
    with pytest.raises(cdc_quality.CdcQualityError, match="1 blocking"):
        cdc_quality.record_cdc_quality("version-1", ingestion_run_id="run-1")
    connection.commit.assert_called_once()
    connection.rollback.assert_not_called()
    cursor = connection.cursor.return_value.__enter__.return_value
    inserts = [call.args for call in cursor.execute.call_args_list if "INSERT INTO" in call.args[0]]
    assert len(inserts) == 2
    assert inserts[0][1][3] == "FAILED"
    assert inserts[1][1][3] == "PASSED"
    assert inserts[0][1][1] == "run-1"
    assert inserts[0][1][-1] == inserts[1][1][-1]


def test_partial_evidence_write_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = quality_connection(monkeypatch, [("run-1", "nonempty_raw", 1, 1)])
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = [None, None, RuntimeError("write failed")]
    with pytest.raises(RuntimeError, match="write failed"):
        cdc_quality.record_cdc_quality("version-1", ingestion_run_id="run-1")
    connection.rollback.assert_called_once()
    connection.commit.assert_not_called()


def test_empty_data_cannot_report_success(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = quality_connection(monkeypatch, [])
    with pytest.raises(cdc_quality.CdcQualityError, match="retained source rows"):
        cdc_quality.record_cdc_quality("version-1", ingestion_run_id="run-1")
    connection.commit.assert_not_called()


def test_dbt_success_still_fails_when_quality_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cdc, "cdc_operation", lambda: nullcontext("lease"))
    monkeypatch.setattr(cdc, "publication_context", lambda _: ("run-1", 0))
    monkeypatch.setattr(cdc.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))

    def fail(_version: str, **kwargs: object) -> None:
        raise cdc_quality.CdcQualityError("evidence retained")

    monkeypatch.setattr(cdc, "record_cdc_quality", fail)
    with pytest.raises(cdc.CdcDbtBuildError, match="DATA_QUALITY_FAILED"):
        cdc.build_approved_cdc_models("version-1")
