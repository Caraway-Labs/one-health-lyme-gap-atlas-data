"""Disk mosaic calculations retain the frozen tile scientific behavior."""

from __future__ import annotations

import hashlib
import zipfile
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from rasterio.io import MemoryFile
from test_annual_nlcd import DEFINITION, _county, _inputs

from lyme_gap_atlas_data.ingestion.annual_nlcd import PRODUCTS, AnnualNLCDAdapter, _name
from lyme_gap_atlas_data.ingestion.annual_nlcd_mosaic import (
    aggregate_county,
    deadline,
    exclusive,
    extract_retained,
    validate_grid,
    validate_values,
)


@pytest.mark.parametrize("partial", [False, True])
def test_mosaic_matches_frozen_tile_all_seven_measures(partial: bool) -> None:
    inputs = _inputs(impervious=[[0, 50], [100, 250 if not partial else 0]])
    county = _county()
    expected = list(AnnualNLCDAdapter()._county_records(DEFINITION, county, 2025, inputs))
    with ExitStack() as stack:
        datasets = {}
        for product in PRODUCTS:
            memory = stack.enter_context(
                MemoryFile(inputs.payloads[_name("H14V15", product, "tif")])
            )
            datasets[product] = stack.enter_context(memory.open())
        validate_grid(datasets, fixture=True)
        actual = aggregate_county(county, datasets, "local-lineage")
    assert len(actual) == 7
    for row, frozen in zip(actual, expected, strict=True):
        record = frozen["record"]
        for key in (
            "measure",
            "value",
            "coverage_status",
            "expected_area_m2",
            "intersected_area_m2",
            "source_supported_area_m2",
            "valid_area_m2",
            "source_coverage_fraction",
            "valid_fraction_of_supported_area",
            "native_class_area_m2",
        ):
            assert row[key] == record[key]


def test_ak_hi_are_explicit_nulls_without_reading_rasters() -> None:
    for fips in ("02013", "15001"):
        rows = aggregate_county(replace(_county(), county_fips=fips), {}, "lineage")
        assert len(rows) == 7
        assert all(
            row["value"] is None and row["coverage_status"] == "OUT_OF_SOURCE_COVERAGE"
            for row in rows
        )


@pytest.mark.parametrize("product,value", [("LndCov", 0), ("FctImp", 101), ("LndChg", 4141)])
def test_unknown_source_codes_fail_closed(product: str, value: int) -> None:
    with pytest.raises(ValueError):
        validate_values(product, np.array([[value]]))


def test_zero_and_nodata_are_distinct() -> None:
    validate_values("FctImp", np.array([[0, 250]]))
    validate_values("LndCov", np.array([[11, 250]]))
    validate_values("LndChg", np.array([[41, 4121, 9999]]))


@pytest.mark.parametrize("missing", [False, True])
def test_zero_aggregate_is_not_source_missing(missing: bool) -> None:
    inputs = _inputs(
        cover=[[250, 250], [250, 250]] if missing else [[41, 41], [41, 41]],
        impervious=[[250, 250], [250, 250]] if missing else [[0, 0], [0, 0]],
        change=[[9999, 9999], [9999, 9999]] if missing else [[41, 41], [41, 41]],
    )
    with ExitStack() as stack:
        datasets = {}
        for product in PRODUCTS:
            memory = stack.enter_context(
                MemoryFile(inputs.payloads[_name("H14V15", product, "tif")])
            )
            datasets[product] = stack.enter_context(memory.open())
        rows = aggregate_county(_county(), datasets, "lineage")
    if missing:
        assert all(
            row["value"] is None and row["coverage_status"] == "SOURCE_MISSING" for row in rows
        )
    else:
        assert (
            next(row for row in rows if row["measure"] == "MEAN_IMPERVIOUS_FRACTION")["value"] == 0
        )
        assert all(row["coverage_status"] == "COMPLETE" for row in rows)


def test_official_mosaic_dimensions_are_not_tile_dimensions() -> None:
    inputs = _inputs()
    with ExitStack() as stack:
        datasets = {}
        for product in PRODUCTS:
            memory = stack.enter_context(
                MemoryFile(inputs.payloads[_name("H14V15", product, "tif")])
            )
            datasets[product] = stack.enter_context(memory.open())
        with pytest.raises(ValueError, match="mosaic grid changed"):
            validate_grid(datasets)


def test_extraction_is_exact_hash_bound_and_never_overwrites(tmp_path: Path) -> None:
    payload = b"retained source file"
    with zipfile.ZipFile(tmp_path / "source.zip", "w") as archive:
        archive.writestr("source.tif", payload)
    records = {
        "source": {
            "source": {"url": "https://example.org/source.zip"},
            "members": [
                {
                    "name": "source.tif",
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            ],
        }
    }
    output = tmp_path / "extracted"
    extract_retained(records, tmp_path, output, lambda: None)
    extract_retained(records, tmp_path, output, lambda: None)
    (output / "source.tif").write_bytes(b"changed")
    with pytest.raises(ValueError, match="never overwrite"):
        extract_retained(records, tmp_path, output, lambda: None)
    assert (output / "source.tif").read_bytes() == b"changed"


def test_unsafe_member_and_concurrent_owner_block(tmp_path: Path) -> None:
    records = {"source": {"members": [{"name": "../escape", "bytes": 1}]}}
    with pytest.raises(ValueError, match="Unsafe"):
        extract_retained(records, tmp_path, tmp_path / "out", lambda: None)
    lock = tmp_path / "lock"
    with exclusive(lock), pytest.raises(FileExistsError), exclusive(lock):
        pass
    assert not lock.exists()


def test_deadline_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    current = [0.0]
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.annual_nlcd_mosaic.time.monotonic", lambda: current[0]
    )
    check = deadline(1)
    current[0] = 1.0
    with pytest.raises(TimeoutError):
        check()
    with pytest.raises(ValueError):
        deadline(1801)
