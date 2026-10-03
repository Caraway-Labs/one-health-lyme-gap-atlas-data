"""Fail-closed bounded national planning; synthetic footprints are fixture evidence."""

from dataclasses import replace
from pathlib import Path

import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from test_annual_nlcd import _county

from lyme_gap_atlas_data.ingestion.annual_nlcd import _CRS, PRODUCTS, _key
from lyme_gap_atlas_data.ingestion.annual_nlcd_planning import (
    TARGET_YEARS,
    CountyTileCoverage,
    TileGridEvidence,
    bounded_definitions,
    county_required_tiles,
    definition_document,
    planned_footprint,
    tile_prefix_inventory,
)
from lyme_gap_atlas_data.ingestion.source_definition import (
    load_source_definition,
    source_definition_from_mapping,
)

BASE = load_source_definition(
    Path(__file__).resolve().parents[1] / "config/sources/usgs_annual_nlcd_c1v2_2025_48081.yml"
)


def _grids() -> list[TileGridEvidence]:
    return [
        TileGridEvidence(
            tile,
            2025,
            product,
            _key(tile, product, 2025, "tif"),
            "version",
            "etag",
            "a" * 64,
            bounds,
        )
        for tile, bounds in [
            ("H14V15", (-10.0, -10.0, 30.0, 70.0)),
            ("H15V15", (30.0, -10.0, 70.0, 70.0)),
        ]
        for product in PRODUCTS
    ]


def _coverage(year: int = 2025, fips: str = "48081") -> CountyTileCoverage:
    return CountyTileCoverage(
        fips, year, ("H14V15", "H15V15"), "TILE_COVERED", 2700.0, 0.0, "b" * 64
    )


def _sizes(year: int = 2025) -> dict[str, int]:
    return {
        _key(tile, product, year, suffix): 1000
        for tile in ("H14V15", "H15V15")
        for product in PRODUCTS
        for suffix in ("tif", "xml")
    }


def test_publisher_prefixes_are_exact_and_sorted() -> None:
    assert tile_prefix_inventory(
        ["annual-nlcd/c1/v2/cu/tile/h15v15/", "annual-nlcd/c1/v2/cu/tile/h14v15/"]
    ) == ("H14V15", "H15V15")
    for prefixes in (
        [],
        ["annual-nlcd/c1/v1/cu/tile/h14v15/"],
        ["annual-nlcd/c1/v2/cu/tile/h14v15/"] * 2,
    ):
        with pytest.raises(ValueError):
            tile_prefix_inventory(prefixes)


def test_multitile_mapping_is_deterministic() -> None:
    grids = _grids()
    mapped = county_required_tiles(
        {"48081": _county()}, year=2025, inventory_tiles=("H14V15", "H15V15"), grids=grids
    )
    assert mapped[0].required_tiles == ("H14V15", "H15V15")
    assert mapped[0].status == "TILE_COVERED"
    assert mapped == county_required_tiles(
        {"48081": _county()}, year=2025, inventory_tiles=("H14V15", "H15V15"), grids=reversed(grids)
    )


def test_inventory_missing_product_drift_overlap_and_gap_fail_closed() -> None:
    arguments = dict(counties={"48081": _county()}, year=2025, inventory_tiles=("H14V15", "H15V15"))
    with pytest.raises(ValueError, match="incomplete"):
        county_required_tiles(**arguments, grids=_grids()[:-1])
    drift = _grids()
    drift[-1] = replace(drift[-1], bounds=(29.0, -10.0, 70.0, 70.0))
    with pytest.raises(ValueError, match="drift"):
        county_required_tiles(**arguments, grids=drift)
    overlap = [
        replace(grid, bounds=(29.0, -10.0, 70.0, 70.0)) if grid.tile_id == "H15V15" else grid
        for grid in _grids()
    ]
    with pytest.raises(ValueError, match="overlapping"):
        county_required_tiles(**arguments, grids=overlap)
    gap = [
        replace(grid, bounds=(31.0, -10.0, 70.0, 70.0)) if grid.tile_id == "H15V15" else grid
        for grid in _grids()
    ]
    result = county_required_tiles(**arguments, grids=gap)
    assert result[0].status == "TILE_GAP"
    with pytest.raises(ValueError, match="blocked"):
        bounded_definitions(BASE, result, _sizes())


