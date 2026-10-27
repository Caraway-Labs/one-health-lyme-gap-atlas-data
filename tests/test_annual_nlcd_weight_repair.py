"""Independent cell-intersection oracle for the #196/#424 weight repair."""

from __future__ import annotations

import math
import os
from contextlib import ExitStack
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.io import MemoryFile
from rasterio.windows import Window, from_bounds
from shapely.geometry import MultiPolygon, Polygon, box

from lyme_gap_atlas_data.county_analysis_geometry import (
    CountyAnalysisGeometry,
    GeometryLineage,
    GridCell,
    grid_intersection_weights,
    load_tiger_counties,
    project_geometry,
)
from lyme_gap_atlas_data.ingestion import annual_nlcd_mosaic
from lyme_gap_atlas_data.ingestion.annual_nlcd import _pixel_weights, _validate_search_bounds
from lyme_gap_atlas_data.ingestion.annual_nlcd_mosaic import aggregate_county


def _county(polygon: Polygon | MultiPolygon) -> CountyAnalysisGeometry:
    return CountyAnalysisGeometry(
        "01001",
        polygon,
        "EPSG:5070",
        GeometryLineage(
            "test geometry",
            "2025",
            "a" * 64,
            "01001",
            "b" * 64,
            "c" * 64,
            "test transform",
            "EPSG:5070",
            "EPSG:5070",
        ),
    )


def _grid(x: float, y: float) -> SimpleNamespace:
    return SimpleNamespace(transform=Affine(30, 0, x, 0, -30, y), crs=CRS.from_epsg(5070))


def _oracle(polygon: Polygon | MultiPolygon, grid: SimpleNamespace, window: Window) -> np.ndarray:
    result = np.zeros((int(window.height), int(window.width)), dtype=float)
    for row in range(result.shape[0]):
        for col in range(result.shape[1]):
            x = grid.transform.c + (int(window.col_off) + col) * 30
            y = grid.transform.f - (int(window.row_off) + row) * 30
            result[row, col] = polygon.intersection(box(x, y - 30, x + 30, y)).area
    return result


@pytest.mark.parametrize(
    "polygon",
    [
        Polygon(
            [
                (1_000_003.0, 2_000_000.0 - 0.0001),
                (1_000_147.0, 2_000_000.0 - 5.0),
                (1_000_147.0, 1_999_912.0),
                (1_000_003.0, 1_999_912.0),
            ]
        ),
        Polygon(
            box(1_000_000, 1_999_880, 1_000_120, 2_000_000).exterior,
            [box(1_000_047, 1_999_933, 1_000_062, 1_999_956).exterior],
        ),
        MultiPolygon(
            [
                box(1_000_001, 1_999_941, 1_000_041, 1_999_999),
                box(1_000_089, 1_999_912, 1_000_119, 1_999_958),
            ]
        ),
    ],
    ids=("shallow-sliver", "hole", "multipart"),
)
def test_every_cell_matches_independent_exact_oracle(
    polygon: Polygon | MultiPolygon,
) -> None:
    grid = _grid(1_000_000, 2_000_000)
    window = Window(0, 0, 4, 4)
    actual = _pixel_weights(_county(polygon), grid, window)
    expected = _oracle(polygon, grid, window)
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-7)
    window_footprint = box(1_000_000, 1_999_880, 1_000_120, 2_000_000)
    assert math.isclose(
        float(np.sum(actual)), polygon.intersection(window_footprint).area, abs_tol=1e-7
    )


def test_large_coordinates_preserve_full_cell_area() -> None:
    x, y = 10_000_000.0, 20_000_000.0
    polygon = box(x, y - 60, x + 60, y)
    actual = _pixel_weights(_county(polygon), _grid(x, y), Window(0, 0, 2, 2))
    np.testing.assert_allclose(actual, np.full((2, 2), 900.0), rtol=0, atol=1e-7)


