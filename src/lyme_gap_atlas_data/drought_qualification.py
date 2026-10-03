"""Bounded native USDM qualification; no ingestion, publication, or county remapping."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

CLASSES = ("None", "D0", "D1", "D2", "D3", "D4")
TRANSFORMATION_VERSION = "usdm-native-categorical-qualification-v1"


@dataclass(frozen=True)
class NativeCountyWeek:
    county_fips: str
    map_date: date
    valid_end: date
    shares_percent: tuple[Decimal, ...]
    artifact_sha256: str
    # Native source geography is deliberately not represented as canonical Atlas geography.
    geography_vintage: str | None = None
    original_available_at: str | None = None
    reference_period: str | None = None

    @property
    def record_id(self) -> str:
        return f"USDM:NATIVE_COUNTY:{self.county_fips}:{self.map_date.isoformat()}"

    @property
    def record_revision(self) -> str:
        return hashlib.sha256(
            f"{self.record_id}:{self.artifact_sha256}:{TRANSFORMATION_VERSION}".encode()
        ).hexdigest()

    def require_canonical_compatibility(self) -> None:
        """The native statistics do not establish a canonical county boundary vintage."""
        raise ValueError("USDM_COUNTY_GEOGRAPHY_UNQUALIFIED")


def qualify_native_county_weeks(
    raw: bytes, *, county_fips: str, start: date, end: date
) -> tuple[NativeCountyWeek, ...]:
    """Validate an explicitly bounded native categorical percent-area CSV capture.

    Missing weeks fail qualification rather than creating zero drought. This helper
    is inactive: callers cannot use its results as canonical semantic assertions.
    """
    if (
        len(raw) > 64_000
        or len(county_fips) != 5
        or not county_fips.isascii()
        or not county_fips.isdigit()
        or start.weekday() != 1
        or end.weekday() != 1
        or not 0 <= (end - start).days <= 28
    ):
        raise ValueError("USDM_SCOPE_INVALID")
    digest = hashlib.sha256(raw).hexdigest()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    required = {
        "MapDate",
        "FIPS",
        "County",
        "State",
        "ValidStart",
        "ValidEnd",
        "StatisticFormatID",
        *CLASSES,
    }
    if set(reader.fieldnames or ()) != required or len(reader.fieldnames or ()) != len(required):
        raise ValueError("USDM_SCHEMA_DRIFT")
    rows: dict[date, NativeCountyWeek] = {}
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("USDM_SCHEMA_DRIFT")
        if row["StatisticFormatID"] != "2":
            raise ValueError("USDM_CATEGORICAL_FORMAT_REQUIRED")
        if row["FIPS"] != county_fips:
            raise ValueError("USDM_GEOGRAPHY_SCOPE_MISMATCH")
        try:
            observed = date.fromisoformat(row["ValidStart"])
            valid_end = date.fromisoformat(row["ValidEnd"])
            if observed.strftime("%Y%m%d") != row["MapDate"]:
                raise ValueError("USDM_DATE_MISMATCH")
            shares = tuple(Decimal(row[category]) for category in CLASSES)
        except (InvalidOperation, ValueError) as error:
            raise ValueError("USDM_VALUE_OR_DATE_INVALID") from error
        if (
            observed.weekday() != 1
            or not start <= observed <= end
            or valid_end != observed + timedelta(days=6)
        ):
            raise ValueError("USDM_PERIOD_INVALID")
        if any(not value.is_finite() or not 0 <= value <= 100 for value in shares):
            raise ValueError("USDM_SHARE_INVALID")
        # Six independently rounded 0.01 percent values permit at most 0.03 error.
        if abs(sum(shares, Decimal(0)) - Decimal(100)) > Decimal("0.03"):
            raise ValueError("USDM_CATEGORICAL_TOTAL_INVALID")
        if observed in rows:
            raise ValueError("USDM_DUPLICATE_WEEK")
        rows[observed] = NativeCountyWeek(county_fips, observed, valid_end, shares, digest)
    expected = {start + timedelta(days=offset) for offset in range(0, (end - start).days + 1, 7)}
    if set(rows) != expected:
        raise ValueError("USDM_MISSING_WEEK")
    return tuple(rows[key] for key in sorted(rows))