@pytest.mark.parametrize("year", [1985, 2005, 2025])
def test_early_middle_recent_definitions_preserve_frozen_contract(year: int) -> None:
    generated = bounded_definitions(BASE, [_coverage(year)], _sizes(year))
    assert len(generated) == 1
    assert generated[0].extra["mapping_year"] == year
    assert generated[0].extra["measures"] == BASE.extra["measures"]
    assert generated[0].extra["tiger_sha256"] == BASE.extra["tiger_sha256"]
    assert generated[0].extra["minimum_valid_fraction_of_supported_area"] == 1.0
    assert tuple(range(1985, 2026)) == TARGET_YEARS


def test_county_batches_and_order_are_stable() -> None:
    coverage = [_coverage(fips=f"48{number:03d}") for number in range(17)]
    first = bounded_definitions(BASE, coverage, _sizes())
    assert [len(definition.extra["county_fips"]) for definition in first] == [16, 1]
    assert first == bounded_definitions(BASE, reversed(coverage), _sizes())
    with pytest.raises(ValueError, match="duplicate"):
        bounded_definitions(BASE, coverage + coverage[:1], _sizes())


def test_missing_xml_and_byte_caps_block_generation() -> None:
    sizes = _sizes()
    del sizes[_key("H14V15", "LndCov", 2025, "xml")]
    with pytest.raises(ValueError, match="missing TIFF/XML"):
        bounded_definitions(BASE, [_coverage()], sizes)
    with pytest.raises(ValueError, match="aggregate"):
        bounded_definitions(BASE, [_coverage()], {key: 50_000_000 for key in _sizes()})
    with pytest.raises(ValueError, match="artifact size"):
        bounded_definitions(BASE, [_coverage()], {key: 128_000_001 for key in _sizes()})


def test_documents_roundtrip_and_retention_counts_repeated_captures() -> None:
    coverage = [_coverage(fips=f"48{number:03d}") for number in range(17)]
    definitions = bounded_definitions(BASE, coverage, _sizes())
    assert source_definition_from_mapping(definition_document(definitions[0])) == definitions[0]
    report = planned_footprint(definitions, _sizes())
    assert report["bounded_runs"] == 2
    assert report["normalized_rows"] == 17 * 7
    assert report["source_artifact_captures"] == 26
    assert report["requester_pays_get_requests"] == 24
    assert report["unique_usgs_object_keys"] == 12
    assert report["unique_usgs_bytes"] == 12_000
    assert report["retained_source_bytes_before_revisions"] == 2 * (83_989_800 + 12_000)


def test_bounded_header_checks_native_grid_and_object_identity() -> None:
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=5000,
            height=5000,
            count=1,
            dtype="uint8",
            nodata=250,
            crs=_CRS.to_wkt(),
            transform=from_origin(-465585, 1064805, 30, 30),
            tiled=True,
            sparse_ok=True,
        ):
            pass
        header = memory.read()[:65_536]
    arguments = dict(
        tile_id="H14V15",
        mapping_year=2025,
        product="LndCov",
        object_key=_key("H14V15", "LndCov", 2025, "tif"),
        version_id="version",
        etag="etag",
    )
    grid = TileGridEvidence.from_header(header, **arguments)
    assert grid.bounds == (-465585.0, 914805.0, -315585.0, 1064805.0)
    with pytest.raises(ValueError, match="identity"):
        TileGridEvidence.from_header(header, **{**arguments, "version_id": "null"})
    with pytest.raises(ValueError, match="bound"):
        TileGridEvidence.from_header(header + b"0" * 65_537, **arguments)
    with pytest.raises(ValueError, match="identity"):
        TileGridEvidence.from_header(header, **{**arguments, "object_key": "mosaic/unknown.tif"})
