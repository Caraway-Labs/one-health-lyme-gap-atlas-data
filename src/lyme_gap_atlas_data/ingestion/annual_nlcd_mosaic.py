"""Offline, disk-backed 2025 MRLC calculation; no acquisition or database effects.

This is a local scientific calculation handoff, not a SourceDefinition adapter
registration or a substitute for governed artifact/source admission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import shutil
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from importlib import import_module
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

import numpy as np
import pyproj
import rasterio  # type: ignore[import-untyped]
import shapely
from rasterio.windows import Window, from_bounds  # type: ignore[import-untyped]
from shapely.geometry import box

from ..county_analysis_geometry import (
    SELECTED_ARTIFACT_SHA256,
    WEIGHT_VERSION,
    CountyAnalysisGeometry,
    load_tiger_counties,
    project_geometry,
)
from ..mrlc_storage_staging import MANIFEST_SHA256, canonical, captured, validate_manifest
from ..nlcd_storage_staging import Limits
from .annual_nlcd import (
    CLASSES,
    GROUPS,
    MEASURES,
    NODATA,
    PRODUCT_TITLES,
    PRODUCTS,
    _change_code,
    _pixel_weights,
    _raster_metadata,
)
from .checkpoints import FileCheckpointStore
from .partitioning import partition_records

TRANSFORM_VERSION = "atlas-annual-nlcd-mrlc-local-county/1"
EXPECTED_GRID = (160000, 105000, (30.0, 0.0, -2415585.0, 0.0, -30.0, 3314805.0))
MAX_EXPANDED_BYTES = 4_335_547_988
WINDOW = 256  # Existing #196 weight/window algorithm, unchanged.
CAPTURE_RECEIPT_SHA256 = "d647adfb5bcd03dd2ad62ef054b0c806ca35b394e4a776e3a6c24ac2bcd909b8"


@contextmanager
def exclusive(path: Path) -> Iterator[None]:
    with path.open("x"):
        pass
    try:
        yield
    finally:
        path.unlink()


def digest_file(path: Path, check: Callable[[], None] = lambda: None) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Regular retained file required")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            check()
            digest.update(chunk)
    return digest.hexdigest()


def deadline(seconds: int) -> Callable[[], None]:
    if not 1 <= seconds <= 1800:
        raise ValueError("Local attempt requires 1-1800 seconds")
    end = time.monotonic() + seconds

    def check() -> None:
        if time.monotonic() >= end:
            raise TimeoutError("Local calculation deadline; completed partitions retained")

    return check


def extract_retained(
    records: dict[str, Any], capture: Path, output: Path, check: Callable[[], None]
) -> None:
    """Extract only exact receipt-listed plain members, verifying every full hash."""
    inventory = [member for record in records.values() for member in record["members"]]
    if sum(member["bytes"] for member in inventory) > MAX_EXPANDED_BYTES:
        raise ValueError("Expanded input bound exceeded")
    names = [member["name"] for member in inventory]
    if len(set(names)) != len(names) or any(Path(name).name != name for name in names):
        raise ValueError("Unsafe or duplicate member name")
    output.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise ValueError("Owned extraction directory required")
    remaining = sum(
        member["bytes"] for member in inventory if not (output / member["name"]).exists()
    )
    if shutil.disk_usage(output).free < remaining + 1_000_000_000:
        raise ValueError("Insufficient local extraction space plus 1 GB reserve")
    for record in records.values():
        package = capture / Path(record["source"]["url"]).name
        with zipfile.ZipFile(package) as archive:
            for member in record["members"]:
                check()
                target = output / member["name"]
                if target.exists():
                    if (
                        target.stat().st_size != member["bytes"]
                        or digest_file(target, check) != member["sha256"]
                    ):
                        raise ValueError("Existing extracted member mismatch; never overwrite")
                    continue
                partial = target.with_name(target.name + ".part")
                digest = hashlib.sha256()
                total = 0
                with archive.open(member["name"]) as source, partial.open("xb") as destination:
                    while chunk := source.read(8 * 1024 * 1024):
                        check()
                        total += len(chunk)
                        if total > member["bytes"]:
                            raise ValueError("Expanded member exceeds pinned size")
                        digest.update(chunk)
                        destination.write(chunk)
                if total != member["bytes"] or digest.hexdigest() != member["sha256"]:
                    raise ValueError("Extracted member checksum mismatch")
                partial.replace(target)


def validate_grid(datasets: dict[str, Any], *, fixture: bool = False) -> dict[str, object]:
    reference: tuple[object, ...] | None = None
    for product in PRODUCTS:
        dataset = datasets[product]
        # Reuse all native dtype/nodata/CRS/scale/resolution checks; dimensions are
        # independently pinned here to the actual mosaic, never called a tile.
        _raster_metadata(dataset, product, fixture=True)
        grid = (dataset.width, dataset.height, tuple(dataset.transform)[:6], dataset.crs.to_wkt())
        if not fixture and grid[:3] != EXPECTED_GRID:
            raise ValueError("2025 official MRLC mosaic grid changed")
        if reference is not None and grid != reference:
            raise ValueError("Mosaic product grids disagree")
        reference = grid
    assert reference is not None
    return {"grid": reference, "sha256": hashlib.sha256(canonical(reference)).hexdigest()}


def validate_values(product: str, values: np.ndarray) -> None:
    for item in np.unique(values).tolist():
        code = int(item)
        if code == NODATA[product]:
            continue
        if product == "LndCov" and code not in CLASSES:
            raise ValueError(f"Unapproved land-cover code {code}")
        if product == "FctImp" and not 0 <= code <= 100:
            raise ValueError(f"Impervious percent outside 0-100: {code}")
        if product == "LndChg":
            _change_code(code)


def aggregate_county(
    county: CountyAnalysisGeometry,
    datasets: dict[str, Any],
    lineage_id: str,
    check: Callable[[], None] = lambda: None,
) -> list[dict[str, object]]:
    """Use the frozen #196 formulas and #424 exact boundary cell weights."""
    expected = project_geometry(
        county.geometry, county.lineage.storage_crs, county.analysis_crs
    ).area
    common: dict[str, object] = {
        "county_fips": county.county_fips,
        "mapping_year": 2025,
        "collection_version": "C1V2",
        "unit": "fraction",
        "denominator": "valid_source_supported_area_m2",
        "lineage_id": lineage_id,
        "geometry_digest": county.lineage.normalized_geometry_sha256,
        "geometry_version": county.lineage.transform_version,
        "weight_version": WEIGHT_VERSION,
        "transformation_version": TRANSFORM_VERSION,
        "expected_area_m2": expected,
    }
    if county.county_fips.startswith(("02", "15")):
        return [
            {
                **common,
                "measure": measure,
                "expected_area_m2": None,
                "value": None,
                "coverage_status": "OUT_OF_SOURCE_COVERAGE",
                "intersected_area_m2": None,
                "source_supported_area_m2": None,
                "valid_area_m2": None,
                "source_coverage_fraction": None,
                "valid_fraction_of_supported_area": None,
                "native_class_area_m2": {},
            }
            for measure in MEASURES
        ]
    reference = datasets["LndCov"]
    native = project_geometry(county.geometry, county.lineage.storage_crs, reference.crs.to_wkt())
    if native.difference(box(*reference.bounds)).area > native.area * 1e-8:
        raise ValueError("Mosaic envelope leaves a legal county gap")
    raw = from_bounds(*native.bounds, transform=reference.transform)
    # Include the outer neighboring cells; geometric intersection, not a
    # rasterized candidate mask, decides whether they contribute area.
    col0, row0 = max(0, math.floor(raw.col_off) - 1), max(0, math.floor(raw.row_off) - 1)
    col1 = min(reference.width, math.ceil(raw.col_off + raw.width) + 1)
    row1 = min(reference.height, math.ceil(raw.row_off + raw.height) + 1)
    areas: dict[str, dict[int, float]] = {product: defaultdict(float) for product in PRODUCTS}
    valid = dict.fromkeys(PRODUCTS, 0.0)
    intersected = supported = impervious_sum = 0.0
    for row in range(row0, row1, WINDOW):
        for col in range(col0, col1, WINDOW):
            check()
            window = Window(col, row, min(WINDOW, col1 - col), min(WINDOW, row1 - row))
            weights = _pixel_weights(county, reference, window)
            if not weights.any():
                continue
            values = {product: datasets[product].read(1, window=window) for product in PRODUCTS}
            for product in PRODUCTS:
                validate_values(product, values[product])
            masks = {product: values[product] != NODATA[product] for product in PRODUCTS}
            intersected += float(np.sum(weights))
            supported += float(np.sum(weights[masks["LndCov"] | masks["FctImp"] | masks["LndChg"]]))
            for product in PRODUCTS:
                product_weights = weights[masks[product]]
                product_values = values[product][masks[product]]
                valid[product] += float(np.sum(product_weights))
                if product == "FctImp":
                    impervious_sum += float(np.dot(product_weights, product_values.astype(float)))
                else:
                    for code in np.unique(product_values):
                        areas[product][int(code)] += float(np.sum(weights[values[product] == code]))
    if intersected > expected * (1 + 1e-8) or supported > expected * (1 + 1e-8):
        raise ValueError("Pixel or supported areas exceed frozen county area")
    intersected, supported = min(intersected, expected), min(supported, expected)
    output: list[dict[str, object]] = []
    for measure in MEASURES:
        product = (
            "FctImp"
            if measure == "MEAN_IMPERVIOUS_FRACTION"
            else "LndChg"
            if measure == "LAND_COVER_CHANGED_AREA_SHARE"
            else "LndCov"
        )
        if valid[product] > supported * (1 + 1e-8):
            raise ValueError("Valid area exceeds union source support")
        product_valid = min(valid[product], supported)
        fraction = product_valid / supported if supported else None
        value: float | None = None
        if not supported:
            status = "SOURCE_MISSING"
        elif fraction is None or fraction + 1e-12 < 1:
            status = "PARTIAL_COVERAGE"
        else:
            status = "COMPLETE"
            if product == "LndCov":
                value = (
                    math.fsum(areas[product].get(code, 0.0) for code in GROUPS[measure])
                    / product_valid
                )
            elif product == "FctImp":
                value = impervious_sum / product_valid / 100
            else:
                value = (
                    math.fsum(area for code, area in areas[product].items() if _change_code(code))
                    / product_valid
                )
        if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
            raise ValueError("Aggregate fraction outside 0-1")
        output.append(
            {
                **common,
                "measure": measure,
                "value": value,
                "coverage_status": status,
                "source_product": product,
                "source_unit": "percent" if product == "FctImp" else "categorical_class_code",
                "change_period": "2024->2025" if product == "LndChg" else None,
                "intersected_area_m2": intersected,
                "source_supported_area_m2": supported,
                "valid_area_m2": product_valid,
                "source_coverage_fraction": supported / expected,
                "valid_fraction_of_supported_area": fraction,
                "native_class_area_m2": {
                    str(code): area for code, area in sorted(areas[product].items())
                },
            }
        )
    return output


