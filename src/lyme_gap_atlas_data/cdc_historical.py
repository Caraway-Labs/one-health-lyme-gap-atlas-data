"""Fail-closed admission checks for historical CDC evidence candidates."""

from __future__ import annotations

from typing import Any

RESOURCE_KEY = "cdc_lyme_qtbi_xd4i"
DATASET_ID = "qtbi-xd4i"
REQUIRED_COLUMNS = {"year", "state", "fips", "case_status", "sex", "age_cat_yrs", "frequency"}


def validate_historical_evidence(
    metadata: Any, sample: Any, *, environment: str, sample_limit: int
) -> dict[str, object]:
    """Validate bounded evidence without coercing source values or asserting a key.

    Schema fields can be present even when individual records omit suppressed or
    unknown values. Missing fields in a row must not be treated as numeric zero.
    """
    if environment not in {"dev", "prod"}:
        raise ValueError("Historical CDC onboarding requires isolated DEV or PROD")
    if not 1 <= sample_limit <= 100:
        raise ValueError("Historical CDC sample limit must be between 1 and 100")
    if not isinstance(metadata, dict) or metadata.get("id") != DATASET_ID:
        raise ValueError("Unexpected historical CDC publisher identity")
    columns = metadata.get("columns")
    if not isinstance(columns, list):
        raise ValueError("Historical CDC metadata requires a column schema")
    fields = {column.get("fieldName") for column in columns if isinstance(column, dict)}
    if not REQUIRED_COLUMNS.issubset(fields):
        raise ValueError("Historical CDC schema is missing required columns")
    if not isinstance(sample, list) or not 1 <= len(sample) <= sample_limit:
        raise ValueError("Historical CDC sample is empty, malformed, or exceeds its bound")
    for row in sample:
        if not isinstance(row, dict):
            raise ValueError("Historical CDC sample contains a malformed record")
        year = str(row.get("year", ""))
        if not year.isascii() or not year.isdigit() or not 2008 <= int(year) <= 2021:
            raise ValueError("Historical CDC sample crosses its surveillance-era boundary")
    return {
        "resource_key": RESOURCE_KEY,
        "surveillance_era": "2008-2021",
        "sample_rows": len(sample),
        "full_dataset_validated": False,
        "publisher_record_identity_verified": False,
    }
