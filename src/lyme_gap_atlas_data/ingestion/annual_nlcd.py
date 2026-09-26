"""Bounded, source-faithful Annual NLCD Collection 1.2 county-year adapter."""

from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

import boto3  # type: ignore[import-untyped]
import httpx
import numpy as np
from pyproj import CRS, Transformer
from rasterio.features import rasterize  # type: ignore[import-untyped]
from rasterio.io import MemoryFile  # type: ignore[import-untyped]
from rasterio.windows import Window, from_bounds  # type: ignore[import-untyped]
from rasterio.windows import transform as window_transform
from shapely.geometry import box

from ..county_analysis_geometry import (
    SELECTED_ARTIFACT_SHA256,
    SOURCE_URL,
    WEIGHT_VERSION,
    CountyAnalysisGeometry,
    GridCell,
    grid_intersection_weights,
    load_tiger_counties,
    project_geometry,
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

BUCKET = "usgs-landcover"
PREFIX = "annual-nlcd/c1/v2/cu/tile"
ENDPOINT = f"https://{BUCKET}.s3.us-west-2.amazonaws.com/{PREFIX}/"
COLLECTION = "Annual NLCD Collection 1.2"
TRANSFORM_VERSION = "atlas-annual-nlcd-county-year/1"
TIGER_MEMBER = "tiger-2025-analysis-county-zip"
PRODUCTS = ("LndCov", "FctImp", "LndChg")
PRODUCT_TITLES = {
    "LndCov": "Land Cover",
    "FctImp": "Fractional Impervious Surface",
    "LndChg": "Land Cover Change",
}
NODATA = {"LndCov": 250, "FctImp": 250, "LndChg": 9999}
DTYPE = {"LndCov": "uint8", "FctImp": "uint8", "LndChg": "uint16"}
CLASSES = frozenset({11, 12, 21, 22, 23, 24, 31, 41, 42, 43, 52, 71, 81, 82, 90, 95})
GROUPS = {
    "FOREST_AREA_SHARE": frozenset({41, 42, 43}),
    "DEVELOPED_AREA_SHARE": frozenset({21, 22, 23, 24}),
    "AGRICULTURE_AREA_SHARE": frozenset({81, 82}),
    "WETLAND_AREA_SHARE": frozenset({90, 95}),
    "OPEN_WATER_AREA_SHARE": frozenset({11}),
}
MEASURES = (*GROUPS, "MEAN_IMPERVIOUS_FRACTION", "LAND_COVER_CHANGED_AREA_SHARE")
_TILE = re.compile(r"H\d{2}V\d{2}\Z")
_CRS = CRS.from_proj4(
    "+proj=aea +lat_1=29.5 +lat_2=45.5 +lat_0=23 +lon_0=-96 +datum=WGS84 +units=m +no_defs"
)
_WINDOW = 256
_MAX_ARTIFACT_BYTES = 128_000_000
_MAX_RUN_BYTES = 512_000_000


def validate_definition(definition: SourceDefinition) -> list[ValidationIssue]:
    """Pin product, geography, and annual period without a generic config framework."""
    extra = definition.extra
    year = extra.get("mapping_year")
    tiles = extra.get("tile_ids")
    counties = extra.get("county_fips")
    issues: list[ValidationIssue] = []
    if not isinstance(year, int) or isinstance(year, bool) or not 1985 <= year <= 2025:
        issues.append(ValidationIssue("NLCD_YEAR", "Mapping year must be 1985 through 2025"))
    if (
        not isinstance(tiles, list)
        or not 1 <= len(tiles) <= 16
        or any(not isinstance(tile, str) or not _TILE.fullmatch(tile) for tile in tiles)
        or len(set(tiles)) != len(tiles)
        or tiles != sorted(tiles)
    ):
        issues.append(ValidationIssue("NLCD_TILES", "Declare 1-16 unique sorted official tile IDs"))
    if (
        not isinstance(counties, list)
        or not 1 <= len(counties) <= 16
        or any(not isinstance(fips, str) or not re.fullmatch(r"\d{5}", fips) for fips in counties)
        or len(set(counties)) != len(counties)
        or counties != sorted(counties)
    ):
        issues.append(ValidationIssue("NLCD_COUNTIES", "Declare 1-16 unique sorted county FIPS"))
    if definition.endpoint_template != ENDPOINT or extra.get("collection_version") != "C1V2":
        issues.append(
            ValidationIssue("NLCD_COLLECTION", "Exact Collection 1.2 S3 tile path is required")
        )
    if (
        extra.get("tiger_url") != SOURCE_URL
        or extra.get("tiger_sha256") != SELECTED_ARTIFACT_SHA256
    ):
        issues.append(
            ValidationIssue("TIGER_PIN", "Approved 2025 TIGER URL and digest are required")
        )
    if extra.get("minimum_valid_fraction_of_supported_area") != 1.0:
        issues.append(
            ValidationIssue(
                "NLCD_COMPLETENESS", "Annual NLCD v1 requires complete valid source-supported area"
            )
        )
    if (
        definition.geography_semantics != "CONUS_COUNTY_FIPS_2025_ANALYSIS"
        or definition.temporal_semantics != "COUNTY_YEAR"
        or tuple(extra.get("measures", ())) != MEASURES
    ):
        issues.append(
            ValidationIssue("NLCD_GRAIN", "Exact seven county-year measures are required")
        )
    return issues


def _name(tile: str, product: str, suffix: str) -> str:
    return f"nlcd-{tile.lower()}-{product.lower()}-{suffix}"


def _key(tile: str, product: str, year: int, suffix: str) -> str:
    stem = f"Annual_NLCD_{tile}_{product}_{year}_CU_C1V2"
    return f"{PREFIX}/{tile.lower()}/{stem}.{suffix}"


@dataclass(frozen=True)
class RetainedInputs:
    payloads: dict[str, bytes]
    sha256: dict[str, str]
    artifact_ids: dict[str, str]
    upstream_metadata: dict[str, dict[str, str | int | None]]
    retrieved_at: str | None = None
    fixture: bool = False


def _change_code(code: int) -> bool:
    if code in CLASSES:
        return False
    before, after = divmod(code, 100)
    if before in CLASSES and after in CLASSES and before != after:
        return True
    raise ValueError(f"unapproved Annual NLCD Land Cover Change code: {code}")


def _raster_metadata(dataset: Any, product: str, *, fixture: bool) -> None:
    if dataset.count != 1 or dataset.dtypes != (DTYPE[product],):
        raise ValueError(f"{product}: single-band dtype changed")
    if dataset.nodata != NODATA[product]:
        raise ValueError(f"{product}: nodata changed")
    if dataset.scales != (1.0,) or dataset.offsets != (0.0,):
        raise ValueError(f"{product}: scale or offset changed")
    if not CRS.from_wkt(dataset.crs.to_wkt()).equals(_CRS):
        raise ValueError(f"{product}: WGS84 Albers CRS changed")
    affine = dataset.transform
    if not (
        affine.a == 30.0
        and affine.e == -30.0
        and affine.b == 0.0
        and affine.d == 0.0
        and dataset.width > 0
        and dataset.height > 0
    ):
        raise ValueError(f"{product}: unapproved resolution or rotated grid")
    if not fixture and (dataset.width, dataset.height) != (5000, 5000):
        raise ValueError(f"{product}: official tile dimensions changed")


def _pixel_weights(
    county: CountyAnalysisGeometry, native_county: Any, dataset: Any, window: Window
) -> np.ndarray:
    """Use #424 exact boundary intersections and projected areas for full cells."""
    affine = window_transform(window, dataset.transform)
    shape = (int(window.height), int(window.width))
    candidate = rasterize([(native_county, 1)], out_shape=shape, transform=affine, all_touched=True)
    if not candidate.any():
        return np.zeros(shape, dtype=np.float64)
    boundary = rasterize(
        [(native_county.boundary, 1)], out_shape=shape, transform=affine, all_touched=True
    )
    interior = (candidate != 0) & (boundary == 0)
    weights = np.zeros(shape, dtype=np.float64)
    rows, cols = np.nonzero(interior)
    if len(rows):
        left = affine.c + cols * 30.0
        top = affine.f - rows * 30.0
        converter = Transformer.from_crs(dataset.crs, county.analysis_crs, always_xy=True)
        x0, y0 = converter.transform(left, top)
        x1, y1 = converter.transform(left + 30.0, top)
        x2, y2 = converter.transform(left + 30.0, top - 30.0)
        x3, y3 = converter.transform(left, top - 30.0)
        weights[rows, cols] = 0.5 * np.abs(
            x0 * y1 + x1 * y2 + x2 * y3 + x3 * y0 - y0 * x1 - y1 * x2 - y2 * x3 - y3 * x0
        )
    edge_rows, edge_cols = np.nonzero((candidate != 0) & (boundary != 0))
    cells = [
        GridCell(
            f"{row}:{col}",
            box(
                affine.c + col * 30,
                affine.f - (row + 1) * 30,
                affine.c + (col + 1) * 30,
                affine.f - row * 30,
            ),
            None,
        )
        for row, col in zip(edge_rows.tolist(), edge_cols.tolist(), strict=True)
    ]
    if cells:
        exact = grid_intersection_weights(county, cells, grid_crs=dataset.crs.to_wkt())
        for cell_id, area in exact.cell_areas_m2:
            row, col = (int(piece) for piece in cell_id.split(":"))
            weights[row, col] = area
    return weights


class AnnualNLCDAdapter:
    kind = AdapterKind.ANNUAL_NLCD

    def acquire(
        self, definition: SourceDefinition, *, fixture_dir: Path | None = None
    ) -> AcquireResult:
        year = int(definition.extra["mapping_year"])
        tiles = list(definition.extra["tile_ids"])
        artifacts: list[AcquisitionArtifact] = []
        metadata: dict[str, dict[str, str | int | None]] = {}
        total_bytes = 0
        client = boto3.client("s3", region_name="us-west-2") if fixture_dir is None else None
        for tile in tiles:
            for product in PRODUCTS:
                for suffix in ("tif", "xml"):
                    key = _key(tile, product, year, suffix)
                    name = _name(tile, product, suffix)
                    if fixture_dir is not None:
                        payload = (fixture_dir / Path(key).name).read_bytes()
                        info: dict[str, str | int | None] = {"content_length": len(payload)}
                    else:
                        try:
                            assert client is not None
                            response = client.get_object(
                                Bucket=BUCKET, Key=key, RequestPayer="requester"
                            )
                            length = int(response["ContentLength"])
                            if length > _MAX_ARTIFACT_BYTES:
                                raise AcquisitionError(
                                    "NLCD tile exceeds bounded size", code="NLCD_SIZE"
                                )
                            payload = cast(bytes, response["Body"].read(length + 1))
                            info = {
                                "content_length": length,
                                "etag": str(response.get("ETag", "")),
                                "version_id": str(response.get("VersionId", "")),
                                "last_modified": str(response.get("LastModified", "")),
                            }
                        except AcquisitionError:
                            raise
                        except Exception as error:
                            raise AcquisitionError(
                                "Annual NLCD S3 acquisition failed", code="NLCD_S3_GET"
                            ) from error
                    total_bytes += len(payload)
                    if len(payload) > _MAX_ARTIFACT_BYTES or total_bytes > _MAX_RUN_BYTES:
                        raise AcquisitionError("NLCD run exceeds bounded bytes", code="NLCD_SIZE")
                    if len(payload) != info["content_length"]:
                        raise AcquisitionError("NLCD S3 object length changed", code="NLCD_LENGTH")
                    artifacts.append(
                        AcquisitionArtifact(
                            name,
                            payload,
                            "image/tiff" if suffix == "tif" else "application/xml",
                            f"s3://{BUCKET}/{key}",
                            "SOURCE_PAYLOAD"
                            if name == _name(tiles[0], "LndCov", "tif")
                            else "SOURCE_PACKAGE_MEMBER",
                        )
                    )
                    metadata[name] = info
        if fixture_dir is not None:
            tiger = (fixture_dir / "tl_2025_us_county.zip").read_bytes()
        else:
            try:
                with (
                    httpx.Client(timeout=120, follow_redirects=True) as web,
                    web.stream("GET", SOURCE_URL) as response,
                ):
                    response.raise_for_status()
                    length = response.headers.get("Content-Length")
                    if length is not None and int(length) > _MAX_ARTIFACT_BYTES:
                        raise AcquisitionError("TIGER exceeds bounded size", code="TIGER_SIZE")
                    chunks: list[bytes] = []
                    tiger_bytes = 0
                    for chunk in response.iter_bytes():
                        tiger_bytes += len(chunk)
                        if (
                            tiger_bytes > _MAX_ARTIFACT_BYTES
                            or total_bytes + tiger_bytes > _MAX_RUN_BYTES
                        ):
                            raise AcquisitionError("TIGER exceeds bounded size", code="TIGER_SIZE")
                        chunks.append(chunk)
                    tiger = b"".join(chunks)
            except httpx.HTTPError as error:
                raise AcquisitionError("TIGER acquisition failed", code="TIGER_GET") from error
            if hashlib.sha256(tiger).hexdigest() != SELECTED_ARTIFACT_SHA256:
                raise AcquisitionError("Approved TIGER artifact changed", code="TIGER_DIGEST")
        if len(tiger) > _MAX_ARTIFACT_BYTES or total_bytes + len(tiger) > _MAX_RUN_BYTES:
            raise AcquisitionError("TIGER exceeds bounded size", code="TIGER_SIZE")
        artifacts.append(
            AcquisitionArtifact(
                TIGER_MEMBER, tiger, "application/zip", SOURCE_URL, "ANALYSIS_REFERENCE"
            )
        )
        primary = artifacts[0]
        return AcquireResult(
            primary.payload,
            primary.sha256,
            primary.media_type,
            artifacts=tuple(artifacts),
            detail={
                "object_metadata": metadata,
                "fixture": fixture_dir is not None,
                "mapping_year": year,
            },
        )

    def restore_artifacts(
        self, definition: SourceDefinition, run_id: str, store: ArtifactMemberStore
    ) -> RetainedInputs:
        tiles = list(definition.extra["tile_ids"])
        expected = {TIGER_MEMBER} | {
            _name(tile, product, suffix)
            for tile in tiles
            for product in PRODUCTS
            for suffix in ("tif", "xml")
        }
        members = {member.name: member for member in store.list_artifact_members(run_id)}
        if set(members) != expected:
            raise ValueError(
                "Annual NLCD requires the exact named product, metadata, and TIGER members"
            )
        payloads = {
            name: store.load_artifact_member(run_id, name=name) for name in sorted(expected)
        }
        state = cast(CheckpointStore, store).load(run_id)
        checkpoint = state.checkpoint(Stage.ACQUIRE) if state else None
        detail = checkpoint.detail if checkpoint else {}
        return RetainedInputs(
            payloads,
            {name: member.sha256 for name, member in members.items()},
            {name: member.artifact_id for name, member in members.items()},
            cast(dict[str, dict[str, str | int | None]], detail.get("object_metadata", {})),
            checkpoint.completed_at if checkpoint else None,
            detail.get("fixture") is True,
        )

    def restore_raw_payload(self, definition: SourceDefinition, raw_payload: bytes) -> Any:
        raise ValueError("Annual NLCD requires all named run-pinned artifacts")

    def validate_payload(self, definition: SourceDefinition, payload: Any) -> ValidationResult:
        try:
            inputs = self._inputs(payload)
            self._open_and_validate(definition, inputs)
        except (KeyError, OSError, TypeError, ValueError) as error:
            return ValidationResult(
                False, [ValidationIssue("NLCD_INVALID", str(error), FailureCategory.SCHEMA)]
            )
        return ValidationResult(True)

    def normalize(self, definition: SourceDefinition, payload: Any) -> NormalizeResult:
        raise TypeError("Annual NLCD requires bounded streaming normalization")

    def normalize_iter(
        self, definition: SourceDefinition, payload: Any
    ) -> StreamingNormalizeResult:
        return StreamingNormalizeResult(
            self._records(definition, self._inputs(payload)), TRANSFORM_VERSION
        )

    @staticmethod
    def _inputs(payload: Any) -> RetainedInputs:
        if not isinstance(payload, RetainedInputs):
            raise TypeError("Annual NLCD requires retained named artifacts")
        return payload

    @staticmethod
    def _open_and_validate(definition: SourceDefinition, inputs: RetainedInputs) -> None:
        for tile in definition.extra["tile_ids"]:
            reference = None
            for product in PRODUCTS:
                metadata = ET.fromstring(inputs.payloads[_name(tile, product, "xml")])
                title = metadata.findtext("./idinfo/citation/citeinfo/title", "")
                pubdate = metadata.findtext("./idinfo/citation/citeinfo/pubdate", "")
                if (
                    "Annual National Land Cover Database" not in title
                    or PRODUCT_TITLES[product] not in title
                    or "ver. 1.2" not in title
                    or "Conterminous United States" not in title
                    or pubdate != "20260630"
                ):
                    raise ValueError(f"{product}: Collection 1.2 metadata identity changed")
                name = _name(tile, product, "tif")
                with MemoryFile(inputs.payloads[name]) as memory, memory.open() as dataset:
                    _raster_metadata(dataset, product, fixture=inputs.fixture)
                    grid = (
                        dataset.width,
                        dataset.height,
                        tuple(dataset.transform),
                        dataset.crs.to_wkt(),
                    )
                    if reference is not None and grid != reference:
                        raise ValueError("Annual NLCD product grids disagree")
                    reference = grid
                    for _, window in dataset.block_windows(1):
                        values = np.unique(dataset.read(1, window=window))
                        for value in values.tolist():
                            code = int(value)
                            if code == NODATA[product]:
                                continue
                            if product == "LndCov" and code not in CLASSES:
                                raise ValueError(f"unapproved Annual NLCD Land Cover code: {code}")
                            if product == "FctImp" and not 0 <= code <= 100:
                                raise ValueError(
                                    f"Annual NLCD impervious percent outside 0-100: {code}"
                                )
                            if product == "LndChg":
                                _change_code(code)

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
            inputs.payloads[TIGER_MEMBER],
            canonical,
            expected_artifact_sha256=inputs.sha256[TIGER_MEMBER],
        )
        year = int(definition.extra["mapping_year"])
        for fips in definition.extra["county_fips"]:
            county = counties[fips]
            if fips.startswith(("02", "15")):
                yield from self._out_of_coverage(definition, county, year, inputs)
            else:
                yield from self._county_records(definition, county, year, inputs)

    @staticmethod
    def _out_of_coverage(
        definition: SourceDefinition,
        county: CountyAnalysisGeometry,
        year: int,
        inputs: RetainedInputs,
    ) -> Iterator[dict[str, object]]:
        for measure in MEASURES:
            yield _row(
                definition,
                county,
                year,
                measure,
                None,
                "OUT_OF_SOURCE_COVERAGE",
                None,
                None,
                None,
                None,
                None,
                {},
                inputs,
            )

    def _county_records(
        self,
        definition: SourceDefinition,
        county: CountyAnalysisGeometry,
        year: int,
        inputs: RetainedInputs,
    ) -> Iterator[dict[str, object]]:
        areas: dict[str, dict[int, float]] = {product: defaultdict(float) for product in PRODUCTS}
        valid = {product: 0.0 for product in PRODUCTS}
        supported = 0.0
        intersected = 0.0
        impervious_sum = 0.0
        county_shape = project_geometry(
            county.geometry, county.lineage.storage_crs, county.analysis_crs
        )
        expected_area = county_shape.area
        tile_footprints = []
        grid_ids: dict[str, str] = {}
        for tile in definition.extra["tile_ids"]:
            memories = [
                MemoryFile(inputs.payloads[_name(tile, product, "tif")]) for product in PRODUCTS
            ]
            datasets = [memory.open() for memory in memories]
            try:
                reference = datasets[0]
                grid_ids[tile] = hashlib.sha256(
                    f"{tile}:{reference.width}:{reference.height}:"
                    f"{tuple(reference.transform)}:{reference.crs.to_wkt()}".encode()
                ).hexdigest()
                tile_footprints.append(
                    project_geometry(
                        box(*reference.bounds), reference.crs.to_wkt(), county.analysis_crs
                    )
                )
                native_county = project_geometry(
                    county.geometry, county.lineage.storage_crs, reference.crs.to_wkt()
                )
                bounds = native_county.bounds
                raw = from_bounds(*bounds, transform=reference.transform)
                col0 = max(0, math.floor(raw.col_off))
                row0 = max(0, math.floor(raw.row_off))
                col1 = min(reference.width, math.ceil(raw.col_off + raw.width))
                row1 = min(reference.height, math.ceil(raw.row_off + raw.height))
                for row in range(row0, row1, _WINDOW):
                    for col in range(col0, col1, _WINDOW):
                        window = Window(
                            col, row, min(_WINDOW, col1 - col), min(_WINDOW, row1 - row)
                        )
                        weights = _pixel_weights(county, native_county, reference, window)
                        if not weights.any():
                            continue
                        raster_values = {
                            product: datasets[index].read(1, window=window)
                            for index, product in enumerate(PRODUCTS)
                        }
                        intersected += float(np.sum(weights))
                        masks = {
                            product: raster_values[product] != NODATA[product]
                            for product in PRODUCTS
                        }
                        support = masks["LndCov"] | masks["FctImp"] | masks["LndChg"]
                        supported += float(np.sum(weights[support]))
                        for product in PRODUCTS:
                            product_weights = weights[masks[product]]
                            product_values = raster_values[product][masks[product]]
                            valid[product] += float(np.sum(product_weights))
                            if product == "FctImp":
                                impervious_sum += float(
                                    np.dot(product_weights, product_values.astype(float))
                                )
                            else:
                                for code in np.unique(product_values):
                                    areas[product][int(code)] += float(
                                        np.sum(weights[raster_values[product] == code])
                                    )
            finally:
                for dataset in datasets:
                    dataset.close()
                for memory in memories:
                    memory.close()
        if not tile_footprints:
            raise ValueError("Annual NLCD county has no selected tile")
        from shapely.ops import unary_union

        tile_union = unary_union(tile_footprints)
        if (
            sum(footprint.area for footprint in tile_footprints) - tile_union.area
            > max(1.0, tile_union.area) * 1e-10
        ):
            raise ValueError("Annual NLCD selected tiles overlap")
        if county_shape.difference(tile_union).area > expected_area * 1e-8:
            raise ValueError("Annual NLCD selected tiles leave a county gap")
        if intersected > expected_area * (1 + 1e-8):
            raise ValueError("Annual NLCD pixel areas exceed county area")
        if supported > expected_area * (1 + 1e-8):
            raise ValueError("Annual NLCD source-supported area exceeds county area")
        intersected = min(intersected, expected_area)
        supported = min(supported, expected_area)
        for product in PRODUCTS:
            if valid[product] > supported * (1 + 1e-8):
                raise ValueError(f"{product}: valid area exceeds source support")
            valid[product] = min(valid[product], supported)
        weight_id = hashlib.sha256(
            f"{sorted(grid_ids.items())}:{county.lineage.normalized_geometry_sha256}:"
            f"{county.lineage.artifact_sha256}:{WEIGHT_VERSION}".encode()
        ).hexdigest()
        for measure in MEASURES:
            product = (
                "FctImp"
                if measure == "MEAN_IMPERVIOUS_FRACTION"
                else "LndChg"
                if measure == "LAND_COVER_CHANGED_AREA_SHARE"
                else "LndCov"
            )
            product_valid = valid[product]
            fraction = product_valid / supported if supported else None
            if supported == 0:
                status, value = "SOURCE_MISSING", None
            elif fraction is None or fraction + 1e-12 < 1.0:
                status, value = "PARTIAL_COVERAGE", None
            elif year == 1985 and product == "LndChg":
                status, value = "UNVERIFIED_FIRST_YEAR_CHANGE", None
            else:
                status = "COMPLETE"
                if product == "LndCov":
                    value = (
                        math.fsum(areas[product].get(code, 0.0) for code in GROUPS[measure])
                        / product_valid
                    )
                elif product == "FctImp":
                    value = impervious_sum / product_valid / 100.0
                else:
                    value = (
                        math.fsum(
                            area for code, area in areas[product].items() if _change_code(code)
                        )
                        / product_valid
                    )
            yield _row(
                definition,
                county,
                year,
                measure,
                value,
                status,
                expected_area,
                intersected,
                supported,
                product_valid,
                fraction,
                areas[product],
                inputs,
                grid_ids,
                weight_id,
            )


