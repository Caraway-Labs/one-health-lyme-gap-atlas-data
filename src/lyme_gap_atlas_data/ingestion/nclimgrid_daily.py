"""NOAA nClimGrid-Daily scaled monthly grids at frozen 2025 county grain."""

from __future__ import annotations

import hashlib
import io
import math
from calendar import monthrange
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

import h5netcdf  # type: ignore[import-untyped]
import httpx
import numpy as np
from shapely.geometry import box

from ..county_analysis_geometry import (
    SELECTED_ARTIFACT_SHA256,
    WEIGHT_VERSION,
    CountyAnalysisGeometry,
    GridCell,
    grid_intersection_weights,
    load_tiger_counties,
)
from .adapters import (
    AcquireResult,
    AcquisitionArtifact,
    AcquisitionError,
    NormalizeResult,
    StreamingNormalizeResult,
)
from .checkpoints import ArtifactMemberStore, CheckpointStore
from .types import (
    AdapterKind,
    FailureCategory,
    SourceDefinition,
    Stage,
    ValidationIssue,
    ValidationResult,
)

TRANSFORM_VERSION = "atlas-nclimgrid-county-day/2"
GRID_CRS = "EPSG:4326"
MEASURES = {
    "prcp": "mm",
    "tmin": "degree_Celsius",
    "tmax": "degree_Celsius",
    "tavg": "degree_Celsius",
}
NOAA_MEMBER = "noaa-scaled-monthly-netcdf"
TIGER_MEMBER = "tiger-2025-analysis-county-zip"


@dataclass(frozen=True)
class RetainedInputs:
    noaa: bytes
    tiger: bytes
    noaa_sha256: str
    tiger_sha256: str
    noaa_artifact_id: str
    tiger_artifact_id: str
    retrieved_at: str | None = None
    upstream_last_modified: str | None = None


@dataclass(frozen=True)
class CountyWeights:
    county: CountyAnalysisGeometry
    grid_id: str
    weight_id: str
    cells: tuple[tuple[int, int, float], ...]
    county_area_m2: float
    intersected_area_m2: float


def _bounds(points: np.ndarray) -> np.ndarray:
    if len(points) < 2 or not np.all(np.diff(points) > 0):
        raise ValueError("nClimGrid coordinate must be strictly increasing")
    edges = np.empty(len(points) + 1, dtype=float)
    edges[1:-1] = (points[:-1] + points[1:]) / 2
    edges[0] = points[0] - (points[1] - points[0]) / 2
    edges[-1] = points[-1] + (points[-1] - points[-2]) / 2
    if not np.all(np.diff(edges) > 0):
        raise ValueError("nClimGrid cell bounds overlap")
    return edges


def _weights(
    county: CountyAnalysisGeometry, lat: np.ndarray, lon: np.ndarray, grid_id: str
) -> CountyWeights:
    lat_edges, lon_edges = _bounds(lat), _bounds(lon)
    west, south, east, north = county.geometry.bounds
    rows = range(
        max(0, int(np.searchsorted(lat_edges, south) - 1)),
        min(len(lat), int(np.searchsorted(lat_edges, north) + 1)),
    )
    cols = range(
        max(0, int(np.searchsorted(lon_edges, west) - 1)),
        min(len(lon), int(np.searchsorted(lon_edges, east) + 1)),
    )
    grid_cells: list[GridCell] = []
    for row in rows:
        for col in cols:
            footprint = box(lon_edges[col], lat_edges[row], lon_edges[col + 1], lat_edges[row + 1])
            grid_cells.append(GridCell(f"{row}:{col}", footprint, None))
    base = grid_intersection_weights(county, grid_cells, grid_crs=GRID_CRS)
    cells = tuple(
        (int(cell_id.split(":")[0]), int(cell_id.split(":")[1]), area)
        for cell_id, area in base.cell_areas_m2
    )
    weight_id = hashlib.sha256(
        f"{grid_id}:{county.lineage.normalized_geometry_sha256}:{county.lineage.artifact_sha256}:{WEIGHT_VERSION}".encode()
    ).hexdigest()
    return CountyWeights(
        county, grid_id, weight_id, cells, base.county_area_m2, base.intersected_area_m2
    )


