from datetime import datetime
from unittest.mock import MagicMock

import pytest

from lyme_gap_atlas_data import cdc_monitor


def test_monitor_reports_failure_and_overdue_without_historical_noise() -> None:
    events = [
        {
            "id": "old",
            "job_name": "approved-source-ingestion",
            "phase": "FAILED",
            "created_at": "2026-07-01T15:00:00Z",
        },
        {
            "id": "failed",
            "job_name": "approved-source-ingestion",
            "phase": "FAILED",
            "created_at": "2026-09-01T15:00:00Z",
        },
        {
            "id": "unrelated",
            "job_name": "catalog-discovery",
            "phase": "FAILED",
            "created_at": "2026-09-02T15:00:00Z",
        },
    ]
    result = cdc_monitor.incident_candidates(
        events,
        now=datetime.fromisoformat("2026-09-09T18:00:00+00:00"),
        enabled_at=datetime.fromisoformat("2026-08-15T18:00:00+00:00"),
    )
    assert set(result) == {"job:failed", "overdue:2026-09"}


def test_successful_watchdog_does_not_mask_overdue_metadata() -> None:
    event = {
        "id": "watchdog",
        "job_name": "cdc-operations-watchdog",
        "phase": "SUCCEEDED",
        "created_at": "2026-09-09T17:00:00Z",
    }
    result = cdc_monitor.incident_candidates(
        [event],
        now=datetime.fromisoformat("2026-09-09T18:00:00+00:00"),
        enabled_at=datetime.fromisoformat("2026-08-15T18:00:00+00:00"),
    )
    assert set(result) == {"overdue:2026-09"}


def test_issue_receipt_prevents_duplicate_even_after_issue_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = MagicMock(
        side_effect=[
            [[{"state": "closed", "body": "<!-- atlas-cdc-incident:job:known -->"}]],
            {"number": 123},
        ]
    )
    monkeypatch.setattr(cdc_monitor, "run_json", request)
    assert cdc_monitor.deliver_incidents({"job:known": "Known", "job:new": "New"}) == 1
    assert request.call_count == 2
    assert "atlas-cdc-incident:job:new" in request.call_args.kwargs["body"]["body"]


def test_failed_receipt_lookup_never_blindly_creates_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    request = MagicMock(side_effect=RuntimeError("unavailable"))
    monkeypatch.setattr(cdc_monitor, "run_json", request)
    with pytest.raises(RuntimeError):
        cdc_monitor.deliver_incidents({"job:new": "New"})
    assert request.call_count == 1