def _row(
    definition: SourceDefinition,
    county: CountyAnalysisGeometry,
    year: int,
    measure: str,
    value: float | None,
    status: str,
    expected: float | None,
    intersected: float | None,
    supported: float | None,
    valid: float | None,
    valid_fraction: float | None,
    class_areas: dict[int, float],
    inputs: RetainedInputs,
    grid_ids: dict[str, str] | None = None,
    weight_id: str | None = None,
) -> dict[str, object]:
    record_id = f"{definition.resource_key}:{county.county_fips}:{year}:{measure}"
    product = (
        "FctImp"
        if measure == "MEAN_IMPERVIOUS_FRACTION"
        else "LndChg"
        if measure == "LAND_COVER_CHANGED_AREA_SHARE"
        else "LndCov"
    )
    return {
        "id": record_id,
        "source_id": definition.source_id,
        "dataset_id": definition.dataset_id,
        "source_definition_version": definition.definition_version,
        "geography_semantics": definition.geography_semantics,
        "temporal_semantics": definition.temporal_semantics,
        "record": {
            "id": record_id,
            "county_fips": county.county_fips,
            "mapping_year": year,
            "period_start": f"{year}-01-01",
            "period_end": f"{year}-12-31",
            "collection_version": "C1V2",
            "collection_release": "2026-06",
            "measure": measure,
            "source_product": product,
            "value": value,
            "unit": "fraction",
            "source_unit": "percent" if product == "FctImp" else "categorical_class_code",
            "denominator": "valid_source_supported_area_m2",
            "coverage_status": status,
            "expected_area_m2": expected,
            "intersected_area_m2": intersected,
            "source_supported_area_m2": supported,
            "valid_area_m2": valid,
            "source_coverage_fraction": supported / expected
            if supported is not None and expected
            else None,
            "valid_fraction_of_supported_area": valid_fraction,
            "native_class_area_m2": {str(code): area for code, area in sorted(class_areas.items())},
            "geometry_version": county.lineage.transform_version,
            "geometry_digest": county.lineage.normalized_geometry_sha256,
            "tiger_sha256": inputs.sha256[TIGER_MEMBER],
            "weight_version": WEIGHT_VERSION,
            "weight_id": weight_id,
            "grid_id_by_tile": grid_ids or {},
            "transformation_version": TRANSFORM_VERSION,
            "artifact_sha256_by_member": inputs.sha256,
            "artifact_id_by_member": inputs.artifact_ids,
            "source_object_metadata": inputs.upstream_metadata,
            "retrieved_at": inputs.retrieved_at,
            "change_period": f"{year - 1}->{year}" if product == "LndChg" and year > 1985 else None,
            "limitation": (
                "Frozen 2025 county geometry; mapped land cover is contextual, not Lyme risk."
            ),
        },
    }