def _dates(time: np.ndarray, units: str, year_month: str) -> tuple[date, ...]:
    prefix = "days since "
    if not units.startswith(prefix):
        raise ValueError("unsupported nClimGrid time unit")
    origin = date.fromisoformat(units[len(prefix) :].split(" ", 1)[0])
    result = tuple(origin + timedelta(days=int(value)) for value in time)
    if any(not float(value).is_integer() for value in time):
        raise ValueError("nClimGrid time must contain whole daily offsets")
    if not result or any(day.strftime("%Y%m") != year_month for day in result):
        raise ValueError("nClimGrid time is outside configured source month")
    if result != tuple(sorted(set(result))):
        raise ValueError("nClimGrid time must be unique and increasing")
    return result


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


class NClimGridDailyAdapter:
    kind = AdapterKind.NCLIMGRID_DAILY

    def acquire(
        self, definition: SourceDefinition, *, fixture_dir: Path | None = None
    ) -> AcquireResult:
        if fixture_dir is not None:
            noaa = (fixture_dir / "nclimgrid-scaled.nc").read_bytes()
            tiger = (fixture_dir / "tl_2025_us_county.zip").read_bytes()
            modified = None
        else:
            try:
                with httpx.Client(timeout=120, follow_redirects=True) as client:
                    response = client.get(definition.endpoint_template)
                    response.raise_for_status()
                    noaa = response.content
                    modified = response.headers.get("Last-Modified")
                    tiger_response = client.get(str(definition.extra["tiger_url"]))
                    tiger_response.raise_for_status()
                    tiger = tiger_response.content
            except httpx.HTTPError as error:
                raise AcquisitionError(
                    "nClimGrid acquisition failed", code="NCLIMGRID_ACQUIRE"
                ) from error
        if hashlib.sha256(tiger).hexdigest() != SELECTED_ARTIFACT_SHA256 and fixture_dir is None:
            raise AcquisitionError("Approved TIGER bytes changed", code="TIGER_DIGEST_MISMATCH")
        noaa_member = AcquisitionArtifact(
            NOAA_MEMBER,
            noaa,
            "application/x-netcdf",
            definition.endpoint_template,
            "SOURCE_PAYLOAD",
        )
        tiger_member = AcquisitionArtifact(
            TIGER_MEMBER,
            tiger,
            "application/zip",
            str(definition.extra["tiger_url"]),
            "ANALYSIS_REFERENCE",
        )
        return AcquireResult(
            payload=noaa,
            artifact_sha256=noaa_member.sha256,
            media_type="application/x-netcdf",
            artifacts=(noaa_member, tiger_member),
            detail={
                "upstream_last_modified": modified,
                "source_year_month": definition.extra["year_month"],
            },
        )

    def restore_artifacts(
        self, definition: SourceDefinition, run_id: str, store: ArtifactMemberStore
    ) -> RetainedInputs:
        members = {member.name: member for member in store.list_artifact_members(run_id)}
        if set(members) != {NOAA_MEMBER, TIGER_MEMBER}:
            raise ValueError("nClimGrid requires exactly the named NOAA and TIGER members")
        noaa = store.load_artifact_member(run_id, name=NOAA_MEMBER, role="SOURCE_PAYLOAD")
        tiger = store.load_artifact_member(run_id, name=TIGER_MEMBER, role="ANALYSIS_REFERENCE")
        state = cast(CheckpointStore, store).load(run_id)
        checkpoint = state.checkpoint(Stage.ACQUIRE) if state else None
        return RetainedInputs(
            noaa,
            tiger,
            members[NOAA_MEMBER].sha256,
            members[TIGER_MEMBER].sha256,
            members[NOAA_MEMBER].artifact_id,
            members[TIGER_MEMBER].artifact_id,
            checkpoint.completed_at if checkpoint else None,
            str(checkpoint.detail["upstream_last_modified"])
            if checkpoint and checkpoint.detail.get("upstream_last_modified")
            else None,
        )

    def restore_raw_payload(self, definition: SourceDefinition, raw_payload: bytes) -> Any:
        raise ValueError("nClimGrid requires both named run-pinned members")

    def validate_payload(self, definition: SourceDefinition, payload: Any) -> ValidationResult:
        try:
            inputs = self._inputs(payload)
            with h5netcdf.File(io.BytesIO(inputs.noaa), "r") as dataset:
                self._metadata(dataset, str(definition.extra["year_month"]))
            if hashlib.sha256(inputs.tiger).hexdigest() != inputs.tiger_sha256:
                raise ValueError("TIGER replay digest mismatch")
        except (OSError, KeyError, TypeError, ValueError) as error:
            return ValidationResult(
                False, [ValidationIssue("NCLIMGRID_INVALID", str(error), FailureCategory.SCHEMA)]
            )
        return ValidationResult(True)

    def normalize(self, definition: SourceDefinition, payload: Any) -> NormalizeResult:
        raise TypeError("nClimGrid requires bounded streaming normalization")

    def normalize_iter(
        self, definition: SourceDefinition, payload: Any
    ) -> StreamingNormalizeResult:
        inputs = self._inputs(payload)
        return StreamingNormalizeResult(self._records(definition, inputs), TRANSFORM_VERSION)

    @staticmethod
    def _inputs(payload: Any) -> RetainedInputs:
        if not isinstance(payload, RetainedInputs):
            raise TypeError("nClimGrid requires retained named artifacts")
        return payload

    @staticmethod
    def _metadata(
        dataset: Any, year_month: str
    ) -> tuple[np.ndarray, np.ndarray, tuple[date, ...], str]:
        lat = np.asarray(dataset.variables["lat"][:], dtype=float)
        lon = np.asarray(dataset.variables["lon"][:], dtype=float)
        time = np.asarray(dataset.variables["time"][:], dtype=float)
        if lat.ndim != 1 or lon.ndim != 1 or time.ndim != 1:
            raise ValueError("nClimGrid coordinate dimensionality changed")
        if (
            _text(dataset.variables["lat"].attrs["units"]) != "degrees_north"
            or _text(dataset.variables["lon"].attrs["units"]) != "degrees_east"
        ):
            raise ValueError("nClimGrid coordinate units changed")
        _bounds(lat)
        _bounds(lon)
        if not np.isclose(np.median(np.diff(lat)), 1 / 24, atol=1e-5) or not np.isclose(
            np.median(np.diff(lon)), 1 / 24, atol=1e-5
        ):
            raise ValueError("nClimGrid grid resolution changed")
        dates = _dates(time, _text(dataset.variables["time"].attrs["units"]), year_month)
        if _text(dataset.variables["time"].attrs.get("calendar", "")) != "gregorian":
            raise ValueError("nClimGrid calendar changed")
        version = _text(dataset.attrs.get("product_version", ""))
        if not version.startswith("v1-0-0"):
            raise ValueError("nClimGrid product version is not v1.0.0")
        for measure, unit in MEASURES.items():
            variable = dataset.variables[measure]
            if tuple(variable.dimensions) != ("time", "lat", "lon") or tuple(variable.shape) != (
                len(time),
                len(lat),
                len(lon),
            ):
                raise ValueError(f"{measure} dimensions changed")
            native_unit = _text(variable.attrs["units"])
            if native_unit != ("millimeter" if measure == "prcp" else unit):
                raise ValueError(f"{measure} unit changed: {native_unit}")
            if "scale_factor" in variable.attrs or "add_offset" in variable.attrs:
                raise ValueError(f"{measure} packing changed")
        grid_id = hashlib.sha256(lat.tobytes() + lon.tobytes() + GRID_CRS.encode()).hexdigest()
        return lat, lon, dates, grid_id

    def _records(
        self, definition: SourceDefinition, inputs: RetainedInputs
    ) -> Iterator[dict[str, object]]:
        canonical = (
            files("lyme_gap_atlas_data")
            .joinpath("data/canonical-county-fips-2022.txt")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        counties = load_tiger_counties(
            inputs.tiger, canonical, expected_artifact_sha256=inputs.tiger_sha256
        )
        with h5netcdf.File(io.BytesIO(inputs.noaa), "r") as dataset:
            lat, lon, days, grid_id = self._metadata(dataset, str(definition.extra["year_month"]))
            year_month = str(definition.extra["year_month"])
            month_start = date(int(year_month[:4]), int(year_month[4:]), 1)
            expected_days = tuple(
                month_start + timedelta(days=offset)
                for offset in range(monthrange(month_start.year, month_start.month)[1])
            )
            day_positions = {day: index for index, day in enumerate(days)}
            # The grid rectangle includes water cells with NOAA fill values. Use
            # evidence from the whole retained month and all four variables to
            # distinguish source support from a missing value on one day.
            source_support = np.zeros((len(lat), len(lon)), dtype=bool)
            for source_variable in MEASURES:
                monthly_variable = dataset.variables[source_variable]
                for position in range(len(days)):
                    monthly_values = np.asarray(monthly_variable[position, :, :], dtype=float)
                    monthly_fill = monthly_variable.attrs.get("_FillValue")
                    source_support |= np.isfinite(monthly_values) & (
                        monthly_values != float(monthly_fill)
                        if monthly_fill is not None and not math.isnan(float(monthly_fill))
                        else True
                    )
            weights = {
                fips: _weights(county, lat, lon, grid_id)
                for fips, county in counties.items()
                if not fips.startswith(("02", "15"))
            }
            supported_areas = {
                fips: math.fsum(area for row, col, area in weight.cells if source_support[row, col])
                for fips, weight in weights.items()
            }
            for day in expected_days:
                day_index = day_positions.get(day)
                for measure, unit in MEASURES.items():
                    variable = dataset.variables[measure]
                    values = (
                        np.asarray(variable[day_index, :, :], dtype=float)
                        if day_index is not None
                        else None
                    )
                    if values is not None:
                        fill = variable.attrs.get("_FillValue")
                        if fill is not None and not math.isnan(float(fill)):
                            values[values == float(fill)] = np.nan
                        valid_values = values[np.isfinite(values)]
                        if valid_values.size and (
                            np.any(valid_values < float(variable.attrs.get("valid_min", -math.inf)))
                            or np.any(
                                valid_values > float(variable.attrs.get("valid_max", math.inf))
                            )
                        ):
                            raise ValueError(f"{measure} violates NOAA valid range")
                    for fips, county in counties.items():
                        logical_id = (
                            f"{definition.resource_key}:{fips}:{day.isoformat()}:{measure.upper()}"
                        )
                        if fips.startswith(("02", "15")):
                            status, value, valid, expected, intersected = (
                                "OUT_OF_SOURCE_COVERAGE",
                                None,
                                0.0,
                                None,
                                None,
                            )
                        else:
                            weight = weights[fips]
                            valid_cells = (
                                [
                                    (area, values[row, col])
                                    for row, col, area in weight.cells
                                    if math.isfinite(float(values[row, col]))
                                ]
                                if values is not None
                                else []
                            )
                            valid = math.fsum(area for area, _ in valid_cells)
                            expected, intersected = (
                                weight.county_area_m2,
                                weight.intersected_area_m2,
                            )
                            supported = supported_areas[fips]
                            if valid == 0:
                                status, value = "SOURCE_MISSING", None
                            elif valid / supported + 1e-12 < 0.95:
                                status, value = "PARTIAL_COVERAGE", None
                            else:
                                status = "COMPLETE"
                                value = (
                                    math.fsum(
                                        area * float(cell_value) for area, cell_value in valid_cells
                                    )
                                    / valid
                                )
                        yield {
                            "id": logical_id,
                            "source_id": definition.source_id,
                            "dataset_id": definition.dataset_id,
                            "source_definition_version": definition.definition_version,
                            "geography_semantics": definition.geography_semantics,
                            "temporal_semantics": definition.temporal_semantics,
                            "record": {
                                "id": logical_id,
                                "county_fips": fips,
                                "observation_date": day.isoformat(),
                                "source_year_month": definition.extra["year_month"],
                                "source_time_present": day_index is not None,
                                "measure": measure.upper(),
                                "source_variable": measure,
                                "value": value,
                                "unit": unit,
                                "source_unit": _text(variable.attrs["units"]),
                                "coverage_status": status,
                                "valid_area_m2": valid,
                                "expected_area_m2": expected,
                                "intersected_area_m2": intersected,
                                "source_supported_area_m2": supported if fips in weights else None,
                                "source_coverage_fraction": (
                                    supported / expected if expected is not None else None
                                ),
                                "valid_fraction_of_supported_area": (
                                    valid / supported if fips in weights and supported else None
                                ),
                                "grid_id": grid_id,
                                "grid_crs": GRID_CRS,
                                "weight_id": weights[fips].weight_id if fips in weights else None,
                                "weight_version": WEIGHT_VERSION,
                                "geometry_version": county.lineage.transform_version,
                                "geometry_digest": county.lineage.normalized_geometry_sha256,
                                "tiger_sha256": inputs.tiger_sha256,
                                "tiger_member_name": TIGER_MEMBER,
                                "noaa_sha256": inputs.noaa_sha256,
                                "noaa_member_name": NOAA_MEMBER,
                                "noaa_product_version": _text(dataset.attrs["product_version"]),
                                "upstream_date_modified": _text(
                                    dataset.attrs.get("date_modified", "")
                                ),
                                "transformation_version": TRANSFORM_VERSION,
                                "trace_state": "NOT_REPRESENTED" if measure == "prcp" else None,
                            },
                        }