def test_window_neighbors_and_tiny_island_match_oracle() -> None:
    x, y = 1_000_000.0, 2_000_000.0
    polygon = MultiPolygon(
        [
            box(x + 255 * 30 - 4, y - 55, x + 256 * 30 + 3, y - 2),
            box(x + 257 * 30 + 0.01, y - 0.01, x + 257 * 30 + 0.02, y - 0.005),
        ]
    )
    grid = _grid(x, y)
    actual = np.hstack(
        [
            _pixel_weights(_county(polygon), grid, Window(254, 0, 2, 2)),
            _pixel_weights(_county(polygon), grid, Window(256, 0, 2, 2)),
            _pixel_weights(_county(polygon), grid, Window(258, 0, 1, 2)),
        ]
    )
    expected = np.hstack(
        [
            _oracle(polygon, grid, Window(254, 0, 2, 2)),
            _oracle(polygon, grid, Window(256, 0, 2, 2)),
            _oracle(polygon, grid, Window(258, 0, 1, 2)),
        ]
    )
    np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-7)
    assert actual[0, 3] > 0  # Tiny island in a neighboring window is retained.


@pytest.mark.parametrize("partial", [False, True])
def test_all_seven_rows_match_direct_cell_polygon_oracle(partial: bool) -> None:
    x, y = 1_000_000.0, 2_000_000.0
    polygon = Polygon(
        box(x, y - 120, x + 120, y).exterior,
        [box(x + 47, y - 67, x + 62, y - 44).exterior],
    )
    county = _county(polygon)
    grid = _grid(x, y)
    cover = np.array(
        [[11, 21, 41, 81], [90, 95, 42, 82], [43, 31, 52, 71], [12, 22, 23, 24]],
        dtype=np.uint8,
    )
    impervious = np.array(
        [[0, 10, 20, 30], [40, 50, 60, 70], [80, 90, 100, 0], [0, 20, 40, 60]],
        dtype=np.uint8,
    )
    change = np.array(
        [[11, 2122, 41, 8182], [90, 95, 4243, 82], [43, 31, 52, 71], [12, 22, 23, 24]],
        dtype=np.uint16,
    )
    for values, nodata in ((cover, 250), (impervious, 250), (change, 9999)):
        values[3, 3] = nodata  # Legal county area outside all product support.
    if partial:
        cover[0, 0] = 250
        change[0, 0] = 9999  # Impervious still supports this area.

    arrays = {"LndCov": cover, "FctImp": impervious, "LndChg": change}
    nodata = {"LndCov": 250, "FctImp": 250, "LndChg": 9999}
    with ExitStack() as stack:
        datasets = {}
        for product, values in arrays.items():
            memory = stack.enter_context(MemoryFile())
            dataset = stack.enter_context(
                memory.open(
                    driver="GTiff",
                    width=4,
                    height=4,
                    count=1,
                    dtype=values.dtype,
                    crs=grid.crs,
                    transform=grid.transform,
                    nodata=nodata[product],
                )
            )
            dataset.write(values, 1)
            datasets[product] = dataset
        rows = aggregate_county(county, datasets, "test-lineage")

    groups = {
        "FOREST_AREA_SHARE": {41, 42, 43},
        "DEVELOPED_AREA_SHARE": {21, 22, 23, 24},
        "AGRICULTURE_AREA_SHARE": {81, 82},
        "WETLAND_AREA_SHARE": {90, 95},
        "OPEN_WATER_AREA_SHARE": {11},
    }
    class_area: dict[int, float] = {}
    product_valid = dict.fromkeys(arrays, 0.0)
    intersected = supported = impervious_sum = changed_area = 0.0
    for row in range(4):
        for col in range(4):
            cell = box(x + 30 * col, y - 30 * (row + 1), x + 30 * (col + 1), y - 30 * row)
            area = polygon.intersection(cell).area
            intersected += area
            if any(arrays[product][row, col] != nodata[product] for product in arrays):
                supported += area
            for product, values in arrays.items():
                value = int(values[row, col])
                if value == nodata[product]:
                    continue
                product_valid[product] += area
                if product == "LndCov":
                    class_area[value] = class_area.get(value, 0.0) + area
                elif product == "FctImp":
                    impervious_sum += area * value
                elif value >= 100:
                    changed_area += area

    assert len(rows) == 7
    for actual in rows:
        measure = actual["measure"]
        product = (
            "FctImp"
            if measure == "MEAN_IMPERVIOUS_FRACTION"
            else "LndChg"
            if measure == "LAND_COVER_CHANGED_AREA_SHARE"
            else "LndCov"
        )
        valid = product_valid[product]
        status = "COMPLETE" if math.isclose(valid, supported, abs_tol=1e-8) else "PARTIAL_COVERAGE"
        expected_value = None
        if status == "COMPLETE":
            if measure in groups:
                expected_value = sum(class_area.get(code, 0.0) for code in groups[measure]) / valid
            elif product == "FctImp":
                expected_value = impervious_sum / valid / 100
            else:
                expected_value = changed_area / valid
        assert actual["coverage_status"] == status
        if expected_value is None:
            assert actual["value"] is None
        else:
            assert actual["value"] == pytest.approx(expected_value)
        assert actual["expected_area_m2"] == pytest.approx(polygon.area)
        assert actual["intersected_area_m2"] == pytest.approx(intersected)
        assert actual["source_supported_area_m2"] == pytest.approx(supported)
        assert actual["valid_area_m2"] == pytest.approx(valid)
        assert actual["source_coverage_fraction"] == pytest.approx(supported / polygon.area)
        assert actual["valid_fraction_of_supported_area"] == pytest.approx(valid / supported)