def prepare(capture: Path, extracted: Path, manifest: Path, seconds: int) -> None:
    check = deadline(seconds)
    members = json.loads(manifest.read_text(encoding="utf-8-sig"))
    validate_manifest(members)
    extracted.mkdir(parents=True, exist_ok=True)
    with exclusive(extracted / "prepare.lock"):
        try:
            if digest_file(capture / "mrlc-capture-receipt.json", check) != CAPTURE_RECEIPT_SHA256:
                raise ValueError("Exact reviewed local capture receipt required")
            records = captured(members, capture, Limits())
            extract_retained(records, capture, extracted, check)
            receipt = capture / "mrlc-capture-receipt.json"
            retained_receipt = extracted / receipt.name
            if not retained_receipt.exists():
                with retained_receipt.open("xb") as handle:
                    handle.write(receipt.read_bytes())
            if digest_file(retained_receipt, check) != CAPTURE_RECEIPT_SHA256:
                raise ValueError("Retained capture receipt changed")
            document = {
                "distribution": "OFFICIAL_MRLC_HTTPS_ZIP",
                "manifest_sha256": MANIFEST_SHA256,
                "packages": records,
                "capture_receipt_sha256": digest_file(capture / "mrlc-capture-receipt.json", check),
            }
            path = extracted / "verified-inputs.json"
            content = canonical(document)
            if path.exists() and path.read_bytes() != content:
                raise ValueError("Existing input manifest differs")
            if not path.exists():
                with path.open("xb") as handle:
                    handle.write(content)
        finally:
            check()


