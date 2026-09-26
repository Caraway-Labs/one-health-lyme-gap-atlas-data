"""Frozen TIGER/Line county geometry and deterministic grid area weights (#424)."""

from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

import shapefile  # type: ignore[import-untyped]
from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

SOURCE_PRODUCT = "TIGER/Line County and Equivalent Entity National Shapefile (Current)"
SOURCE_VINTAGE = "2025"
SOURCE_FILE = "tl_2025_us_county.zip"
SOURCE_URL = f"https://www2.census.gov/geo/tiger/TIGER2025/COUNTY/{SOURCE_FILE}"
SELECTED_ARTIFACT_SHA256 = "9c6e9d9076abce2670d1de255de3710c35ecca00a7005d88e012dec52d95f763"
SOURCE_CRS = "EPSG:4269"  # NAD83 geographic, per the Census .prj
STORAGE_CRS = SOURCE_CRS
TRANSFORM_VERSION = "atlas-county-analysis-geometry/1"
WEIGHT_VERSION = "atlas-grid-county-area-weight/1"
EXPECTED_COUNTIES = 3144
_EXCLUDED_STATEFP = frozenset({"60", "66", "69", "72", "78"})
_INCLUDED_STATEFP = frozenset(
    {f"{number:02d}" for number in range(1, 57)} - {"03", "07", "14", "43", "52"}
)


class CountyGeometryError(ValueError):
    """The frozen source, geometry, or canonical identity failed closed."""


@dataclass(frozen=True)
class GeometryLineage:
    source_product: str
    source_vintage: str
    artifact_sha256: str
    source_geoid: str
    source_geometry_sha256: str
    normalized_geometry_sha256: str
    transform_version: str
    source_crs: str
    storage_crs: str


@dataclass(frozen=True)
class CountyAnalysisGeometry:
    county_fips: str
    geometry: BaseGeometry
    analysis_crs: str
    lineage: GeometryLineage


@dataclass(frozen=True)
class GridCell:
    cell_id: str
    geometry: BaseGeometry
    value: float | None


@dataclass(frozen=True)
class WeightedResult:
    county_fips: str
    value: float | None
    unit: str
    valid_area_m2: float
    intersected_area_m2: float
    county_area_m2: float
    completeness: float
    status: str
    geometry_version: str
    artifact_sha256: str
    weight_version: str = WEIGHT_VERSION


@dataclass(frozen=True)
class GridIntersectionWeights:
    """Reusable #424 projected intersection areas for one county and grid."""

    county_fips: str
    cell_areas_m2: tuple[tuple[str, float], ...]
    intersected_area_m2: float
    county_area_m2: float
    geometry_version: str
    artifact_sha256: str
    weight_version: str = WEIGHT_VERSION


def analysis_crs(county_fips: str) -> str:
    """Choose a fixed equal-area projection for the county's state."""
    if county_fips.startswith("02"):
        return "EPSG:3338"  # Alaska Albers
    if county_fips.startswith("15"):
        return "EPSG:2782"  # Hawaii Albers
    return "EPSG:5070"  # NAD83 / Conus Albers


@lru_cache(maxsize=8)
def _coordinate_transformer(source_crs: str, target_crs: str) -> Transformer:
    """Reuse immutable projection setup across grid cells in one process."""
    return Transformer.from_crs(CRS.from_user_input(source_crs), target_crs, always_xy=True)


def project_geometry(geometry: BaseGeometry, source_crs: str, target_crs: str) -> BaseGeometry:
    """Project with fixed XY axis order; never simplify or repair topology."""
    transformer = _coordinate_transformer(source_crs, target_crs)
    projected = transform(transformer.transform, geometry)
    if projected.is_empty or not projected.is_valid:
        raise CountyGeometryError("projection produced empty or invalid geometry")
    return projected


def _geometry_digest(geometry: BaseGeometry) -> str:
    return hashlib.sha256(geometry.wkb).hexdigest()


