"""Source-specific MOD13Q1.061 identity, QA, geometry and provenance gates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from pyhdf.SD import SD, SDC
from pyproj import Transformer
from rasterio.transform import Affine
from shapely.geometry import box
from shapely.ops import transform

from lyme_gap_atlas_data.county_analysis_geometry import (
    CountyAnalysisGeometry,
    GeometryLineage,
    GridCell,
    grid_intersection_weights,
)
from lyme_gap_atlas_data.ingestion.adapters import AcquisitionError, get_adapter
from lyme_gap_atlas_data.ingestion.checkpoints import FileCheckpointStore
from lyme_gap_atlas_data.ingestion.modis_vegetation import (
    CMR_MEMBER,
    COLLECTION_ID,
    CRS_SIN,
    GRANULE,
    HDF_MAGIC,
    HDF_MEMBER,
    MEASURES,
    TIGER_MEMBER,
    ModisVegetationAdapter,
    RetainedInputs,
    _bounded_get,
    _cmr_entry,
    _hdf_url,
    _pixel_weights,
    _qa_masks,
)
from lyme_gap_atlas_data.ingestion.orchestrator import IngestionOrchestrator
from lyme_gap_atlas_data.ingestion.source_definition import (
    load_source_definition,
    validate_source_definition,
)
from lyme_gap_atlas_data.ingestion.types import AdapterKind, RunStatus, Tier
from lyme_gap_atlas_data.semantic_domain import validate_measures
from lyme_gap_atlas_data.semantic_source_mappings import (
    SemanticMappingError,
    _check_output_scope,
    _source_value,
    load_mapping_registry,
)

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = load_source_definition(
    ROOT / "config/sources/nasa_mod13q1_061_2025193_h09v05_48081.yml"
)


def _cmr() -> bytes:
    return json.dumps(
        {
            "feed": {
                "entry": [
                    {
                        "id": "G3632873570-LPCLOUD",
                        "title": GRANULE,
                        "collection_concept_id": COLLECTION_ID,
                        "time_start": "2025-07-12T00:00:00.000Z",
                        "time_end": "2025-07-27T23:59:59.000Z",
                        "updated": "2025-07-31T11:33:10.874Z",
                        "links": [
                            {
                                "href": (
                                    "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/"
                                    f"MOD13Q1.061/{GRANULE}/{GRANULE}.hdf"
                                )
                            }
                        ],
                    }
                ]
            }
        }
    ).encode()


def _inputs(payloads: dict[str, bytes] | None = None) -> RetainedInputs:
    members = payloads or {
        HDF_MEMBER: HDF_MAGIC + b"fixture",
        CMR_MEMBER: _cmr(),
        TIGER_MEMBER: b"PK\x03\x04fixture",
    }
    return RetainedInputs(
        members,
        {name: hashlib.sha256(data).hexdigest() for name, data in members.items()},
        {name: f"artifact-{name}" for name in members},
        {},
        "2026-09-26T00:00:00Z",
        True,
    )


def _county() -> CountyAnalysisGeometry:
    native = box(0, 0, 1.5, 2)
    converter = Transformer.from_crs(CRS_SIN, 4269, always_xy=True)
    geometry = transform(converter.transform, native)
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


def _hdf_fixture(path: Path, *, cloud: bool = False) -> bytes:
    core = "\n".join(
        f'OBJECT = {name}\nNUM_VAL = 1\nVALUE = "{value}"\nEND_OBJECT = {name}'
        for name, value in (
            ("SHORTNAME", "MOD13Q1"),
            ("VERSIONID", "61"),
            ("LOCALGRANULEID", f"{GRANULE}.hdf"),
            ("RANGEBEGINNINGDATE", "2025-07-12"),
            ("RANGEENDINGDATE", "2025-07-27"),
            ("PRODUCTIONDATETIME", "2025-07-31T16:28:04.000Z"),
        )
    )
    structure = (
        "UpperLeftPointMtrs=(0.000000,2.000000)\n"
        "LowerRightMtrs=(2.000000,0.000000)\n"
        "Projection=GCTP_SNSOID\nProjParams=(6371007.181000,0,0)"
    )
    hdf = SD(str(path), SDC.WRITE | SDC.CREATE)
    hdf.__setattr__("CoreMetadata.0", core)
    hdf.__setattr__("StructMetadata.0", structure)
    specs = (
        ("250m 16 days NDVI", SDC.INT16, [[0, 10000], [5000, 5000]], -3000),
        ("250m 16 days EVI", SDC.INT16, [[0, 5000], [5000, 5000]], -3000),
        (
            "250m 16 days VI Quality",
            SDC.UINT16,
            [[2048, 2048 | 256 if cloud else 2048], [2048, 0]],
            65535,
        ),
        ("250m 16 days pixel reliability", SDC.INT8, [[0, 0], [0, 0]], -1),
        ("250m 16 days composite day of the year", SDC.INT16, [[194, 195], [196, -1]], -1),
    )
    for name, dtype, values, fill in specs:
        item = hdf.create(name, dtype, (2, 2))
        numpy_dtype = (
            np.uint16 if dtype == SDC.UINT16 else np.int8 if dtype == SDC.INT8 else np.int16
        )
        item[:] = np.asarray(values, dtype=numpy_dtype)
        item.setfillvalue(fill)
        if "NDVI" in name or "EVI" in name:
            item.__setattr__("valid_range", [-2000, 10000])
            item.__setattr__("scale_factor", 10000.0)
        item.endaccess()
    hdf.end()
    return path.read_bytes()


def test_definition_is_one_pinned_granule_and_semantic_pair() -> None:
    assert validate_source_definition(DEFINITION).ok
    assert get_adapter(AdapterKind.MODIS_VEGETATION).kind is AdapterKind.MODIS_VEGETATION
    assert tuple(DEFINITION.extra["measures"]) == MEASURES
    assert not validate_source_definition(
        replace(DEFINITION, endpoint_template="https://example.org")
    ).ok
    assert not validate_source_definition(
        replace(
            DEFINITION,
            extra={**DEFINITION.extra, "qa_value_policy": "unreviewed"},
        )
    ).ok
    doc = json.loads(
        (ROOT / "docs/contracts/vegetation/mod13q1-semantic-measures-v1.json").read_text()
    )
    validate_measures(doc["measures"])
    mappings = load_mapping_registry(
        ROOT / "docs/contracts/semantic-domain/atlas-semantic-source-mappings-v1.json"
    )
    assert {item["measure_id"] for item in doc["measures"]} == {
        mappings[name]["measure_id"] for name in ("mod13q1_ndvi", "mod13q1_evi")
    }


def test_cmr_identity_and_no_cross_collection_substitution() -> None:
    assert _hdf_url(_cmr_entry(_cmr())).endswith(f"/{GRANULE}.hdf")
    bad = json.loads(_cmr())
    bad["feed"]["entry"][0]["collection_concept_id"] = "VIIRS-OTHER"
    with pytest.raises(ValueError, match="identity"):
        _cmr_entry(json.dumps(bad).encode())
    bad = json.loads(_cmr())
    bad["feed"]["entry"][0]["links"][0]["href"] = "https://example.org/other.hdf"
    with pytest.raises(ValueError, match="exact LP DAAC"):
        _hdf_url(_cmr_entry(json.dumps(bad).encode()))


@pytest.mark.parametrize(
    ("qa", "reliability", "ndvi", "evi", "doy", "supported", "valid", "reason"),
    [
        (2048, 0, 0, 5000, 194, True, True, None),
        (2049, 1, 5000, 5000, 194, True, False, "marginal"),
        (2050, 3, 5000, 5000, 194, True, False, "cloud"),
        (2048 | 256, 0, 5000, 5000, 194, True, False, "cloud"),
        (2048 | 1024, 0, 5000, 5000, 194, True, False, "cloud"),
        (2048 | 16384, 2, 5000, 5000, 194, True, False, "snow_ice"),
        (2048 | 32768, 0, 5000, 5000, 194, True, False, "shadow"),
        (0, 0, 5000, 5000, 194, False, False, "water_or_coast"),
        (65535, -1, -3000, -3000, -1, False, False, "qa_fill"),
        (2048, 0, -3000, 5000, 194, True, False, "vi_fill_or_invalid"),
        (2048, 0, 5000, 5000, -1, True, False, "doy_fill_or_invalid"),
        (2048, 0, 5000, 5000, 209, True, False, "doy_fill_or_invalid"),
        (2048 | (3 << 2), 0, 5000, 5000, 194, True, False, "marginal"),
    ],
)
def test_native_qa_preserves_zero_and_rejection_reasons(
    qa: int,
    reliability: int,
    ndvi: int,
    evi: int,
    doy: int,
    supported: bool,
    valid: bool,
    reason: str | None,
) -> None:
    values = {
        "qa": np.array([[qa]], dtype=np.uint16),
        "reliability": np.array([[reliability]], dtype=np.int8),
        "ndvi": np.array([[ndvi]], dtype=np.int16),
        "evi": np.array([[evi]], dtype=np.int16),
        "doy": np.array([[doy]], dtype=np.int16),
    }
    support_mask, valid_mask, flags = _qa_masks(values)
    assert bool(support_mask[0, 0]) is supported
    assert bool(valid_mask[0, 0]) is valid
    if reason:
        assert bool(flags[reason][0, 0])


def test_native_qa_flags_can_overlap_without_changing_supported_area() -> None:
    values = {
        "qa": np.array([[2048 | 256 | 32768]], dtype=np.uint16),
        "reliability": np.array([[1]], dtype=np.int8),
        "ndvi": np.array([[5000]], dtype=np.int16),
        "evi": np.array([[5000]], dtype=np.int16),
        "doy": np.array([[194]], dtype=np.int16),
    }
    support, valid, flags = _qa_masks(values)
    assert bool(support[0, 0])
    assert not bool(valid[0, 0])
    assert all(bool(flags[name][0, 0]) for name in ("cloud", "shadow", "marginal"))


def test_boundary_area_uses_424_exact_intersections() -> None:
    county = _county()
    native = box(0, 0, 1.5, 2)
    affine = Affine(1, 0, 0, 0, -1, 2)
    actual = _pixel_weights(county, native, affine, (2, 2))
    cells = [
        GridCell(f"{row}:{col}", box(col, 1 - row, col + 1, 2 - row), None)
        for row in range(2)
        for col in range(2)
    ]
    expected = grid_intersection_weights(county, cells, grid_crs=CRS_SIN.to_wkt())
    for cell_id, area in expected.cell_areas_m2:
        row, col = (int(part) for part in cell_id.split(":"))
        assert actual[row, col] == pytest.approx(area, rel=1e-6)


def test_hdf_raster_normalization_is_deterministic_and_qa_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.modis_vegetation.load_tiger_counties",
        lambda *args, **kwargs: {"48081": _county()},
    )
    hdf = _hdf_fixture(tmp_path / "fixture.hdf")
    inputs = _inputs({HDF_MEMBER: hdf, CMR_MEMBER: _cmr(), TIGER_MEMBER: b"PK\x03\x04fixture"})
    adapter = ModisVegetationAdapter()
    assert adapter.validate_payload(DEFINITION, inputs).ok
    rows = list(adapter.normalize_iter(DEFINITION, inputs).records)
    assert rows == list(adapter.normalize_iter(DEFINITION, inputs).records)
    assert len(rows) == 2
    ndvi, evi = (row["record"] for row in rows)
    assert ndvi["coverage_status"] == evi["coverage_status"] == "COMPLETE"
    assert ndvi["value"] == pytest.approx(0.4, rel=1e-5)
    assert evi["value"] == pytest.approx(0.3, rel=1e-5)
    assert ndvi["source_supported_area_m2"] == ndvi["valid_area_m2"]
    assert ndvi["source_coverage_fraction"] == pytest.approx(5 / 6, rel=1e-5)
    assert ndvi["first_proven_availability_at"] == inputs.retrieved_at
    assert ndvi["period_start"] == "2025-07-12"
    assert ndvi["period_end"] == "2025-07-27"
    assert ndvi["source_production_at"] == "2025-07-31T16:28:04.000Z"
    assert ndvi["cmr_updated"] == "2025-07-31T11:33:10.874Z"
    assert ndvi["first_proven_availability_at"] != ndvi["source_production_at"]
    assert ndvi["artifact_sha256_by_member"] == inputs.sha256
    mappings = load_mapping_registry(
        ROOT / "docs/contracts/semantic-domain/atlas-semantic-source-mappings-v1.json"
    )
    mapping = mappings["mod13q1_ndvi"]
    edges = [
        {
            "member_name": name,
            "artifact_sha256": inputs.sha256[name],
            "artifact_id": inputs.artifact_ids[name],
            "ingestion_run_id": "fixture-run",
        }
        for name in (HDF_MEMBER, CMR_MEMBER, TIGER_MEMBER)
    ]
    semantic_record = {
        "source_output": ndvi,
        "value": ndvi["value"],
        "value_state": "OBSERVED",
        "unit": "unitless_index",
        "denominator": "qa_valid_source_supported_land_area_m2",
        "geography": {"county_fips": "48081"},
        "temporal": {"start": "2025-07-12", "end": "2025-07-27"},
    }
    assert _source_value(semantic_record, mapping) == (ndvi["value"], "OBSERVED")
    zero_output = {**ndvi, "value": 0.0}
    assert _source_value(
        {**semantic_record, "source_output": zero_output, "value": 0.0, "value_state": "ZERO"},
        mapping,
    ) == (0.0, "ZERO")
    _check_output_scope(semantic_record, mapping, edges)
    with pytest.raises(SemanticMappingError, match="lineage"):
        _check_output_scope(semantic_record, mapping, edges[:-1])
    with pytest.raises(SemanticMappingError, match="completeness"):
        _check_output_scope(
            {
                **semantic_record,
                "source_output": {**ndvi, "qa_valid_fraction_of_supported_area": 0.9},
            },
            mapping,
            edges,
        )
    cloudy = replace(
        inputs,
        payloads={**inputs.payloads, HDF_MEMBER: _hdf_fixture(tmp_path / "cloud.hdf", cloud=True)},
    )
    cloudy = replace(
        cloudy, sha256={k: hashlib.sha256(v).hexdigest() for k, v in cloudy.payloads.items()}
    )
    output = list(adapter.normalize_iter(DEFINITION, cloudy).records)[0]["record"]
    assert output["coverage_status"] == "PARTIAL_COVERAGE"
    assert output["value"] is not None
    assert output["qa_category_area_m2"]["cloud"] > 0
    assert _source_value(
        {
            **semantic_record,
            "source_output": output,
            "value": output["value"],
            "value_state": "OBSERVED",
        },
        mapping,
    ) == (output["value"], "OBSERVED")
    cloud_edges = [
        {**edge, "artifact_sha256": cloudy.sha256[edge["member_name"]]} for edge in edges
    ]
    _check_output_scope({**semantic_record, "source_output": output}, mapping, cloud_edges)
    supported = ndvi["source_supported_area_m2"]
    for fraction in (0.866798, 0.999999):
        partial = {
            **ndvi,
            "coverage_status": "PARTIAL_COVERAGE",
            "qa_valid_fraction_of_supported_area": fraction,
            "valid_area_m2": supported * fraction,
            "qa_category_area_m2": {
                **ndvi["qa_category_area_m2"],
                "qa_valid": supported * fraction,
            },
        }
        _check_output_scope({**semantic_record, "source_output": partial}, mapping, edges)
        assert _source_value(
            {"source_output": partial, "value": ndvi["value"], "value_state": "OBSERVED"},
            mapping,
        ) == (ndvi["value"], "OBSERVED")
    zero_valid = {
        **output,
        "valid_area_m2": 0.0,
        "qa_valid_fraction_of_supported_area": 0.0,
        "qa_category_area_m2": {**output["qa_category_area_m2"], "qa_valid": 0.0},
        "value": None,
    }
    _check_output_scope({**semantic_record, "source_output": zero_valid}, mapping, cloud_edges)
    assert _source_value(
        {"source_output": zero_valid, "value": None, "value_state": "MISSING"}, mapping
    ) == (None, "MISSING")
    partial_tile = {
        **partial,
        "intersected_area_m2": ndvi["expected_area_m2"] * 0.9,
        "source_supported_area_m2": supported * 0.8,
        "valid_area_m2": supported * 0.8 * fraction,
        "source_coverage_fraction": supported * 0.8 / ndvi["expected_area_m2"],
        "qa_category_area_m2": {
            **partial["qa_category_area_m2"],
            "source_supported": supported * 0.8,
            "qa_valid": supported * 0.8 * fraction,
        },
        "coverage_status": "SOURCE_MISSING",
    }
    with pytest.raises(SemanticMappingError, match="cannot carry a value"):
        _check_output_scope({**semantic_record, "source_output": partial_tile}, mapping, edges)


def test_named_replay_requires_all_three_members_and_digests() -> None:
    adapter = ModisVegetationAdapter()
    inputs = _inputs()
    with pytest.raises(ValueError, match="named run-pinned"):
        adapter.restore_raw_payload(DEFINITION, b"payload")
    altered = replace(inputs, payloads={**inputs.payloads, CMR_MEMBER: b"{}"})
    assert not adapter.validate_payload(DEFINITION, altered).ok
    missing = replace(inputs, payloads={HDF_MEMBER: inputs.payloads[HDF_MEMBER]})
    assert not adapter.validate_payload(DEFINITION, missing).ok


def test_fresh_process_resume_replays_three_pinned_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.modis_vegetation.load_tiger_counties",
        lambda *args, **kwargs: {"48081": _county()},
    )
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / f"{GRANULE}.hdf").write_bytes(_hdf_fixture(fixture / "generated.hdf"))
    (fixture / "cmr.json").write_bytes(_cmr())
    (fixture / "tl_2025_us_county.zip").write_bytes(b"PK\x03\x04fixture")
    store_path = tmp_path / "runs"
    first = IngestionOrchestrator(FileCheckpointStore(store_path), fixture_dir=fixture).run(
        DEFINITION, tier=Tier.A, fail_after_stage="ACQUIRE"
    )
    assert first.status is RunStatus.FAILED
    assert len(first.checkpoint("ACQUIRE").detail["artifacts"]) == 3
    monkeypatch.setattr(
        ModisVegetationAdapter,
        "acquire",
        lambda *_args, **_kwargs: pytest.fail("resume reacquired a MOD13Q1 artifact"),
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
    assert {row["record"]["measure"] for row in rows} == set(MEASURES)


def test_binary_get_rejects_login_and_oversize_without_content_leak() -> None:
    class Response:
        headers = {"Content-Type": "text/html", "Content-Length": "17"}

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int) -> list[bytes]:
            return [b"<html>login</html>"]

    class Session:
        def get(self, *_: object, **__: object) -> Response:
            return Response()

    with pytest.raises(AcquisitionError, match="document"):
        _bounded_get(Session(), "https://example.org/file.hdf", 100, magic=HDF_MAGIC)  # type: ignore[arg-type]
    Response.headers = {"Content-Type": "binary/octet-stream", "Content-Length": "101"}
    with pytest.raises(AcquisitionError, match="bound"):
        _bounded_get(Session(), "https://example.org/file.hdf", 100, magic=HDF_MAGIC)  # type: ignore[arg-type]
    Response.headers = {
        "Content-Type": "application/json",
        "Content-Length": "2",
        "Content-Encoding": "gzip",
    }
    Response.iter_content = lambda self, chunk_size: [b'{"feed":{}}']  # type: ignore[method-assign]
    body, metadata = _bounded_get(Session(), "https://example.org/cmr.json", 100)  # type: ignore[arg-type]
    assert body == b'{"feed":{}}'
    assert metadata["content_length"] is None
