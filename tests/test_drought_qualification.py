"""DATA197-owned DATA202 native quality and fail-closed compatibility cases."""

import csv
import hashlib
import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from lyme_gap_atlas_data.drought_qualification import qualify_native_county_weeks

FIXTURE = Path(__file__).parent / "fixtures/drought/usdm-48081-20250107-categorical.csv"
DAY = date(2025, 1, 7)


def qualify(raw: bytes):
    return qualify_native_county_weeks(raw, county_fips="48081", start=DAY, end=DAY)


def altered(**changes: str) -> bytes:
    reader = csv.DictReader(io.StringIO(FIXTURE.read_text(encoding="utf-8-sig")))
    row = next(reader)
    row.update(changes)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=reader.fieldnames)
    writer.writeheader()
    writer.writerow(row)
    return output.getvalue().encode()


def test_authoritative_capture_provenance_and_reference_period():
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "e40d5bc6b654b827cc884bf375ca34ea58ffa65b088275de926a2cd97cbcdca9"
    )
    (week,) = qualify(raw)
    assert week.artifact_sha256 == hashlib.sha256(raw).hexdigest()
    assert week.original_available_at is None
    assert week.reference_period is None  # USDM has no SPEI calibration period.
    assert week.geography_vintage is None
    assert abs(sum(week.shares_percent) - 100) <= Decimal("0.03")
    with pytest.raises(ValueError, match="GEOGRAPHY_UNQUALIFIED"):
        week.require_canonical_compatibility()


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"StatisticFormatID": "1"}, "CATEGORICAL_FORMAT_REQUIRED"),
        ({"FIPS": "01001"}, "GEOGRAPHY_SCOPE_MISMATCH"),
        ({"D1": ""}, "VALUE_OR_DATE_INVALID"),
        ({"D1": "NaN"}, "SHARE_INVALID"),
        ({"D1": "-1"}, "SHARE_INVALID"),
        ({"D1": "101"}, "SHARE_INVALID"),
        ({"MapDate": "20250108"}, "VALUE_OR_DATE_INVALID"),
        ({"ValidEnd": "2025-01-14"}, "PERIOD_INVALID"),
        ({"None": "100", "D0": "100"}, "CATEGORICAL_TOTAL_INVALID"),
    ],
)
def test_quality_drift_blocks(changes, reason):
    with pytest.raises(ValueError, match=reason):
        qualify(altered(**changes))


def test_missing_week_never_becomes_zero_or_episode_bridge():
    with pytest.raises(ValueError, match="MISSING_WEEK"):
        qualify_native_county_weeks(
            FIXTURE.read_bytes(), county_fips="48081", start=DAY, end=date(2025, 1, 14)
        )


def test_zero_none_and_partial_county_classes_remain_distinct():
    (week,) = qualify(
        altered(**{"None": "20", "D0": "10", "D1": "30", "D2": "40", "D3": "0", "D4": "0"})
    )
    assert week.shares_percent == tuple(map(Decimal, ("20", "10", "30", "40", "0", "0")))


def test_content_revision_preserves_logical_identity():
    original = {"None": "100", "D0": "0", "D1": "0", "D2": "0", "D3": "0", "D4": "0"}
    (first,) = qualify(altered(**original))
    (revised,) = qualify(altered(**(original | {"None": "99", "D0": "1"})))
    assert first.record_id == revised.record_id
    assert first.record_revision != revised.record_revision
    assert first == qualify(altered(**original))[0]


def test_duplicate_week_blocks():
    raw = FIXTURE.read_bytes()
    with pytest.raises(ValueError, match="DUPLICATE_WEEK"):
        qualify(raw + raw.splitlines(keepends=True)[1])


def test_schema_and_unbounded_scope_block():
    with pytest.raises(ValueError, match="SCHEMA_DRIFT"):
        qualify(FIXTURE.read_bytes().replace(b"None,", b"Population,"))
    with pytest.raises(ValueError, match="SCOPE_INVALID"):
        qualify_native_county_weeks(
            FIXTURE.read_bytes(), county_fips="48081", start=DAY, end=date(2025, 2, 11)
        )


def test_duplicate_header_and_oversized_capture_block():
    raw = FIXTURE.read_bytes()
    with pytest.raises(ValueError, match="SCHEMA_DRIFT"):
        qualify(raw.replace(b"StatisticFormatID\r", b"StatisticFormatID,D1\r"))
    with pytest.raises(ValueError, match="SCOPE_INVALID"):
        qualify(raw + b" " * 64_000)


def test_complete_dry_week_is_valid_but_empty_capture_is_missing():
    original = {"None": "100", "D0": "0", "D1": "0", "D2": "0", "D3": "0", "D4": "0"}
    (week,) = qualify(altered(**original))
    assert week.shares_percent[0] == Decimal(100)
    with pytest.raises(ValueError, match="MISSING_WEEK"):
        qualify(FIXTURE.read_bytes().splitlines(keepends=True)[0])
