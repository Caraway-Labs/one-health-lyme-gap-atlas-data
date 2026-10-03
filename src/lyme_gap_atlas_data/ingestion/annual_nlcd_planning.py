"""Offline Annual NLCD coverage planning; acquisition stays in the existing runtime."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace

from rasterio.io import MemoryFile  # type: ignore[import-untyped]
from shapely.geometry import box
from shapely.ops import unary_union

from ..county_analysis_geometry import CountyAnalysisGeometry, project_geometry
from .annual_nlcd import _CRS, MEASURES, PREFIX, PRODUCTS, _key, _raster_metadata
from .source_definition import validate_source_definition
from .types import AdapterKind, SourceDefinition

TARGET_YEARS = tuple(range(1985, 2026))
TIGER_BYTES = 83_989_800


def tile_prefix_inventory(prefixes: Iterable[str]) -> tuple[str, ...]:
    """Accept exact publisher prefixes, never infer IDs from index arithmetic."""
    tiles: list[str] = []
    for prefix in prefixes:
        match = re.fullmatch(rf"{PREFIX}/(h\d{{2}}v\d{{2}})/", prefix)
        if not match:
            raise ValueError("unexpected Collection 1.2 tile prefix")
        tiles.append(match[1].upper())
    if not tiles or len(tiles) != len(set(tiles)):
        raise ValueError("empty or duplicate tile inventory")
    return tuple(sorted(tiles))


@dataclass(frozen=True)
class TileGridEvidence:
    tile_id: str
    mapping_year: int
    product: str
    object_key: str
    version_id: str
    etag: str
    header_sha256: str
    bounds: tuple[float, float, float, float]

    @classmethod
    def from_header(
        cls,
        header: bytes,
        *,
        tile_id: str,
        mapping_year: int,
        product: str,
        object_key: str,
        version_id: str,
        etag: str,
    ) -> TileGridEvidence:
        """Read native grid only. A range digest is never a full-artifact digest."""
        if (
            not re.fullmatch(r"H\d{2}V\d{2}", tile_id)
            or mapping_year not in TARGET_YEARS
            or product not in PRODUCTS
            or object_key != _key(tile_id, product, mapping_year, "tif")
            or not version_id
            or version_id == "null"
            or not etag
            or not 0 < len(header) <= 65_536
        ):
            raise ValueError("unverified tile grid identity or header bound")
        with MemoryFile(header) as memory, memory.open() as dataset:
            _raster_metadata(dataset, product, fixture=False)
            native = dataset.bounds
            bounds = (
                float(native.left),
                float(native.bottom),
                float(native.right),
                float(native.top),
            )
        return cls(
            tile_id,
            mapping_year,
            product,
            object_key,
            version_id,
            etag,
            hashlib.sha256(header).hexdigest(),
            bounds,
        )


@dataclass(frozen=True)
class CountyTileCoverage:
    county_fips: str
    mapping_year: int
    required_tiles: tuple[str, ...]
    status: str
    expected_area_m2: float
    uncovered_area_m2: float
    geometry_sha256: str


def county_required_tiles(
    counties: Mapping[str, CountyAnalysisGeometry],
    *,
    year: int,
    inventory_tiles: tuple[str, ...],
    grids: Iterable[TileGridEvidence],
) -> tuple[CountyTileCoverage, ...]:
    """Require a complete reviewed grid inventory for this year before intersection."""
    if (
        year not in TARGET_YEARS
        or not inventory_tiles
        or inventory_tiles != tuple(sorted(set(inventory_tiles)))
    ):
        raise ValueError("invalid year or empty inventory")
    indexed: dict[tuple[str, str], TileGridEvidence] = {}
    for grid in grids:
        identity = (grid.tile_id, grid.product)
        if grid.mapping_year != year or identity in indexed:
            raise ValueError("cross-year or duplicate tile grid")
        indexed[identity] = grid
    expected = {(tile, product) for tile in inventory_tiles for product in PRODUCTS}
    if set(indexed) != expected:
        raise ValueError("incomplete tile/year/product grid inventory; coverage UNKNOWN")
    footprints = {}
    for tile in inventory_tiles:
        bounds = indexed[tile, "LndCov"].bounds
        if any(indexed[tile, product].bounds != bounds for product in PRODUCTS):
            raise ValueError("product grid footprint drift")
        footprints[tile] = box(*bounds)
    union = unary_union(list(footprints.values()))
    if sum(shape.area for shape in footprints.values()) - union.area > union.area * 1e-10:
        raise ValueError("overlapping tile footprints")
    results = []
    for fips, county in sorted(counties.items()):
        if fips != county.county_fips:
            raise ValueError("county identity mismatch")
        shape = project_geometry(county.geometry, county.lineage.storage_crs, _CRS.to_wkt())
        analytical = project_geometry(
            county.geometry, county.lineage.storage_crs, county.analysis_crs
        )
        required = tuple(
            tile for tile in sorted(footprints) if shape.intersection(footprints[tile]).area > 0
        )
        gap_shape = shape.difference(union)
        gap = (
            project_geometry(gap_shape, _CRS.to_wkt(), county.analysis_crs).area
            if not gap_shape.is_empty and gap_shape.area > 0
            else 0.0
        )
        status = (
            "OUT_OF_SOURCE_COVERAGE"
            if fips.startswith(("02", "15"))
            else "TILE_COVERED"
            if gap <= analytical.area * 1e-8
            else "TILE_GAP"
        )
        results.append(
            CountyTileCoverage(
                fips,
                year,
                () if status == "OUT_OF_SOURCE_COVERAGE" else required,
                status,
                analytical.area,
                gap,
                county.lineage.normalized_geometry_sha256,
            )
        )
    return tuple(results)


def bounded_definitions(
    base: SourceDefinition,
    coverage: Iterable[CountyTileCoverage],
    object_sizes: Mapping[str, int],
) -> tuple[SourceDefinition, ...]:
    """Generate reviewable definitions, without registering or executing them."""
    if base.adapter_kind is not AdapterKind.ANNUAL_NLCD or not validate_source_definition(base).ok:
        raise ValueError("invalid frozen Annual NLCD base definition")
    groups: dict[tuple[int, tuple[str, ...]], list[str]] = defaultdict(list)
    seen: set[tuple[int, str]] = set()
    for county in coverage:
        identity = (county.mapping_year, county.county_fips)
        if identity in seen or county.mapping_year not in TARGET_YEARS:
            raise ValueError("duplicate county-year or unsupported year")
        seen.add(identity)
        if county.status == "OUT_OF_SOURCE_COVERAGE":
            continue
        if county.status != "TILE_COVERED" or not 1 <= len(county.required_tiles) <= 16:
            raise ValueError("blocked county tile coverage")
        groups[county.mapping_year, county.required_tiles].append(county.county_fips)
    definitions = []
    for (year, tiles), counties in sorted(groups.items()):
        keys = [
            _key(tile, product, year, suffix)
            for tile in tiles
            for product in PRODUCTS
            for suffix in ("tif", "xml")
        ]
        sizes = [object_sizes.get(key) for key in keys]
        if any(
            size is None or isinstance(size, bool) or not 0 < size <= 128_000_000 for size in sizes
        ):
            raise ValueError("missing TIFF/XML or invalid artifact size")
        if sum(size for size in sizes if size is not None) + TIGER_BYTES > 512_000_000:
            raise ValueError("tile set exceeds existing aggregate acquisition cap")
        for offset in range(0, len(counties), 16):
            batch = sorted(counties)[offset : offset + 16]
            digest = hashlib.sha256(json.dumps(batch, separators=(",", ":")).encode()).hexdigest()[
                :16
            ]
            key = f"usgs_annual_nlcd_c1v2_{year}_batch_{digest}"
            definition = replace(
                base,
                resource_key=key,
                destination=f"RAW.{key.upper()}",
                extra={
                    **base.extra,
                    "mapping_year": year,
                    "county_fips": batch,
                    "tile_ids": list(tiles),
                },
            )
            if not validate_source_definition(definition).ok:
                raise ValueError("generated definition failed canonical validation")
            definitions.append(definition)
    return tuple(definitions)


def definition_document(definition: SourceDefinition) -> dict[str, object]:
    """Return JSON/YAML-compatible input for canonical source validate/run."""
    document = asdict(definition)
    document.update(document.pop("extra"))
    result: dict[str, object] = json.loads(json.dumps(document, default=lambda value: value.value))
    return result


def planned_footprint(
    definitions: Iterable[SourceDefinition], object_sizes: Mapping[str, int]
) -> dict[str, int]:
    """Estimate acquisition retention, including duplicate captures across county batches.

    These are logical bytes/GETs, not Snowflake compressed storage, measured
    billing, runtime or permission to execute. Revisions multiply retention.
    """
    seen: set[str] = set()
    keys_seen: set[str] = set()
    captures = retained = rows = runs = 0
    for definition in definitions:
        if (
            definition.resource_key in seen
            or definition.adapter_kind is not AdapterKind.ANNUAL_NLCD
            or not validate_source_definition(definition).ok
        ):
            raise ValueError("duplicate or invalid planned definition")
        seen.add(definition.resource_key)
        year = definition.extra["mapping_year"]
        keys = [
            _key(tile, product, year, suffix)
            for tile in definition.extra["tile_ids"]
            for product in PRODUCTS
            for suffix in ("tif", "xml")
        ]
        if any(key not in object_sizes or not 0 < object_sizes[key] <= 128_000_000 for key in keys):
            raise ValueError("missing or invalid object size")
        batch_bytes = TIGER_BYTES + sum(object_sizes[key] for key in keys)
        if batch_bytes > 512_000_000:
            raise ValueError("planned definition exceeds acquisition cap")
        keys_seen.update(keys)
        captures += len(keys) + 1
        retained += batch_bytes
        rows += len(definition.extra["county_fips"]) * len(MEASURES)
        runs += 1
    return {
        "bounded_runs": runs,
        "source_artifact_captures": captures,
        "requester_pays_get_requests": captures - runs,
        "retained_source_bytes_before_revisions": retained,
        "unique_usgs_object_keys": len(keys_seen),
        "unique_usgs_bytes": sum(object_sizes[key] for key in keys_seen),
        "normalized_rows": rows,
    }
