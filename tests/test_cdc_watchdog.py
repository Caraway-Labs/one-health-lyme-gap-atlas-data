from datetime import datetime

import pytest

from lyme_gap_atlas_data.cdc_policy import overdue_metadata_period


@pytest.mark.parametrize(
    "now,last,expected",
    [
        ("2026-09-08T15:00:00+00:00", "2026-08-01T15:00:00+00:00", None),
        ("2026-09-08T15:00:01+00:00", "2026-08-01T15:00:00+00:00", "2026-09"),
        ("2026-09-09T15:00:00+00:00", "2026-09-02T15:00:00+00:00", None),
        ("2026-01-02T16:00:00+00:00", "2025-11-01T15:00:00+00:00", "2025-12"),
        ("2026-12-08T16:00:01+00:00", "2026-11-01T16:00:00+00:00", "2026-12"),
        ("2026-09-09T15:00:00+00:00", None, "2026-09"),
    ],
)
def test_overdue_month_including_grace_dst_and_year_rollover(
    now: str, last: str | None, expected: str | None
) -> None:
    assert (
        overdue_metadata_period(
            datetime.fromisoformat(now), datetime.fromisoformat(last) if last else None
        )
        == expected
    )


def test_watchdog_rejects_ambiguous_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        overdue_metadata_period(datetime(2026, 9, 9), None)