def calculate(
    extracted: Path,
    tiger: Path,
    output: Path,
    selected: list[str],
    maximum_counties: int,
    seconds: int,
    code_revision: str,
) -> dict[str, object]:
    if not 1 <= maximum_counties <= 128:
        raise ValueError("An invocation requires 1-128 new counties")
    if re.fullmatch(r"[a-f0-9]{40}", code_revision) is None:
        raise ValueError("Exact reviewed calculation Git revision required")
    check = deadline(seconds)
    started = time.monotonic()
    document = json.loads((extracted / "verified-inputs.json").read_text())
    if document.get("manifest_sha256") != MANIFEST_SHA256:
        raise ValueError("Wrong source distribution manifest")
    records = document["packages"]
    if document.get("capture_receipt_sha256") != CAPTURE_RECEIPT_SHA256:
        raise ValueError("Unreviewed capture receipt")
    receipt = extracted / "mrlc-capture-receipt.json"
    if digest_file(receipt, check) != CAPTURE_RECEIPT_SHA256:
        raise ValueError("Retained capture receipt changed")
    if records != json.loads(receipt.read_bytes())["packages"]:
        raise ValueError("Input members differ from exact captured receipt")
    by_product = {record["source"]["product"]: record for record in records.values()}
    if set(by_product) != set(PRODUCTS) or len(records) != 3:
        raise ValueError("Exactly three frozen products required")
    validate_manifest([by_product[product]["source"] for product in PRODUCTS])
    paths: dict[str, Path] = {}
    for record in records.values():
        for member in record["members"]:
            path = extracted / member["name"]
            if (
                path.stat().st_size != member["bytes"]
                or digest_file(path, check) != member["sha256"]
            ):
                raise ValueError("Retained extracted member changed")
            if member["name"].endswith(".tif"):
                paths[record["source"]["product"]] = path
            if member["name"].endswith(".xml") and not member["name"].endswith(".aux.xml"):
                xml = ET.fromstring(path.read_bytes())
                title = xml.findtext("./idinfo/citation/citeinfo/title", "")
                if (
                    PRODUCT_TITLES[record["source"]["product"]] not in title
                    or "ver. 1.2" not in title
                    or "Conterminous United States" not in title
                    or xml.findtext("./idinfo/citation/citeinfo/pubdate") != "20260630"
                ):
                    raise ValueError("Product/version metadata changed")
    if digest_file(tiger, check) != SELECTED_ARTIFACT_SHA256:
        raise ValueError("Frozen TIGER artifact changed")
    canonical_fips = (
        files("lyme_gap_atlas_data")
        .joinpath("data/canonical-county-fips-2022.txt")
        .read_text()
        .splitlines()
    )
    counties = load_tiger_counties(tiger.read_bytes(), canonical_fips)
    selected = sorted(selected or counties)
    if len(set(selected)) != len(selected) or any(fips not in counties for fips in selected):
        raise ValueError("Unknown or duplicate county")
    output.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise ValueError("Owned result directory required")
    if shutil.disk_usage(output).free < 1_000_000_000:
        raise ValueError("Local result disk reserve unavailable")
    if sum(path.stat().st_size for path in output.rglob("*") if path.is_file()) > 256_000_000:
        raise ValueError("Local compact result budget exceeded")
    with exclusive(output / "calculation.lock"), ExitStack() as stack:
        try:
            stack.enter_context(rasterio.Env(GDAL_CACHEMAX=64 * 1024 * 1024, GDAL_NUM_THREADS="1"))
            datasets = {
                product: stack.enter_context(rasterio.open(paths[product])) for product in PRODUCTS
            }
            grid = validate_grid(datasets)
            lineage = {
                "input_manifest_sha256": digest_file(extracted / "verified-inputs.json", check),
                "source": document,
                "tiger_sha256": SELECTED_ARTIFACT_SHA256,
                "software": {
                    "python": platform.python_version(),
                    "numpy": np.__version__,
                    "rasterio": rasterio.__version__,
                    "gdal": rasterio.__gdal_version__,
                    "pyproj": pyproj.__version__,
                    "shapely": shapely.__version__,
                },
                "calculation_code_sha256": digest_file(Path(__file__), check),
                "weight_code_sha256": digest_file(
                    Path(__file__).with_name("annual_nlcd.py"), check
                ),
                "geometry_code_sha256": digest_file(
                    Path(__file__).parents[1] / "county_analysis_geometry.py", check
                ),
                "transform": TRANSFORM_VERSION,
                "code_revision": code_revision,
                "grid": grid,
                "selected_counties": selected,
                "scope": "LOCAL_CALCULATION_ONLY_NOT_GOVERNED_SOURCE_ADMISSION",
            }
            lineage_id = hashlib.sha256(canonical(lineage)).hexdigest()
            run_id = "mrlc2025_" + lineage_id
            context = output / (run_id + ".lineage.json")
            if not context.exists():
                with context.open("xb") as handle:
                    handle.write(canonical(lineage))
            elif context.read_bytes() != canonical(lineage):
                raise ValueError("Immutable lineage differs")
            store = FileCheckpointStore(output / "partitions")
            completed = {
                partition.ordinal: partition for partition in store.iter_partitions(run_id)
            }
            for ordinal, partition in completed.items():
                if (
                    ordinal >= len(selected)
                    or len(partition.records) != 7
                    or any(
                        row["county_fips"] != selected[ordinal] or row["lineage_id"] != lineage_id
                        for row in partition.records
                    )
                ):
                    raise ValueError("Existing county partition identity differs")
            new_counties = 0
            for ordinal, fips in enumerate(selected):
                if ordinal in completed:
                    continue
                if new_counties >= maximum_counties:
                    break
                check()
                rows = aggregate_county(counties[fips], datasets, lineage_id, check)
                partition = replace(next(partition_records(rows)), ordinal=ordinal)
                store.save_partition(run_id, partition)
                completed[ordinal] = partition
                new_counties += 1
                print(
                    json.dumps(
                        {
                            "county": fips,
                            "completed_counties": len(completed),
                            "elapsed_seconds": time.monotonic() - started,
                        }
                    ),
                    flush=True,
                )
            if len(completed) == len(selected):
                store.complete_partitions(run_id, len(selected))
            report: dict[str, object] = {
                "run_id": run_id,
                "lineage_id": lineage_id,
                "selected_counties": len(selected),
                "eligible_conus_counties": sum(
                    not fips.startswith(("02", "15")) for fips in selected
                ),
                "completed_counties": len(completed),
                "new_counties": new_counties,
                "complete": store.partitions_complete(run_id),
                "elapsed_seconds": time.monotonic() - started,
                "rows": 7 * len(completed),
                "snowflake_operations": 0,
                "source_download_bytes": 0,
            }
            if platform.system() == "Linux":
                resource = cast(Any, import_module("resource"))
                usage = resource.getrusage(resource.RUSAGE_SELF)
                report["peak_rss_bytes"] = usage.ru_maxrss * 1024
                report["cpu_seconds"] = usage.ru_utime + usage.ru_stime
            report_path = output / f"{run_id}.attempt-{time.time_ns()}.json"
            report_path.write_bytes(canonical(report))
            return report
        finally:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "calculate"))
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--extracted", type=Path, required=True)
    parser.add_argument("--tiger", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--counties", default="")
    parser.add_argument("--maximum-counties", type=int, default=16)
    parser.add_argument("--seconds", type=int, default=900)
    parser.add_argument("--code-revision")
    args = parser.parse_args()
    if args.mode == "prepare":
        if args.capture is None or args.manifest is None:
            parser.error("prepare requires capture and manifest")
        prepare(args.capture, args.extracted, args.manifest, args.seconds)
        print("Retained extraction verified")
    else:
        if args.tiger is None or args.output is None or args.code_revision is None:
            parser.error("calculate requires tiger, output and code-revision")
        print(
            json.dumps(
                calculate(
                    args.extracted,
                    args.tiger,
                    args.output,
                    args.counties.split(",") if args.counties else [],
                    args.maximum_counties,
                    args.seconds,
                    args.code_revision,
                )
            )
        )


if __name__ == "__main__":
    main()
