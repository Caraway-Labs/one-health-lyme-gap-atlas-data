"""Deterministic monthly definitions and NOAA inventory for nClimGrid v1.

This module prepares one ordinary SourceDefinition at a time. It does not
acquire artifacts or implement a second ingestion runtime.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from calendar import monthrange
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

import h5netcdf  # type: ignore[import-untyped]
import numpy as np
import yaml  # type: ignore[import-untyped]

FIRST_MONTH = "195101"
LAST_MONTH = "202608"
BASE_MONTH = "202501"
SOURCE_ROOT = "https://www.ncei.noaa.gov/data/nclimgrid-daily/access/grids"
EXPECTED_GRID_ID = "f6759ec770aa79789cb9e38f170bdb7b820d1c19e89eb734fc66720c392f0c95"
WINDOW_VERSION = "nclimgrid-longitudinal-window-v1"
BASE_TEMPLATE_SHA256 = "17bcf70171eee5fddcc9684f2174f4f2d460bc95e74846fadb14ac4b5de16c3d"
_MONTH = re.compile(r"\d{6}\Z")
_SCALED_HREF = re.compile(r'href="(?:\./)?(ncdd-(\d{6})-grd-scaled\.nc)"')


def _month(value: str) -> date:
    if not _MONTH.fullmatch(value) or not 1 <= int(value[4:]) <= 12:
        raise ValueError("Expected a valid YYYYMM month")
    return date(int(value[:4]), int(value[4:]), 1)


def months(start: str = FIRST_MONTH, end: str = LAST_MONTH) -> tuple[str, ...]:
    """Return the frozen, inclusive historical window in calendar order."""
    first, last = _month(start), _month(end)
    if first < _month(FIRST_MONTH) or last > _month(LAST_MONTH) or first > last:
        raise ValueError("Requested months are outside the frozen nClimGrid window")
    result: list[str] = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        result.append(f"{year:04d}{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return tuple(result)


def expected_days(year_month: str) -> int:
    """The calendar-day denominator for one source month."""
    _month(year_month)
    return monthrange(int(year_month[:4]), int(year_month[4:]))[1]


def batch_definition_specs(value: str, *, maximum: int = 12) -> tuple[str, ...]:
    """Resolve only a bounded range of generated nClimGrid definitions."""
    if not 1 <= maximum <= 12:
        raise ValueError("Batch bound must be between one and twelve")
    if not re.fullmatch(r"nclimgrid:\d{6}\.\.\d{6}", value):
        raise ValueError("nClimGrid batch requires nclimgrid:YYYYMM..YYYYMM")
    start, end = value.removeprefix("nclimgrid:").split("..", 1)
    specs = tuple(f"nclimgrid:{month}" for month in months(start, end))
    if not specs or len(specs) > maximum or len(specs) != len(set(specs)):
        raise ValueError("Batch must contain one to twelve unique definitions")
    return specs


def definition_mapping(year_month: str) -> dict[str, object]:
    """Generate the existing #198 definition with only month-specific pins changed."""
    if year_month not in months():
        raise ValueError("Month is outside the frozen nClimGrid window")
    root = Path(__file__).resolve().parents[3]
    template = root / "config/sources/noaa_nclimgrid_daily_202501.yml"
    document = yaml.safe_load(template.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("year_month") != BASE_MONTH:
        raise ValueError("The committed #198 source template has changed")
    template_digest = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if template_digest != BASE_TEMPLATE_SHA256:
        raise ValueError("The reviewed #198 template digest changed")
    result: dict[str, object] = dict(document)
    result["resource_key"] = f"noaa_nclimgrid_daily_{year_month}"
    result["endpoint_template"] = f"{SOURCE_ROOT}/{year_month[:4]}/ncdd-{year_month}-grd-scaled.nc"
    result["destination"] = f"RAW.NOAA_NCLIMGRID_DAILY_{year_month}"
    result["year_month"] = year_month
    result["expected_grid_id"] = EXPECTED_GRID_ID
    result["longitudinal_window_version"] = WINDOW_VERSION
    result["source_definition_sha256"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return result


def scaled_inventory(start: str = FIRST_MONTH, end: str = LAST_MONTH) -> dict[str, object]:
    """Inspect NOAA directory hrefs, one bounded metadata request per year."""
    expected = months(start, end)
    found: set[str] = set()
    duplicate: set[str] = set()
    unexpected: set[str] = set()
    for year in range(int(start[:4]), int(end[:4]) + 1):
        url = f"{SOURCE_ROOT}/{year}/"
        request = Request(url, headers={"User-Agent": "Atlas-nClimGrid-inventory/1"})
        with urlopen(request, timeout=30) as response:
            listing = response.read(2_000_001)
        if len(listing) > 2_000_000:
            raise ValueError(f"NOAA year index exceeds byte bound: {year}")
        for filename, file_month in _SCALED_HREF.findall(listing.decode("utf-8")):
            if filename != f"ncdd-{file_month}-grd-scaled.nc" or file_month[:4] != str(year):
                unexpected.add(filename)
            elif file_month in found:
                duplicate.add(file_month)
            else:
                found.add(file_month)
    selected = set(expected)
    return {
        "source": SOURCE_ROOT,
        "product": "NOAA nClimGrid-Daily v1.0.0 scaled monthly NetCDF",
        "start_month": start,
        "end_month": end,
        "expected_count": len(expected),
        "available_months": sorted(found & selected),
        "missing_months": sorted(selected - found),
        "duplicate_months": sorted(duplicate & selected),
        "unexpected_entries": sorted(unexpected),
    }


def inspect_scaled_artifact(path: Path, year_month: str) -> dict[str, object]:
    """Inspect one local NOAA artifact without treating it as a governed capture."""
    from .nclimgrid_daily import MEASURES, NClimGridDailyAdapter

    definition_mapping(year_month)  # Enforce the frozen selection before reading.
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with h5netcdf.File(path, "r") as dataset:
        lat, lon, dates, grid_id = NClimGridDailyAdapter._metadata(
            dataset, year_month, expected_grid_id=EXPECTED_GRID_ID
        )
        support = np.zeros((len(lat), len(lon)), dtype=bool)
        variables: dict[str, dict[str, object]] = {}
        for name in MEASURES:
            variable = dataset.variables[name]
            fill = float(variable.attrs["_FillValue"])
            variables[name] = {
                "dimensions": list(variable.dimensions),
                "unit": str(variable.attrs["units"]),
                "fill": "NaN" if math.isnan(fill) else fill,
            }
            for position in range(len(dates)):
                values = np.asarray(variable[position, :, :], dtype=float)
                support |= np.isfinite(values) & (values != fill if not math.isnan(fill) else True)
        return {
            "evidence_level": "LOCAL_SOURCE_BACKED_ARTIFACT_INSPECTION",
            "month": year_month,
            "source_uri": f"{SOURCE_ROOT}/{year_month[:4]}/ncdd-{year_month}-grd-scaled.nc",
            "sha256": digest,
            "bytes": path.stat().st_size,
            "product_version": str(dataset.attrs["product_version"]),
            "upstream_date_modified": str(dataset.attrs.get("date_modified", "")),
            "original_publication_time": None,
            "grid_id": grid_id,
            "grid_shape": [len(lat), len(lon)],
            "first_day": dates[0].isoformat(),
            "last_day": dates[-1].isoformat(),
            "source_day_count": len(dates),
            "expected_day_count": expected_days(year_month),
            "source_supported_grid_cells": int(np.count_nonzero(support)),
            "source_support_mask_sha256": hashlib.sha256(support.tobytes()).hexdigest(),
            "variables": variables,
        }
