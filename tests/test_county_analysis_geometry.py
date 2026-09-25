"""Story #424 fixture tests; no governed acquisition or warehouse access."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest
import shapefile
from pyproj import CRS
from shapely.geometry import MultiPolygon, box

from lyme_gap_atlas_data.county_analysis_geometry import (
    SELECTED_ARTIFACT_SHA256,
    SOURCE_PRODUCT,
    SOURCE_VINTAGE,
    TRANSFORM_VERSION,
    CountyAnalysisGeometry,
    CountyGeometryError,
    GeometryLineage,
    GridCell,
    analysis_crs,
    area_weighted_mean,
    load_tiger_counties,
    project_geometry,
)

ROOT = Path(__file__).resolve().parents[1]
FIPS = tuple(
    (ROOT / "docs/contracts/county-identity-geometry/canonical-county-fips-2022.txt")
    .read_text(encoding="utf-8")
    .splitlines()
)


def _archive(
    *, omit: str | None = None, extra: str | None = None, invalid: str | None = None
) -> bytes:
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    writer = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON)
    for name, width in (("STATEFP", 2), ("COUNTYFP", 3), ("GEOID", 5), ("MTFCC", 5)):
        writer.field(name, "C", size=width)
    for index, geoid in enumerate((*FIPS, *((extra,) if extra else ()))):
        if geoid == omit:
            continue
        x = float(index * 2)
        parts = [[(x, 0), (x, 1), (x + 1, 1), (x + 1, 0), (x, 0)]]
        if geoid == invalid:
            parts = [[(x, 0), (x + 1, 1), (x, 1), (x + 1, 0), (x, 0)]]
        if geoid == "02013":
            parts.append([(x, 2), (x, 3), (x + 1, 3), (x + 1, 2), (x, 2)])
        writer.poly(parts)
        writer.record(geoid[:2], geoid[2:], geoid, "G4020")
    writer.close()
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as archive:
        for extension, contents in (("shp", shp), ("shx", shx), ("dbf", dbf)):
            archive.writestr(f"tl_2025_us_county.{extension}", contents.getvalue())
        archive.writestr("tl_2025_us_county.prj", CRS.from_epsg(4269).to_wkt())
    return result.getvalue()


def _load(archive: bytes, canonical: tuple[str, ...] = FIPS) -> dict[str, CountyAnalysisGeometry]:
    return load_tiger_counties(
        archive, canonical, expected_artifact_sha256=hashlib.sha256(archive).hexdigest()
    )


def _county() -> CountyAnalysisGeometry:
    lineage = GeometryLineage(
        SOURCE_PRODUCT,
        SOURCE_VINTAGE,
        "a" * 64,
        "01001",
        "b" * 64,
        "c" * 64,
        TRANSFORM_VERSION,
        "EPSG:5070",
        "EPSG:5070",
    )
    return CountyAnalysisGeometry("01001", box(0, 0, 1000, 1000), "EPSG:5070", lineage)


def test_exact_reconciliation_vintage_multipart_and_lineage() -> None:
    assert SELECTED_ARTIFACT_SHA256 == (
        "9c6e9d9076abce2670d1de255de3710c35ecca00a7005d88e012dec52d95f763"
    )
    assert len(FIPS) == 3144 == len(set(FIPS))
    archive = _archive()
    first = _load(archive)
    second = _load(archive)
    assert tuple(first) == FIPS
    assert first["02013"].geometry.geom_type == "MultiPolygon"
    assert first["02013"].geometry.is_valid
    assert first["02013"].geometry.wkb == second["02013"].geometry.wkb
    assert first["02013"].lineage == second["02013"].lineage
    assert first["01001"].lineage.source_product == SOURCE_PRODUCT
    assert first["01001"].lineage.source_vintage == "2025"
    assert first["01001"].lineage.artifact_sha256 == hashlib.sha256(archive).hexdigest()
    assert first["01001"].lineage.source_crs == "EPSG:4269"
    assert first["01001"].lineage.transform_version == TRANSFORM_VERSION


def test_reconciliation_fails_on_missing_or_changed_identity() -> None:
    with pytest.raises(CountyGeometryError, match="canonical_only"):
        _load(_archive(omit="01001"))
    with pytest.raises(CountyGeometryError, match="TIGER_only"):
        _load(_archive(omit="01001", extra="01999"))
    with pytest.raises(CountyGeometryError, match="pinned digest"):
        load_tiger_counties(_archive(), FIPS, expected_artifact_sha256="0" * 64)
    with pytest.raises(CountyGeometryError, match="invalid"):
        _load(_archive(invalid="01001"))


def test_equal_area_crs_and_no_simplification() -> None:
    assert analysis_crs("02013") == "EPSG:3338"
    assert analysis_crs("15001") == "EPSG:2782"
    assert analysis_crs("09110") == "EPSG:5070"
    source = MultiPolygon((box(-100, 40, -99, 41), box(-98, 40, -97, 41)))
    projected = project_geometry(source, "EPSG:4269", "EPSG:5070")
    assert projected.geom_type == "MultiPolygon"
    assert len(projected.geoms) == len(source.geoms)
    assert sum(len(part.exterior.coords) for part in projected.geoms) == 10
    assert projected.area > 0
    assert projected.wkb == project_geometry(source, "EPSG:4269", "EPSG:5070").wkb
    lineage = _county().lineage
    geographic_county = CountyAnalysisGeometry(
        "01001",
        box(-100, 40, -99, 41),
        "EPSG:5070",
        GeometryLineage(
            lineage.source_product,
            lineage.source_vintage,
            lineage.artifact_sha256,
            lineage.source_geoid,
            lineage.source_geometry_sha256,
            lineage.normalized_geometry_sha256,
            lineage.transform_version,
            "EPSG:4269",
            "EPSG:4269",
        ),
    )
    weighted = area_weighted_mean(
        geographic_county,
        [GridCell("native", box(-100, 40, -99, 41), 7)],
        grid_crs="EPSG:4269",
        unit="K",
        minimum_completeness=0.99,
    )
    assert weighted.status == "COMPLETE"
    assert weighted.value == 7
    assert weighted.county_area_m2 > 1_000_000_000


def test_area_weighting_boundary_nodata_completeness_and_repeatability() -> None:
    county = _county()
    cells = [
        GridCell("b", box(500, 0, 1000, 1000), 30),
        GridCell("a", box(0, 0, 500, 1000), 10),
        GridCell("touch", box(1000, 0, 1100, 1000), 999),
    ]
    result = area_weighted_mean(
        county, cells, grid_crs="EPSG:5070", unit="K", minimum_completeness=1
    )
    assert result.status == "COMPLETE"
    assert result.value == 20
    assert result.unit == "K"
    assert result.valid_area_m2 == result.county_area_m2 == 1_000_000
    assert result.intersected_area_m2 == 1_000_000
    assert result.completeness == 1
    assert result.geometry_version == TRANSFORM_VERSION
    assert result == area_weighted_mean(
        county, reversed(cells), grid_crs="EPSG:5070", unit="K", minimum_completeness=1
    )
    nodata = [GridCell("a", cells[1].geometry, 10), GridCell("b", cells[0].geometry, None)]
    partial = area_weighted_mean(
        county, nodata, grid_crs="EPSG:5070", unit="K", minimum_completeness=0.75
    )
    assert partial.status == "INCOMPLETE" and partial.value is None
    assert partial.completeness == 0.5
    assert (
        area_weighted_mean(
            county, nodata, grid_crs="EPSG:5070", unit="K", minimum_completeness=0.5
        ).value
        == 10
    )
    assert (
        area_weighted_mean(
            county,
            [GridCell("x", box(2000, 0, 3000, 1000), 5)],
            grid_crs="EPSG:5070",
            unit="K",
            minimum_completeness=0,
        ).status
        == "NO_INTERSECTING_CELLS"
    )
    assert (
        area_weighted_mean(
            county,
            [GridCell("x", box(0, 0, 1000, 1000), None)],
            grid_crs="EPSG:5070",
            unit="K",
            minimum_completeness=0,
        ).status
        == "NO_VALID_CELLS"
    )


def test_overlapping_cells_and_invalid_values_fail() -> None:
    county = _county()
    with pytest.raises(CountyGeometryError, match="overlap"):
        area_weighted_mean(
            county,
            [GridCell("a", box(0, 0, 600, 1000), 1), GridCell("b", box(500, 0, 1000, 1000), 2)],
            grid_crs="EPSG:5070",
            unit="K",
            minimum_completeness=0,
        )
    with pytest.raises(CountyGeometryError, match="non-finite"):
        area_weighted_mean(
            county,
            [GridCell("a", box(0, 0, 1000, 1000), float("nan"))],
            grid_crs="EPSG:5070",
            unit="K",
            minimum_completeness=0,
        )
