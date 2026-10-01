"""January climate meaning aligned with the verified normalization, not publication.

The previous /1 draft remains immutable. These definitions neither approve a
source nor authorize consumer exposure. They describe the same bounded /2
candidate already verified by DATA #443.
"""

from __future__ import annotations

from typing import Any

METHOD = "atlas-nclimgrid-county-day/2"
SEMANTIC_VERSION = "2.0.0"
PERIOD = "2025-01-01/2025-01-31"
_QUANTITIES = {
    "prcp": "precipitation amount",
    "tmin": "daily minimum temperature",
    "tmax": "daily maximum temperature",
    "tavg": "NOAA-supplied daily average temperature",
}


def january_measure_definitions() -> list[dict[str, Any]]:
    """Return independent canonical definitions with explicit denominator meaning."""
    return [
        {
            "measure_id": f"nclimgrid_{code}_county_day",
            "indicator_id": "climate_precipitation" if code == "prcp" else "climate_temperature",
            "semantic_version": SEMANTIC_VERSION,
            "definition": (
                f"Valid-area-weighted NOAA nClimGrid-Daily scaled grid {quantity} "
                "for a canonical Atlas county using 2025 TIGER/Line geometry and a "
                "labeled 24-hour day in January 2025. Daily completeness requires "
                "valid area / monthly source-supported area >= 0.95; monthly "
                "source-supported / legal-county area is reported separately. "
                "CONUS descriptive weather context only; AK/HI are unavailable."
            ),
            "data_type": "NUMBER",
            "unit": "mm" if code == "prcp" else "degree_Celsius",
            "denominator": "NONE",
            "geography_grain": "COUNTY",
            "temporal_semantics": "PERIOD",
            "allowed_strata": [],
            "origin": "DERIVED",
            "methodology_version": METHOD,
            "allowed_value_states": ["OBSERVED", "ZERO", "MISSING", "UNAVAILABLE"],
        }
        for code, quantity in _QUANTITIES.items()
    ]
