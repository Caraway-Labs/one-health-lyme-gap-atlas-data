"""Small, source-specific Annual NLCD categorical and continuous raster proofs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import box
from shapely.ops import transform

from lyme_gap_atlas_data.county_analysis_geometry import (
    CountyAnalysisGeometry,
    GeometryLineage,
    GridCell,
    grid_intersection_weights,
)
from lyme_gap_atlas_data.ingestion.annual_nlcd import (
    _CRS,
    CLASSES,
    MEASURES,
    PRODUCT_TITLES,
    AnnualNLCDAdapter,
    RetainedInputs,
    _key,
    _name,
    _pixel_weights,
)
from lyme_gap_atlas_data.ingestion.checkpoints import FileCheckpointStore
from lyme_gap_atlas_data.ingestion.orchestrator import IngestionOrchestrator
from lyme_gap_atlas_data.ingestion.source_definition import (
    load_source_definition,
    validate_source_definition,
)
from lyme_gap_atlas_data.ingestion.types import RunStatus, Tier
from lyme_gap_atlas_data.semantic_domain import validate_measures
from lyme_gap_atlas_data.semantic_source_mappings import (
    SemanticMappingError,
    _check_output_scope,
    _source_value,
    load_mapping_registry,
)

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = load_source_definition(ROOT / "config/sources/usgs_annual_nlcd_c1v2_2025_48081.yml")
TRANSFORM = from_origin(0, 60, 30, 30)


def _county() -> CountyAnalysisGeometry:
    native = box(0, 0, 45, 60)
    to_source = Transformer.from_crs(_CRS, 4269, always_xy=True)
    geometry = transform(to_source.transform, native)
    lineage = GeometryLineage(
        "TIGER/Line",
        "2025",
        "f" * 64,
        "48081",
        "a" * 64,
        "b" * 64,
        "atlas-county-analysis-geometry/1",
        "EPSG:4269",
        "EPSG:4269",
    )
    return CountyAnalysisGeometry("48081", geometry, "EPSG:5070", lineage)


def _tiff(values: list[list[int]], nodata: int, dtype: str) -> bytes:
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=2,
            height=2,
            count=1,
            dtype=dtype,
            crs=_CRS.to_wkt(),
            transform=TRANSFORM,
            nodata=nodata,
        ) as dataset:
            dataset.write(np.asarray(values, dtype=dtype), 1)
        return memory.read()


def _inputs(
    *,
    cover: list[list[int]] | None = None,
    impervious: list[list[int]] | None = None,
    change: list[list[int]] | None = None,
) -> RetainedInputs:
    values = {
        "LndCov": _tiff(cover or [[41, 21], [82, 250]], 250, "uint8"),
        "FctImp": _tiff(impervious or [[0, 50], [100, 250]], 250, "uint8"),
        "LndChg": _tiff(change or [[41, 4121], [82, 9999]], 9999, "uint16"),
    }
    payloads = {_name("H14V15", product, "tif"): data for product, data in values.items()}
    payloads.update(
        {
            _name("H14V15", product, "xml"): (
                "<metadata><idinfo><citation><citeinfo>"
                "<pubdate>20260630</pubdate>"
                "<title>Annual National Land Cover Database Collection 1 "
                f"{PRODUCT_TITLES[product]} Conterminous United States (ver. 1.2)"
                "</title></citeinfo></citation></idinfo></metadata>"
            ).encode()
            for product in values
        }
    )
    payloads["tiger-2025-analysis-county-zip"] = b"fixture"
    return RetainedInputs(
        payloads,
        {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()},
        {name: f"artifact-{name}" for name in payloads},
        {},
        "2026-09-25T00:00:00Z",
        True,
    )


def _replace_payload(inputs: RetainedInputs, name: str, payload: bytes) -> RetainedInputs:
    from dataclasses import replace

    data = {**inputs.payloads, name: payload}
    return replace(
        inputs,
        payloads=data,
        sha256={member: hashlib.sha256(content).hexdigest() for member, content in data.items()},
    )


def test_source_definition_pins_collection_and_seven_measures() -> None:
    assert validate_source_definition(DEFINITION).ok
    assert len(MEASURES) == 7
    assert len(CLASSES) == 16
    assert tuple(DEFINITION.extra["measures"]) == MEASURES
    assert _key("H14V15", "LndCov", 2025, "tif") == (
        "annual-nlcd/c1/v2/cu/tile/h14v15/Annual_NLCD_H14V15_LndCov_2025_CU_C1V2.tif"
    )


def test_candidate_measures_match_exact_semantic_mappings() -> None:
    document = json.loads(
        (ROOT / "docs/contracts/land-cover/annual-nlcd-semantic-measures-v1.json").read_text()
    )
    measures = document["measures"]
    validate_measures(measures)
    registry = load_mapping_registry(
        ROOT / "docs/contracts/semantic-domain/atlas-semantic-source-mappings-v1.json"
    )
    assert len(measures) == 7
    assert {measure["measure_id"] for measure in measures} == {
        registry[mapping_id]["measure_id"]
        for mapping_id in (
            "nlcd_forest",
            "nlcd_developed",
            "nlcd_agriculture",
            "nlcd_wetland",
            "nlcd_open_water",
            "nlcd_impervious",
            "nlcd_change",
        )
    }


def test_fractional_boundary_weights_match_424() -> None:
    county = _county()
    inputs = _inputs()
    with (
        MemoryFile(inputs.payloads[_name("H14V15", "LndCov", "tif")]) as memory,
        memory.open() as dataset,
    ):
        native = transform(
            Transformer.from_crs(4269, _CRS, always_xy=True).transform, county.geometry
        )
        weights = _pixel_weights(county, native, dataset, rasterio.windows.Window(0, 0, 2, 2))
    cells = [
        GridCell(f"{row}:{col}", box(col * 30, 30 - row * 30, (col + 1) * 30, 60 - row * 30), None)
        for row in range(2)
        for col in range(2)
    ]
    exact = grid_intersection_weights(county, cells, grid_crs=_CRS.to_wkt())
    for cell_id, area in exact.cell_areas_m2:
        row, col = (int(piece) for piece in cell_id.split(":"))
        assert weights[row, col] == pytest.approx(area, rel=1e-9)
    assert weights[0, 1] == pytest.approx(weights[0, 0] / 2, rel=1e-5)


def test_categorical_and_impervious_county_year(monkeypatch: pytest.MonkeyPatch) -> None:
    county = _county()
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.annual_nlcd.load_tiger_counties",
        lambda *_args, **_kwargs: {"48081": county},
    )
    inputs = _inputs()
    adapter = AnnualNLCDAdapter()
    assert adapter.validate_payload(DEFINITION, inputs).ok
    rows = list(adapter.normalize_iter(DEFINITION, inputs).records)
    assert len(rows) == 7
    by_measure = {row["record"]["measure"]: row["record"] for row in rows}
    assert by_measure["FOREST_AREA_SHARE"]["value"] == pytest.approx(0.4, rel=1e-5)
    assert by_measure["DEVELOPED_AREA_SHARE"]["value"] == pytest.approx(0.2, rel=1e-5)
    assert by_measure["AGRICULTURE_AREA_SHARE"]["value"] == pytest.approx(0.4, rel=1e-5)
    assert by_measure["MEAN_IMPERVIOUS_FRACTION"]["value"] == pytest.approx(0.5, rel=1e-5)
    assert by_measure["LAND_COVER_CHANGED_AREA_SHARE"]["value"] == pytest.approx(0.2, rel=1e-5)
    assert by_measure["FOREST_AREA_SHARE"]["source_coverage_fraction"] == pytest.approx(
        5 / 6, rel=1e-5
    )
    assert by_measure["MEAN_IMPERVIOUS_FRACTION"]["source_unit"] == "percent"
    assert by_measure["LAND_COVER_CHANGED_AREA_SHARE"]["native_class_area_m2"].keys() == {
        "41",
        "82",
        "4121",
    }


def test_nodata_zero_and_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    county = _county()
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.annual_nlcd.load_tiger_counties",
        lambda *_args, **_kwargs: {"48081": county},
    )
    adapter = AnnualNLCDAdapter()
    inputs = _inputs(impervious=[[0, 250], [100, 250]])
    rows = list(adapter.normalize_iter(DEFINITION, inputs).records)
    impervious = next(
        row["record"] for row in rows if row["record"]["measure"] == "MEAN_IMPERVIOUS_FRACTION"
    )
    assert impervious["coverage_status"] == "PARTIAL_COVERAGE"
    assert impervious["value"] is None
    assert impervious["valid_area_m2"] > 0  # observed zero is retained as valid
    assert not adapter.validate_payload(DEFINITION, _inputs(cover=[[41, 99], [82, 250]])).ok
    assert not adapter.validate_payload(DEFINITION, _inputs(impervious=[[0, 101], [100, 250]])).ok
    assert not adapter.validate_payload(DEFINITION, _inputs(change=[[41, 4141], [82, 9999]])).ok


def test_product_metadata_grid_and_legacy_drift() -> None:
    from dataclasses import replace

    adapter = AnnualNLCDAdapter()
    inputs = _inputs()
    title = _name("H14V15", "LndCov", "xml")
    assert not adapter.validate_payload(
        DEFINITION,
        _replace_payload(inputs, title, inputs.payloads[title].replace(b"ver. 1.2", b"ver. 1.1")),
    ).ok
    fct = _name("H14V15", "FctImp", "tif")
    assert not adapter.validate_payload(
        DEFINITION, _replace_payload(inputs, fct, _tiff([[0, 50], [100, 250]], 249, "uint8"))
    ).ok
    assert not adapter.validate_payload(
        DEFINITION, _replace_payload(inputs, fct, b"not-a-geotiff")
    ).ok
    legacy = replace(DEFINITION, extra={**DEFINITION.extra, "collection_version": "C1V1"})
    assert not validate_source_definition(legacy).ok


def test_historical_revision_preserves_logical_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    county = _county()
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.annual_nlcd.load_tiger_counties",
        lambda *_args, **_kwargs: {"48081": county},
    )
    adapter = AnnualNLCDAdapter()
    first = {
        row["record"]["measure"]: row
        for row in adapter.normalize_iter(DEFINITION, _inputs()).records
    }
    revised = _inputs(cover=[[42, 21], [82, 250]])
    second = {
        row["record"]["measure"]: row for row in adapter.normalize_iter(DEFINITION, revised).records
    }
    assert first["FOREST_AREA_SHARE"]["id"] == second["FOREST_AREA_SHARE"]["id"]
    assert (
        first["FOREST_AREA_SHARE"]["record"]["artifact_sha256_by_member"]
        != second["FOREST_AREA_SHARE"]["record"]["artifact_sha256_by_member"]
    )
    assert (
        first["FOREST_AREA_SHARE"]["record"]["native_class_area_m2"]
        != second["FOREST_AREA_SHARE"]["record"]["native_class_area_m2"]
    )


def test_missing_tile_and_unsupported_states(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    county = _county()
    wide = replace(
        county,
        geometry=transform(
            Transformer.from_crs(_CRS, 4269, always_xy=True).transform, box(0, 0, 75, 60)
        ),
    )
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.annual_nlcd.load_tiger_counties",
        lambda *_args, **_kwargs: {"48081": wide},
    )
    with pytest.raises(ValueError, match="tile.*gap"):
        list(AnnualNLCDAdapter().normalize_iter(DEFINITION, _inputs()).records)
    alaska = replace(county, county_fips="02013")
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.annual_nlcd.load_tiger_counties",
        lambda *_args, **_kwargs: {"02013": alaska},
    )
    definition = replace(DEFINITION, extra={**DEFINITION.extra, "county_fips": ["02013"]})
    records = [
        row["record"] for row in AnnualNLCDAdapter().normalize_iter(definition, _inputs()).records
    ]
    assert len(records) == 7
    assert all(
        row["coverage_status"] == "OUT_OF_SOURCE_COVERAGE" and row["value"] is None
        for row in records
    )


def test_1985_change_is_not_inferred(monkeypatch: pytest.MonkeyPatch) -> None:
    county = _county()
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.annual_nlcd.load_tiger_counties",
        lambda *_args, **_kwargs: {"48081": county},
    )
    from dataclasses import replace

    definition = replace(DEFINITION, extra={**DEFINITION.extra, "mapping_year": 1985})
    inputs = _inputs()
    rows = list(AnnualNLCDAdapter().normalize_iter(definition, inputs).records)
    change = next(
        row["record"] for row in rows if row["record"]["measure"] == "LAND_COVER_CHANGED_AREA_SHARE"
    )
    assert change["coverage_status"] == "UNVERIFIED_FIRST_YEAR_CHANGE"
    assert change["value"] is None
    assert change["native_class_area_m2"]["4121"] > 0


def test_semantic_mapping_requires_exact_named_lineage_and_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.annual_nlcd.load_tiger_counties",
        lambda *_args, **_kwargs: {"48081": _county()},
    )
    output = next(
        row["record"]
        for row in AnnualNLCDAdapter().normalize_iter(DEFINITION, _inputs()).records
        if row["record"]["measure"] == "FOREST_AREA_SHARE"
    )
    mapping = load_mapping_registry(
        ROOT / "docs/contracts/semantic-domain/atlas-semantic-source-mappings-v1.json"
    )["nlcd_forest"]
    edges = [
        {
            "member_name": name,
            "artifact_sha256": digest,
            "artifact_id": output["artifact_id_by_member"][name],
            "ingestion_run_id": "fixture-run",
        }
        for name, digest in output["artifact_sha256_by_member"].items()
    ]
    record = {
        "source_output": output,
        "value": output["value"],
        "value_state": "OBSERVED",
        "unit": "fraction",
        "denominator": "valid_source_supported_area_m2",
        "geography": {"county_fips": "48081"},
        "temporal": {"start": "2025-01-01", "end": "2025-12-31"},
    }
    assert _source_value(record, mapping) == (output["value"], "OBSERVED")
    _check_output_scope(record, mapping, edges)
    with pytest.raises(SemanticMappingError, match="lineage"):
        _check_output_scope(record, mapping, edges[:-1])
    bad = {**output, "collection_version": "C1V1"}
    with pytest.raises(SemanticMappingError, match="lineage"):
        _check_output_scope({**record, "source_output": bad}, mapping, edges)
    bad = {**output, "valid_fraction_of_supported_area": 0.9}
    with pytest.raises(SemanticMappingError, match="complete"):
        _check_output_scope({**record, "source_output": bad}, mapping, edges)


def test_fresh_process_resume_replays_all_named_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    county = _county()
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.annual_nlcd.load_tiger_counties",
        lambda *_args, **_kwargs: {"48081": county},
    )
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    for name, payload in _inputs().payloads.items():
        if name == "tiger-2025-analysis-county-zip":
            filename = "tl_2025_us_county.zip"
        else:
            _, tile, product, suffix = name.split("-")
            codes = {"lndcov": "LndCov", "fctimp": "FctImp", "lndchg": "LndChg"}
            filename = Path(_key(tile.upper(), codes[product], 2025, suffix)).name
        (fixture / filename).write_bytes(payload)
    store_path = tmp_path / "runs"
    first = IngestionOrchestrator(FileCheckpointStore(store_path), fixture_dir=fixture).run(
        DEFINITION, tier=Tier.A, fail_after_stage="ACQUIRE"
    )
    assert first.status is RunStatus.FAILED
    assert len(first.checkpoint("ACQUIRE").detail["artifacts"]) == 7
    monkeypatch.setattr(
        AnnualNLCDAdapter,
        "acquire",
        lambda *_args, **_kwargs: pytest.fail("resume reacquired an NLCD artifact"),
    )
    resumed = IngestionOrchestrator(FileCheckpointStore(store_path)).resume(
        first.ingestion_run_id, definition=DEFINITION
    )
    assert resumed.status is RunStatus.SUCCEEDED
    rows = [
        row
        for part in FileCheckpointStore(store_path).iter_partitions(first.ingestion_run_id)
        for row in part.records
    ]
    assert len(rows) == 7
    assert {row["record"]["measure"] for row in rows} == set(MEASURES)
