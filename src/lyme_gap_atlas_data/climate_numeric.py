"""Decode the climate view's bounded native numeric transport columns.

DOUBLE arrives through guarded native FLOAT columns. INTEGER/DECIMAL stays in
VARIANT with exact decimal JSON parsing. Transport columns never enter API JSON.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

FIELDS = (
    "value",
    "expected_area_m2",
    "intersected_area_m2",
    "source_supported_area_m2",
    "valid_area_m2",
    "source_coverage_fraction",
    "valid_fraction_of_supported_area",
)


def decode_numeric_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """Preserve native DOUBLE, decimal precision, zero and SQL NULL."""
    output = dict(row)
    for field in FIELDS:
        stored = output.pop(f"{field}_stored_type")
        native = output.pop(f"{field}_native_double")
        raw = output[field]
        if stored == "DOUBLE":
            if type(native) is not float or not math.isfinite(native):
                raise ValueError("CLIMATE_NATIVE_DOUBLE")
            value: Any = native
        else:
            if native is not None:
                raise ValueError("CLIMATE_UNEXPECTED_NATIVE_DOUBLE")
            value = json.loads(raw, parse_float=Decimal) if isinstance(raw, str) else raw
            if stored in (None, "NULL_VALUE"):
                if raw is not None:
                    raise ValueError("CLIMATE_SQL_NULL")
                value = None
            elif stored == "INTEGER":
                if type(value) is not int:
                    raise ValueError("CLIMATE_INTEGER")
            elif stored == "DECIMAL":
                if type(value) is int:
                    value = Decimal(value)
                if not isinstance(value, Decimal) or not value.is_finite():
                    raise ValueError("CLIMATE_DECIMAL")
            else:
                raise ValueError("CLIMATE_NUMERIC_TYPE")
        output[field] = value
    return output
