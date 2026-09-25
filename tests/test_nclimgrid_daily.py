"""Bounded NOAA NetCDF, county semantics, and named-member replay fixtures."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date
from importlib.resources import files
from pathlib import Path

import h5netcdf  # type: ignore[import-untyped]
import numpy as np
import pytest
from shapely.geometry import box

from lyme_gap_atlas_data.county_analysis_geometry import (
    CountyAnalysisGeometry,
    GeometryLineage,
    analysis_crs,
)
from lyme_gap_atlas_data.ingestion.checkpoints import FileCheckpointStore
from lyme_gap_atlas_data.ingestion.identity import deterministic_record_id, source_row_hash
from lyme_gap_atlas_data.ingestion.nclimgrid_daily import (
    NClimGridDailyAdapter,
    RetainedInputs,
)
from lyme_gap_atlas_data.ingestion.orchestrator import IngestionOrchestrator
from lyme_gap_atlas_data.ingestion.source_definition import (
    load_source_definition,
    validate_source_definition,
)
from lyme_gap_atlas_data.ingestion.types import RunStatus, Tier
from lyme_gap_atlas_data.semantic_domain import validate_measures
from lyme_gap_atlas_data.semantic_governance import Outcome, compare_measure
from lyme_gap_atlas_data.semantic_source_mappings import (
    SemanticMappingError,
    _check_output_scope,
    _source_value,
    load_mapping_registry,
)

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = load_source_definition(ROOT / "config/sources/noaa_nclimgrid_daily_202501.yml")
STEP = 1 / 24


def _county(
    fips: str, west: float, south: float, east: float, north: float
) -> CountyAnalysisGeometry:
    digest = hashlib.sha256(fips.encode()).hexdigest()
    return CountyAnalysisGeometry(
        fips,
        box(west, south, east, north),
        analysis_crs(fips),
        GeometryLineage(
            "TIGER/Line County",
            "2025",
            digest,
            fips,
            digest,
            digest,
            "atlas-county-analysis-geometry/1",
            "EPSG:4269",
            "EPSG:4269",
        ),
    )


def _counties() -> dict[str, CountyAnalysisGeometry]:
    return {
        "01001": _county("01001", -100 - STEP / 4, 30 - STEP / 4, -100 + STEP / 4, 30 + STEP / 4),
        "01003": _county("01003", -100 - STEP / 2, 30 - STEP / 2, -100 + STEP * 1.5, 30 + STEP / 2),
        "01005": _county(
            "01005", -100 + STEP * 0.75, 30 - STEP / 4, -100 + STEP * 1.25, 30 + STEP / 4
        ),
        "02013": _county("02013", -150, 60, -149, 61),
        "15001": _county("15001", -155, 19, -154, 20),
    }


def _netcdf(path: Path, *, revised: bool = False) -> bytes:
    first_day = (date(2025, 1, 1) - date(1800, 1, 1)).days
    with h5netcdf.File(path, "w") as file:
        file.dimensions = {"time": 2, "lat": 2, "lon": 2}
        file.attrs["product_version"] = "v1-0-0 fixture"
        file.attrs["date_modified"] = "2025-02-05 00:00:00"
        for name, dim, values, unit in (
            ("time", "time", [first_day, first_day + 1], "days since 1800-01-01 00:00:00"),
            ("lat", "lat", [30, 30 + STEP], "degrees_north"),
            ("lon", "lon", [-100, -100 + STEP], "degrees_east"),
        ):
            variable = file.create_variable(name, (dim,), data=np.array(values, dtype="f8"))
            variable.attrs["units"] = unit
            if name == "time":
                variable.attrs["calendar"] = "gregorian"
        for measure, unit in (
            ("prcp", "millimeter"),
            ("tmin", "degree_Celsius"),
            ("tmax", "degree_Celsius"),
            ("tavg", "degree_Celsius"),
        ):
            values = np.array(
                [
                    [[0 if measure == "prcp" else 5, np.nan], [2, 3]],
                    [[7 if measure == "prcp" else 8, np.nan], [4, 5]],
                ],
                dtype="f8",
            )
            if measure == "prcp" and revised:
                values[0, 0, 0] = 1
            variable = file.create_variable(
                measure, ("time", "lat", "lon"), data=values, fillvalue=np.nan
            )
            variable.attrs["units"] = unit
    return path.read_bytes()


def _inputs(data: bytes) -> RetainedInputs:
    return RetainedInputs(
        data,
        b"fixture-tiger",
        hashlib.sha256(data).hexdigest(),
        hashlib.sha256(b"fixture-tiger").hexdigest(),
        "noaa-artifact",
        "tiger-artifact",
    )


def test_native_measures_coverage_and_revision_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.nclimgrid_daily.load_tiger_counties",
        lambda *args, **kwargs: _counties(),
    )
    original = _netcdf(tmp_path / "original.nc")
    revised = _netcdf(tmp_path / "revised.nc", revised=True)
    rows = list(NClimGridDailyAdapter().normalize_iter(DEFINITION, _inputs(original)).records)
    recaptured = replace(
        _inputs(original),
        noaa_artifact_id="new-run-noaa",
        tiger_artifact_id="new-run-tiger",
        retrieved_at="2026-09-25T14:00:00+00:00",
    )
    recaptured_rows = list(NClimGridDailyAdapter().normalize_iter(DEFINITION, recaptured).records)
    new_rows = list(NClimGridDailyAdapter().normalize_iter(DEFINITION, _inputs(revised)).records)
    assert len(rows) == 31 * 4 * 5
    assert rows == recaptured_rows
    assert [row["id"] for row in rows] == [row["id"] for row in new_rows]
    original_prcp = next(
        row["record"]
        for row in rows
        if row["id"] == "noaa_nclimgrid_daily_202501:01001:2025-01-01:PRCP"
    )
    revised_prcp = next(
        row["record"]
        for row in new_rows
        if row["id"] == "noaa_nclimgrid_daily_202501:01001:2025-01-01:PRCP"
    )
    assert original_prcp["value"] == 0
    assert revised_prcp["value"] == 1
    assert original_prcp["trace_state"] == "NOT_REPRESENTED"
    assert original_prcp["noaa_sha256"] != revised_prcp["noaa_sha256"]
    assert deterministic_record_id(
        DEFINITION.resource_key, 1, original_prcp
    ) == deterministic_record_id(DEFINITION.resource_key, 1, revised_prcp)
    assert source_row_hash(original_prcp) != source_row_hash(revised_prcp)
    coastal = next(
        row["record"]
        for row in rows
        if row["id"] == "noaa_nclimgrid_daily_202501:01003:2025-01-01:PRCP"
    )
    assert coastal["coverage_status"] == "COMPLETE"
    assert isinstance(coastal["value"], float)
    assert 0 < coastal["source_coverage_fraction"] < 0.95
    assert coastal["valid_fraction_of_supported_area"] == 1
    assert coastal["intersected_area_m2"] > coastal["source_supported_area_m2"]
    missing = next(
        row["record"]
        for row in rows
        if row["id"] == "noaa_nclimgrid_daily_202501:01005:2025-01-01:PRCP"
    )
    assert missing["coverage_status"] == "SOURCE_MISSING"
    assert missing["value"] is None
    absent_day = next(
        row["record"]
        for row in rows
        if row["id"] == "noaa_nclimgrid_daily_202501:01001:2025-01-03:PRCP"
    )
    assert absent_day["coverage_status"] == "SOURCE_MISSING"
    assert absent_day["source_time_present"] is False
    assert {
        row["record"]["coverage_status"]
        for row in rows
        if str(row["id"]).split(":")[1] in {"02013", "15001"}
    } == {"OUT_OF_SOURCE_COVERAGE"}
    tavg = next(
        row["record"]
        for row in rows
        if row["id"] == "noaa_nclimgrid_daily_202501:01001:2025-01-01:TAVG"
    )
    assert tavg["value"] == 5
    assert tavg["source_variable"] == "tavg"
    revised_tavg = next(
        row["record"]
        for row in new_rows
        if row["id"] == "noaa_nclimgrid_daily_202501:01001:2025-01-01:TAVG"
    )
    assert revised_tavg["value"] == tavg["value"]
    assert revised_tavg["noaa_sha256"] != tavg["noaa_sha256"]


def test_static_source_support_and_daily_missingness_are_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    counties = {
        **_counties(),
        "01009": _county(
            "01009", -100 - STEP / 2, 30 - STEP / 2, -100 + STEP * 1.5, 30 + STEP * 1.5
        ),
    }
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.nclimgrid_daily.load_tiger_counties",
        lambda *args, **kwargs: counties,
    )
    path = tmp_path / "daily-missing.nc"
    _netcdf(path)
    with h5netcdf.File(path, "r+") as dataset:
        dataset.variables["prcp"][0, 1, 1] = np.nan
    rows = list(
        NClimGridDailyAdapter().normalize_iter(DEFINITION, _inputs(path.read_bytes())).records
    )

    def prcp(fips: str, day: str) -> dict[str, object]:
        return next(
            row["record"]
            for row in rows
            if row["id"] == f"noaa_nclimgrid_daily_202501:{fips}:{day}:PRCP"
        )

    first = prcp("01009", "2025-01-01")
    second = prcp("01009", "2025-01-02")
    assert first["coverage_status"] == "PARTIAL_COVERAGE"
    assert first["value"] is None
    assert 0 < first["source_coverage_fraction"] < 1
    assert 0 < first["valid_fraction_of_supported_area"] < 0.95
    assert second["coverage_status"] == "COMPLETE"
    assert second["source_coverage_fraction"] == pytest.approx(first["source_coverage_fraction"])
    assert second["valid_fraction_of_supported_area"] == 1
    assert prcp("01005", "2025-01-01")["coverage_status"] == "SOURCE_MISSING"
    assert prcp("01001", "2025-01-01")["value"] == 0
    assert prcp("02013", "2025-01-01")["coverage_status"] == "OUT_OF_SOURCE_COVERAGE"
    assert prcp("15001", "2025-01-01")["coverage_status"] == "OUT_OF_SOURCE_COVERAGE"


def test_fresh_process_resume_uses_both_retained_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.nclimgrid_daily.load_tiger_counties",
        lambda *args, **kwargs: _counties(),
    )
    fixture = tmp_path / "fixtures"
    fixture.mkdir()
    (fixture / "nclimgrid-scaled.nc").write_bytes(_netcdf(tmp_path / "fixture.nc"))
    (fixture / "tl_2025_us_county.zip").write_bytes(b"fixture-tiger")
    store_path = tmp_path / "runs"
    first = IngestionOrchestrator(FileCheckpointStore(store_path), fixture_dir=fixture).run(
        DEFINITION, tier=Tier.A, fail_after_stage="ACQUIRE"
    )
    assert first.status is RunStatus.FAILED
    monkeypatch.setattr(
        NClimGridDailyAdapter,
        "acquire",
        lambda *args, **kwargs: pytest.fail("resume reacquired a member"),
    )
    resumed = IngestionOrchestrator(FileCheckpointStore(store_path)).resume(
        first.ingestion_run_id, definition=DEFINITION
    )
    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.checkpoint("NORMALIZE") is not None
    acquisition = resumed.checkpoint("ACQUIRE")
    assert acquisition.completed_at is not None
    assert acquisition.completed_at[:10] != "2025-01-01"
    assert len(acquisition.detail["artifacts"]) == 2
    assert acquisition.detail["upstream_last_modified"] is None


def test_partial_partition_resume_is_run_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    counties = {
        f"01{index:03d}": _county(
            f"01{index:03d}",
            -100 - STEP / 2,
            30 - STEP / 2,
            -100 + STEP / 2,
            30 + STEP / 2,
        )
        for index in range(1, 41)
    }
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.nclimgrid_daily.load_tiger_counties",
        lambda *args, **kwargs: counties,
    )
    fixture = tmp_path / "fixtures"
    fixture.mkdir()
    (fixture / "nclimgrid-scaled.nc").write_bytes(_netcdf(tmp_path / "fixture.nc"))
    (fixture / "tl_2025_us_county.zip").write_bytes(b"fixture-tiger")
    store_path = tmp_path / "runs"
    original_records = NClimGridDailyAdapter._records

    def interrupted_records(
        self: NClimGridDailyAdapter, definition: object, inputs: object
    ) -> object:
        for index, row in enumerate(original_records(self, definition, inputs)):
            if index == 251:
                raise ValueError("injected normalize interruption")
            yield row

    monkeypatch.setattr(NClimGridDailyAdapter, "_records", interrupted_records)
    first = IngestionOrchestrator(FileCheckpointStore(store_path), fixture_dir=fixture).run(
        DEFINITION, tier=Tier.A
    )
    assert first.status is RunStatus.FAILED
    assert len(tuple(FileCheckpointStore(store_path).iter_partitions(first.ingestion_run_id))) == 1
    monkeypatch.setattr(NClimGridDailyAdapter, "_records", original_records)
    monkeypatch.setattr(
        NClimGridDailyAdapter,
        "acquire",
        lambda *args, **kwargs: pytest.fail("resume reacquired a member"),
    )
    resumed = IngestionOrchestrator(FileCheckpointStore(store_path)).resume(
        first.ingestion_run_id, definition=DEFINITION
    )
    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.checkpoint("NORMALIZE").detail["record_count"] == 31 * 4 * 40
    assert len(tuple(FileCheckpointStore(store_path).iter_partitions(first.ingestion_run_id))) == 20


def test_climate_quality_and_compatibility_contract() -> None:
    packaged = (
        files("lyme_gap_atlas_data").joinpath("data/canonical-county-fips-2022.txt").read_bytes()
    )
    governed = (
        ROOT / "docs/contracts/county-identity-geometry/canonical-county-fips-2022.txt"
    ).read_bytes()
    assert packaged == governed
    document = json.loads(
        (ROOT / "docs/contracts/climate/nclimgrid-semantic-measures-v1.json").read_text(
            encoding="utf-8"
        )
    )
    measures = document["measures"]
    validate_measures(measures)
    assert {measure["measure_id"] for measure in measures} == {
        f"nclimgrid_{name}_county_day" for name in ("prcp", "tmin", "tmax", "tavg")
    }
    changed_grain = {**measures[0], "geography_grain": "SITE_EVENT", "semantic_version": "2.0.0"}
    changed_time = {
        **measures[0],
        "temporal_semantics": "POINT_IN_TIME",
        "semantic_version": "2.0.0",
    }
    assert (
        compare_measure(measures[0], changed_grain).outcome is Outcome.REQUIRES_NEW_SEMANTIC_VERSION
    )
    assert (
        compare_measure(measures[0], changed_time).outcome is Outcome.REQUIRES_NEW_SEMANTIC_VERSION
    )
    assert not validate_source_definition(
        replace(
            DEFINITION, endpoint_template=DEFINITION.endpoint_template.replace("scaled", "prelim")
        )
    ).ok
    assert not validate_source_definition(
        replace(DEFINITION, geography_semantics="ALL_US_COUNTY")
    ).ok


def test_source_metadata_drift_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "drift.nc"
    _netcdf(path)
    with h5netcdf.File(path, "r+") as file:
        file.variables["prcp"].attrs["units"] = "inch"
    assert not NClimGridDailyAdapter().validate_payload(DEFINITION, _inputs(path.read_bytes())).ok
    with h5netcdf.File(path, "r+") as file:
        file.variables["prcp"].attrs["units"] = "millimeter"
        file.attrs["product_version"] = "v2-0-0"
    assert not NClimGridDailyAdapter().validate_payload(DEFINITION, _inputs(path.read_bytes())).ok


def test_climate_semantic_mapping_preserves_value_and_two_member_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.nclimgrid_daily.load_tiger_counties",
        lambda *args, **kwargs: _counties(),
    )
    rows = list(
        NClimGridDailyAdapter()
        .normalize_iter(DEFINITION, _inputs(_netcdf(tmp_path / "semantic.nc")))
        .records
    )
    mappings = load_mapping_registry(
        ROOT / "docs/contracts/semantic-domain/atlas-semantic-source-mappings-v1.json"
    )
    mapping = mappings["nclimgrid_prcp"]
    assert mapping["measure_id"] == "nclimgrid_prcp_county_day"
    for fips, expected in (
        ("01001", (0, "ZERO")),
        ("01003", (None, "OBSERVED")),
        ("01005", (None, "MISSING")),
        ("02013", (None, "UNAVAILABLE")),
    ):
        output = next(
            row["record"]
            for row in rows
            if row["id"] == f"noaa_nclimgrid_daily_202501:{fips}:2025-01-01:PRCP"
        )
        value, state = expected
        if fips == "01003":
            value = output["value"]
            expected = (value, state)
        record = {
            "source_output": output,
            "value": value,
            "value_state": state,
            "unit": "mm",
            "geography": {"grain": "COUNTY", "county_fips": fips},
            "temporal": {"semantics": "PERIOD", "start": "2025-01-01", "end": "2025-01-01"},
        }
        edges = [
            {"artifact_sha256": output["noaa_sha256"], "ingestion_run_id": "run-1"},
            {"artifact_sha256": output["tiger_sha256"], "ingestion_run_id": "run-1"},
        ]
        assert _source_value(record, mapping) == expected
        _check_output_scope(record, mapping, edges)
        if fips == "01003":
            with pytest.raises(SemanticMappingError):
                _check_output_scope(
                    {
                        **record,
                        "source_output": {**output, "source_coverage_fraction": 1.0},
                    },
                    mapping,
                    edges,
                )
        if fips == "02013":
            with pytest.raises(SemanticMappingError):
                _check_output_scope(
                    {**record, "source_output": {**output, "coverage_status": "SOURCE_MISSING"}},
                    mapping,
                    edges,
                )
        with pytest.raises(SemanticMappingError):
            _check_output_scope(
                {
                    **record,
                    "temporal": {"semantics": "PERIOD", "start": "2025-01-01", "end": "2025-01-31"},
                },
                mapping,
                edges,
            )
