"""Numeric interpretation of the retained CDC/ATSDR 2022 county SVI fields.

RAW records remain source-faithful. This projection does not recompute ranks,
select a new vintage, impute values, or establish scientific eligibility.
"""

from __future__ import annotations

import math
from typing import Any

TRANSFORMATION_VERSION = "svi_numeric_projection_v2"
_MAXIMUM = {"E_TOTPOP": None, "RPL_THEMES": 1, "EPL_UNINSUR": 1, "EP_UNINSUR": 100}


def numeric_value(field: str, raw: Any) -> float | None:
    """Map publisher -999 to missing; reject values outside the native domain."""
    maximum = _MAXIMUM[field]
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        raise ValueError(f"SVI {field} must be numeric, not boolean")
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"SVI {field} must be numeric") from error
    if value == -999:
        return None
    if not math.isfinite(value) or value < 0 or (maximum is not None and value > maximum):
        raise ValueError(f"SVI {field} outside publisher value domain")
    return value