def _validate_polygon(geometry: BaseGeometry, geoid: str) -> None:
    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise CountyGeometryError(f"{geoid}: expected Polygon or MultiPolygon")
    if geometry.is_empty or not geometry.is_valid:
        raise CountyGeometryError(f"{geoid}: source geometry is empty or invalid")
    if geometry.area <= 0:
        raise CountyGeometryError(f"{geoid}: source geometry has no area")


def load_tiger_counties(
    artifact: bytes,
    canonical_fips: Iterable[str],
    *,
    expected_artifact_sha256: str = SELECTED_ARTIFACT_SHA256,
) -> dict[str, CountyAnalysisGeometry]:
    """Validate the pinned Census archive against the unchanged canonical FIPS set.

    The caller must supply an immutable artifact and an independently sourced
    canonical identity set. This function performs no acquisition or database write.
    """
    digest = hashlib.sha256(artifact).hexdigest()
    if digest != expected_artifact_sha256:
        raise CountyGeometryError("TIGER artifact SHA-256 differs from pinned digest")
    canonical = set(canonical_fips)
    if len(canonical) != EXPECTED_COUNTIES or any(
        len(value) != 5 or not value.isdigit() for value in canonical
    ):
        raise CountyGeometryError(
            "canonical county identity must have 3,144 unique five-digit FIPS"
        )
    with zipfile.ZipFile(io.BytesIO(artifact)) as archive:
        names = set(archive.namelist())
        required = {f"tl_2025_us_county.{suffix}" for suffix in ("shp", "shx", "dbf", "prj")}
        if not required <= names:
            raise CountyGeometryError("TIGER archive is missing required county shapefile members")
        prj = archive.read("tl_2025_us_county.prj").decode("ascii")
        if CRS.from_wkt(prj).to_epsg() != 4269:
            raise CountyGeometryError("TIGER source CRS is not EPSG:4269")
        reader = shapefile.Reader(
            shp=io.BytesIO(archive.read("tl_2025_us_county.shp")),
            shx=io.BytesIO(archive.read("tl_2025_us_county.shx")),
            dbf=io.BytesIO(archive.read("tl_2025_us_county.dbf")),
        )
        fields = [field[0] for field in reader.fields[1:]]
        if not {"GEOID", "STATEFP", "COUNTYFP", "MTFCC"} <= set(fields):
            raise CountyGeometryError("TIGER county identity fields are missing")
        output: dict[str, CountyAnalysisGeometry] = {}
        for record in reader.iterShapeRecords():
            row = dict(zip(fields, record.record, strict=True))
            state = str(row["STATEFP"])
            if state in _EXCLUDED_STATEFP:
                continue
            if state not in _INCLUDED_STATEFP:
                raise CountyGeometryError(f"unexpected TIGER state code {state}")
            geoid = str(row["GEOID"])
            if geoid != state + str(row["COUNTYFP"]) or row["MTFCC"] != "G4020":
                raise CountyGeometryError(f"{geoid}: county identifier or feature class disagrees")
            if geoid in output:
                raise CountyGeometryError(f"duplicate TIGER county {geoid}")
            geometry = shape(record.shape.__geo_interface__)
            _validate_polygon(geometry, geoid)
            # A shapefile conversion to OGC polygon encoding is a normalization,
            # not a simplification or topology repair. Both digests are retained.
            source_digest = hashlib.sha256(
                json.dumps(
                    record.shape.__geo_interface__, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            lineage = GeometryLineage(
                source_product=SOURCE_PRODUCT,
                source_vintage=SOURCE_VINTAGE,
                artifact_sha256=digest,
                source_geoid=geoid,
                source_geometry_sha256=source_digest,
                normalized_geometry_sha256=_geometry_digest(geometry),
                transform_version=TRANSFORM_VERSION,
                source_crs=SOURCE_CRS,
                storage_crs=STORAGE_CRS,
            )
            output[geoid] = CountyAnalysisGeometry(geoid, geometry, analysis_crs(geoid), lineage)
    if set(output) != canonical:
        missing = sorted(canonical - set(output))
        extra = sorted(set(output) - canonical)
        raise CountyGeometryError(
            f"county FIPS mismatch: canonical_only={missing}; TIGER_only={extra}"
        )
    return dict(sorted(output.items()))


def area_weighted_mean(
    county: CountyAnalysisGeometry,
    cells: Iterable[GridCell],
    *,
    grid_crs: str,
    unit: str,
    minimum_completeness: float,
) -> WeightedResult:
    """Intersect native cell footprints with one county in its equal-area CRS.

    Cells must be disjoint, one value per cell, and represent the full intended
    grid coverage. Missing values contribute coverage area but not the mean.
    """
    if not 0 <= minimum_completeness <= 1 or not math.isfinite(minimum_completeness):
        raise CountyGeometryError("minimum completeness must be finite in [0, 1]")
    if not unit.strip():
        raise CountyGeometryError("source unit is required")
    ordered = sorted(cells, key=lambda cell: cell.cell_id)
    weights = grid_intersection_weights(county, ordered, grid_crs=grid_crs)
    values = {cell.cell_id: cell.value for cell in ordered}
    valid_areas: list[float] = []
    products: list[float] = []
    for cell_id, area in weights.cell_areas_m2:
        value = values[cell_id]
        if value is None:
            continue
        if not math.isfinite(value):
            raise CountyGeometryError("non-finite cell value; use None for nodata")
        valid_areas.append(area)
        products.append(area * value)
    intersected_area = weights.intersected_area_m2
    valid_area = math.fsum(valid_areas)
    completeness = min(valid_area / weights.county_area_m2, 1.0)
    if not weights.cell_areas_m2:
        status, value = "NO_INTERSECTING_CELLS", None
    elif not valid_areas:
        status, value = "NO_VALID_CELLS", None
    elif completeness + 1e-12 < minimum_completeness:
        status, value = "INCOMPLETE", None
    else:
        status, value = "COMPLETE", math.fsum(products) / valid_area
    return WeightedResult(
        county_fips=county.county_fips,
        value=value,
        unit=unit,
        valid_area_m2=valid_area,
        intersected_area_m2=intersected_area,
        county_area_m2=weights.county_area_m2,
        completeness=completeness,
        status=status,
        geometry_version=county.lineage.transform_version,
        artifact_sha256=county.lineage.artifact_sha256,
    )


def grid_intersection_weights(
    county: CountyAnalysisGeometry,
    cells: Iterable[GridCell],
    *,
    grid_crs: str,
) -> GridIntersectionWeights:
    """Project and intersect source cells once, preserving the #424 area rules."""
    polygon = project_geometry(county.geometry, county.lineage.storage_crs, county.analysis_crs)
    county_area = polygon.area
    if county_area <= 0:
        raise CountyGeometryError("projected county has no area")
    ordered = sorted(cells, key=lambda cell: cell.cell_id)
    if len({cell.cell_id for cell in ordered}) != len(ordered):
        raise CountyGeometryError("duplicate grid cell ID")
    projected_cells: list[tuple[GridCell, BaseGeometry]] = []
    for cell in ordered:
        if not cell.cell_id or cell.geometry.is_empty or not cell.geometry.is_valid:
            raise CountyGeometryError("grid cell has invalid identity or geometry")
        projected_cells.append(
            (cell, project_geometry(cell.geometry, grid_crs, county.analysis_crs))
        )
    footprint_area = math.fsum(geometry.area for _, geometry in projected_cells)
    union_area = unary_union([geometry for _, geometry in projected_cells]).area
    if footprint_area - union_area > max(union_area, 1.0) * 1e-10:
        raise CountyGeometryError("grid cell footprints overlap")
    areas = tuple(
        (cell.cell_id, area)
        for cell, footprint in projected_cells
        if (area := polygon.intersection(footprint).area) > 0
    )
    intersected_area = math.fsum(area for _, area in areas)
    if intersected_area > county_area * (1 + 1e-8):
        raise CountyGeometryError("grid intersection area exceeds county area")
    return GridIntersectionWeights(
        county.county_fips,
        areas,
        intersected_area,
        county_area,
        county.lineage.transform_version,
        county.lineage.artifact_sha256,
    )