def test_truncated_candidate_envelope_fails_instead_of_undercounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    x, y = 1_000_000.0, 2_000_000.0
    county = _county(box(x + 90, y - 210, x + 210, y - 90))
    grid = _grid(x, y)
    monkeypatch.setattr(
        annual_nlcd_mosaic, "from_bounds", lambda *_args, **_kwargs: Window(4, 4, 1, 1)
    )
    with ExitStack() as stack:
        datasets = {}
        for product, code, nodata, dtype in (
            ("LndCov", 41, 250, "uint8"),
            ("FctImp", 0, 250, "uint8"),
            ("LndChg", 41, 9999, "uint16"),
        ):
            memory = stack.enter_context(MemoryFile())
            dataset = stack.enter_context(
                memory.open(
                    driver="GTiff",
                    width=10,
                    height=10,
                    count=1,
                    dtype=dtype,
                    crs=grid.crs,
                    transform=grid.transform,
                    nodata=nodata,
                )
            )
            dataset.write(np.full((10, 10), code, dtype=dtype), 1)
            datasets[product] = dataset
        with pytest.raises(ValueError, match="candidate coverage unverified"):
            aggregate_county(county, datasets, "test-lineage")


def test_retained_46127_matches_frozen_exact_cells_and_conserves_area() -> None:
    supplied = os.environ.get("ATLAS_NLCD_RETAINED_INPUTS")
    if not supplied:
        pytest.skip("retained original TIGER and mosaic inputs are required")
    root = Path(supplied)
    canonical = (
        files("lyme_gap_atlas_data")
        .joinpath("data/canonical-county-fips-2022.txt")
        .read_text()
        .splitlines()
    )
    county = load_tiger_counties((root / "tl_2025_us_county.zip").read_bytes(), canonical)["46127"]
    with rasterio.open(root / "Annual_NLCD_LndCov_2025_CU_C1V2.tif") as dataset:
        native = project_geometry(county.geometry, county.lineage.storage_crs, dataset.crs.to_wkt())
        raw = from_bounds(*native.bounds, transform=dataset.transform)
        col0, row0 = max(0, math.floor(raw.col_off) - 1), max(0, math.floor(raw.row_off) - 1)
        col1 = min(dataset.width, math.ceil(raw.col_off + raw.width) + 1)
        row1 = min(dataset.height, math.ceil(raw.row_off + raw.height) + 1)
        totals = []
        for row in range(row0, row1, 256):
            for col in range(col0, col1, 256):
                window = Window(col, row, min(256, col1 - col), min(256, row1 - row))
                weights = _pixel_weights(county, dataset, window)
                _validate_search_bounds(weights, window, (col0, row0, col1, row1), dataset)
                totals.append(float(np.sum(weights)))
                if row <= 36087 < row + int(window.height) and col <= 78901 < col + int(
                    window.width
                ):
                    cells = [
                        GridCell(
                            str(index),
                            box(
                                dataset.transform.c + index * 30,
                                dataset.transform.f - (36087 + 1) * 30,
                                dataset.transform.c + (index + 1) * 30,
                                dataset.transform.f - 36087 * 30,
                            ),
                            None,
                        )
                        for index in range(78901, 78906)
                    ]
                    exact = dict(
                        grid_intersection_weights(
                            county, cells, grid_crs=dataset.crs.to_wkt()
                        ).cell_areas_m2
                    )
                    for index in range(78901, 78906):
                        assert weights[36087 - row, index - col] == pytest.approx(
                            exact[str(index)], abs=1e-7
                        )
        expected_area = project_geometry(
            county.geometry, county.lineage.storage_crs, county.analysis_crs
        ).area
        assert abs(math.fsum(totals) - expected_area) < expected_area * 1e-8
