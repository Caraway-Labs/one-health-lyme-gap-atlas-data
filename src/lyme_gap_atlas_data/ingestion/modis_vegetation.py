"""Bounded MOD13Q1.061 county-composite vegetation context."""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

import numpy as np
import requests
from pyhdf.SD import SD, SDC  # type: ignore[import-untyped]
from pyproj import CRS, Transformer
from rasterio.features import rasterize  # type: ignore[import-untyped]
from rasterio.transform import Affine  # type: ignore[import-untyped]
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

COLLECTION_ID = "C1748066515-LPCLOUD"
GRANULE = "MOD13Q1.A2025193.h09v05.061.2025212122804"
CMR_URL = (
    "https://cmr.earthdata.nasa.gov/search/granules.json"
    f"?collection_concept_id={COLLECTION_ID}&granule_ur={GRANULE}&page_size=2"
)
HDF_MEMBER = "mod13q1-061-h09v05-2025193-hdf"
CMR_MEMBER = "mod13q1-061-h09v05-2025193-cmr"
TIGER_MEMBER = "tiger-2025-analysis-county-zip"
MEMBERS = (HDF_MEMBER, CMR_MEMBER, TIGER_MEMBER)
MEASURES = ("MODIS_NDVI_MEAN", "MODIS_EVI_MEAN")
TRANSFORM_VERSION = "atlas-mod13q1-county-composite/1"
HDF_LIMIT = 300_000_000
TIGER_LIMIT = 100_000_000
CMR_LIMIT = 1_000_000
RUN_LIMIT = 384_000_000
HDF_MAGIC = b"\x0e\x03\x13\x01"
CRS_SIN = CRS.from_proj4("+proj=sinu +R=6371007.181 +nadgrids=@null +wktext")
SDS = {
    "ndvi": "250m 16 days NDVI",
    "evi": "250m 16 days EVI",
    "qa": "250m 16 days VI Quality",
    "reliability": "250m 16 days pixel reliability",
    "doy": "250m 16 days composite day of the year",
}


def validate_definition(definition: SourceDefinition) -> list[ValidationIssue]:
    extra = definition.extra
    issues: list[ValidationIssue] = []
    pins = (
        definition.endpoint_template == CMR_URL
        and extra.get("collection_concept_id") == COLLECTION_ID
        and extra.get("granule_ur") == GRANULE
        and extra.get("county_fips") == ["48081"]
        and extra.get("tile_id") == "h09v05"
        and extra.get("tiger_url") == SOURCE_URL
        and extra.get("tiger_sha256") == SELECTED_ARTIFACT_SHA256
    )
    if not pins:
        issues.append(
            ValidationIssue("MOD13_PIN", "Exact CMR granule, tile, county and TIGER pins required")
        )
    if (
        definition.geography_semantics != "CONUS_COUNTY_FIPS_2025_ANALYSIS"
        or definition.temporal_semantics != "COUNTY_16_DAY_COMPOSITE"
        or tuple(extra.get("measures", ())) != MEASURES
    ):
        issues.append(
            ValidationIssue("MOD13_GRAIN", "Exact county-composite NDVI/EVI measures required")
        )
    if extra.get("minimum_qa_valid_fraction_of_supported_area") != 0.99:
        issues.append(
            ValidationIssue("MOD13_COMPLETENESS", "QA-valid supported area threshold is 0.99")
        )
    if (
        extra.get("hdf_max_bytes") != HDF_LIMIT
        or extra.get("tiger_max_bytes") != TIGER_LIMIT
        or extra.get("run_max_bytes") != RUN_LIMIT
    ):
        issues.append(
            ValidationIssue("MOD13_BOUNDS", "Reviewed per-member and per-run bounds required")
        )
    return issues


@dataclass(frozen=True)
class RetainedInputs:
    payloads: dict[str, bytes]
    sha256: dict[str, str]
    artifact_ids: dict[str, str]
    object_metadata: dict[str, str | int | None]
    retrieved_at: str | None
    fixture: bool = False


def _bounded_get(
    session: requests.Session, url: str, maximum: int, *, magic: bytes | None = None
) -> tuple[bytes, dict[str, str | int | None]]:
    try:
        with session.get(url, stream=True, timeout=(30, 120)) as response:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            if "html" in content_type or "xml" in content_type:
                raise AcquisitionError(
                    "Source returned a document instead of binary data", code="MOD13_CONTENT"
                )
            length_text = response.headers.get("Content-Length")
            length = int(length_text) if length_text is not None else None
            encoded = bool(response.headers.get("Content-Encoding"))
            if length is not None and length > maximum:
                raise AcquisitionError("Source artifact exceeds reviewed bound", code="MOD13_SIZE")
            chunks: list[bytes] = []
            count = 0
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                count += len(chunk)
                if count > maximum:
                    raise AcquisitionError(
                        "Source artifact exceeds reviewed bound", code="MOD13_SIZE"
                    )
                chunks.append(chunk)
            payload = b"".join(chunks)
            if length is not None and not encoded and count != length:
                raise AcquisitionError("Source content length changed", code="MOD13_LENGTH")
            if magic is not None and not payload.startswith(magic):
                raise AcquisitionError("Source response is not HDF4 binary", code="MOD13_BINARY")
            return payload, {
                "content_length": None if encoded else length,
                "content_type": content_type,
                "last_modified": response.headers.get("Last-Modified"),
            }
    except requests.RequestException as error:
        raise AcquisitionError("MOD13Q1 source acquisition failed", code="MOD13_GET") from error


def _cmr_entry(payload: bytes) -> dict[str, Any]:
    doc = json.loads(payload)
    entries = doc["feed"]["entry"]
    if len(entries) != 1:
        raise ValueError("CMR must resolve exactly one pinned granule")
    entry = entries[0]
    if (
        entry["title"] != GRANULE
        or entry["collection_concept_id"] != COLLECTION_ID
        or entry["time_start"] != "2025-07-12T00:00:00.000Z"
        or entry["time_end"] != "2025-07-27T23:59:59.000Z"
    ):
        raise ValueError("CMR granule identity or observation period changed")
    return cast(dict[str, Any], entry)


def _hdf_url(entry: dict[str, Any]) -> str:
    links = [
        str(link.get("href", ""))
        for link in entry.get("links", [])
        if str(link.get("href", "")).endswith(f"/{GRANULE}.hdf")
        and str(link.get("href", "")).startswith("https://")
        and "data.lpdaac.earthdatacloud.nasa.gov/" in str(link.get("href", ""))
    ]
    if len(set(links)) != 1:
        raise ValueError("CMR lacks one exact LP DAAC HDF download link")
    return links[0]


def _core_value(text: str, key: str) -> str:
    pattern = rf"OBJECT\s*=\s*{key}\s+NUM_VAL\s*=\s*1\s+VALUE\s*=\s*\"?([^\"\n]+)"
    match = re.search(pattern, text)
    if match is None:
        raise ValueError(f"HDF CoreMetadata missing {key}")
    return match.group(1).strip()


def _hdf_metadata(hdf: Any, *, fixture: bool) -> tuple[Affine, dict[str, str]]:
    attrs = hdf.attributes()
    core = str(attrs["CoreMetadata.0"])
    structure = str(attrs["StructMetadata.0"])
    identity = {
        key: _core_value(core, key)
        for key in (
            "SHORTNAME",
            "VERSIONID",
            "LOCALGRANULEID",
            "RANGEBEGINNINGDATE",
            "RANGEENDINGDATE",
            "PRODUCTIONDATETIME",
        )
    }
    if (
        identity["SHORTNAME"] != "MOD13Q1"
        or identity["VERSIONID"] != "61"
        or identity["LOCALGRANULEID"] != f"{GRANULE}.hdf"
        or identity["RANGEBEGINNINGDATE"] != "2025-07-12"
        or identity["RANGEENDINGDATE"] != "2025-07-27"
        or "Projection=GCTP_SNSOID" not in structure
    ):
        raise ValueError("HDF source identity, collection or composite changed")
    ul = re.search(r"UpperLeftPointMtrs=\((-?[\d.]+),(-?[\d.]+)\)", structure)
    lr = re.search(r"LowerRightMtrs=\((-?[\d.]+),(-?[\d.]+)\)", structure)
    radius = re.search(r"ProjParams=\((\d+\.\d+),", structure)
    if (
        ul is None
        or lr is None
        or radius is None
        or not math.isclose(float(radius[1]), 6371007.181)
    ):
        raise ValueError("HDF sinusoidal grid metadata changed")
    width = 4800 if not fixture else hdf.select(SDS["ndvi"]).info()[2][1]
    height = 4800 if not fixture else hdf.select(SDS["ndvi"]).info()[2][0]
    x0, y0 = float(ul[1]), float(ul[2])
    x1, y1 = float(lr[1]), float(lr[2])
    affine = Affine((x1 - x0) / width, 0, x0, 0, (y1 - y0) / height, y0)
    if not fixture and (
        not math.isclose(affine.a, 231.656358, abs_tol=0.001)
        or not math.isclose(affine.e, -231.656358, abs_tol=0.001)
    ):
        raise ValueError("HDF tile pixel resolution changed")
    for kind, name in SDS.items():
        sds = hdf.select(name)
        info = sds.info()
        attrs = sds.attributes()
        expected_dtype = (
            SDC.UINT16 if kind == "qa" else SDC.INT8 if kind == "reliability" else SDC.INT16
        )
        if info[1] != 2 or info[2] != [height, width] or info[3] != expected_dtype:
            raise ValueError(f"{name} dimensions changed")
        if kind in ("ndvi", "evi") and (
            list(attrs.get("valid_range", [])) != [-2000, 10000]
            or attrs.get("_FillValue") != -3000
            or attrs.get("scale_factor") != 10000.0
        ):
            raise ValueError(f"{name} range, fill or scaling changed")
        if kind == "qa" and attrs.get("_FillValue") != 65535:
            raise ValueError("VI Quality fill changed")
        if kind == "qa" and not fixture:
            legend = str(attrs.get("Legend", ""))
            if not all(
                label in legend
                for label in (
                    "MODLAND_QA",
                    "VI usefulness",
                    "Adjacent cloud detected",
                    "Mixed clouds",
                    "Land/Water Flag",
                    "Possible snow/ice",
                    "Possible shadow",
                )
            ):
                raise ValueError("VI Quality bit legend changed")
        if kind in ("reliability", "doy") and attrs.get("_FillValue") != -1:
            raise ValueError(f"{name} fill changed")
        if kind == "reliability" and not fixture:
            legend = str(attrs.get("Legend", ""))
            if not all(
                label in legend for label in ("Good data", "Marginal data", "Snow/Ice", "Cloudy")
            ):
                raise ValueError("pixel reliability legend changed")
        sds.endaccess()
    return affine, identity


def _pixel_weights(
    county: CountyAnalysisGeometry, native_county: Any, affine: Affine, shape: tuple[int, int]
) -> np.ndarray:
    candidate = rasterize([(native_county, 1)], out_shape=shape, transform=affine, all_touched=True)
    boundary = rasterize(
        [(native_county.boundary, 1)], out_shape=shape, transform=affine, all_touched=True
    )
    weights = np.zeros(shape, dtype=np.float64)
    rows, cols = np.nonzero((candidate != 0) & (boundary == 0))
    if len(rows):
        # #424 analysis CRS supplies the area measure. Full cells need no polygon clipping.
        converter = Transformer.from_crs(CRS_SIN, county.analysis_crs, always_xy=True)
        left = affine.c + cols * affine.a
        top = affine.f + rows * affine.e
        x0, y0 = converter.transform(left, top)
        x1, y1 = converter.transform(left + affine.a, top)
        x2, y2 = converter.transform(left + affine.a, top + affine.e)
        x3, y3 = converter.transform(left, top + affine.e)
        weights[rows, cols] = 0.5 * np.abs(
            x0 * y1 + x1 * y2 + x2 * y3 + x3 * y0 - y0 * x1 - y1 * x2 - y2 * x3 - y3 * x0
        )
    edge_rows, edge_cols = np.nonzero((candidate != 0) & (boundary != 0))
    cells = [
        GridCell(
            f"{row}:{col}",
            box(
                affine.c + col * affine.a,
                affine.f + (row + 1) * affine.e,
                affine.c + (col + 1) * affine.a,
                affine.f + row * affine.e,
            ),
            None,
        )
        for row, col in zip(edge_rows.tolist(), edge_cols.tolist(), strict=True)
    ]
    if cells:
        exact = grid_intersection_weights(county, cells, grid_crs=CRS_SIN.to_wkt())
        for cell_id, area in exact.cell_areas_m2:
            row, col = (int(value) for value in cell_id.split(":"))
            weights[row, col] = area
    return weights


def _qa_masks(
    values: dict[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """Retain independent publisher flags and a common strict VI mask."""
    qa = values["qa"].astype(np.uint16)
    reliability = values["reliability"]
    land = ((qa >> 11) & 7) == 1
    supported = (qa != 65535) & land
    cloud = ((qa & 3) == 2) | (((qa >> 8) & 1) == 1) | (((qa >> 10) & 1) == 1) | (reliability == 3)
    snow = (((qa >> 14) & 1) == 1) | (reliability == 2)
    shadow = ((qa >> 15) & 1) == 1
    marginal = ((qa & 3) == 1) | (reliability == 1) | (((qa >> 2) & 15) > 2)
    invalid_vi = (
        (values["ndvi"] < -2000)
        | (values["ndvi"] > 10000)
        | (values["evi"] < -2000)
        | (values["evi"] > 10000)
    )
    invalid_doy = (values["doy"] < 193) | (values["doy"] > 208)
    strict = (
        supported
        & ((qa & 3) == 0)
        & (((qa >> 2) & 15) <= 2)
        & ~cloud
        & ~snow
        & ~shadow
        & (reliability == 0)
        & ~invalid_vi
        & ~invalid_doy
    )
    flags = {
        "qa_fill": qa == 65535,
        "water_or_coast": (qa != 65535) & ~land,
        "cloud": cloud,
        "snow_ice": snow,
        "shadow": shadow,
        "marginal": marginal,
        "vi_fill_or_invalid": invalid_vi,
        "doy_fill_or_invalid": invalid_doy,
    }
    return supported, strict, flags


class ModisVegetationAdapter:
    kind = AdapterKind.MODIS_VEGETATION

    def acquire(
        self, definition: SourceDefinition, *, fixture_dir: Path | None = None
    ) -> AcquireResult:
        if fixture_dir is None:
            with requests.Session() as session:
                cmr, _ = _bounded_get(session, CMR_URL, CMR_LIMIT)
                entry = _cmr_entry(cmr)
                hdf_url = _hdf_url(entry)
                hdf, info = _bounded_get(session, hdf_url, HDF_LIMIT, magic=HDF_MAGIC)
                tiger, _ = _bounded_get(session, SOURCE_URL, TIGER_LIMIT, magic=b"PK\x03\x04")
        else:
            cmr = (fixture_dir / "cmr.json").read_bytes()
            entry = _cmr_entry(cmr)
            hdf_url = _hdf_url(entry)
            hdf = (fixture_dir / f"{GRANULE}.hdf").read_bytes()
            tiger = (fixture_dir / "tl_2025_us_county.zip").read_bytes()
            info = {
                "content_length": len(hdf),
                "content_type": "binary/octet-stream",
                "last_modified": None,
            }
        if not hdf.startswith(HDF_MAGIC) or not tiger.startswith(b"PK\x03\x04"):
            raise AcquisitionError("Retained source member signature changed", code="MOD13_BINARY")
        if (
            len(cmr) > CMR_LIMIT
            or len(hdf) > HDF_LIMIT
            or len(tiger) > TIGER_LIMIT
            or len(cmr) + len(hdf) + len(tiger) > RUN_LIMIT
        ):
            raise AcquisitionError("MOD13Q1 run exceeds reviewed bound", code="MOD13_SIZE")
        if hashlib.sha256(tiger).hexdigest() != SELECTED_ARTIFACT_SHA256 and fixture_dir is None:
            raise AcquisitionError("Approved TIGER artifact changed", code="TIGER_DIGEST")
        artifacts = (
            AcquisitionArtifact(HDF_MEMBER, hdf, "application/x-hdf", hdf_url, "SOURCE_PAYLOAD"),
            AcquisitionArtifact(
                CMR_MEMBER, cmr, "application/json", CMR_URL, "SOURCE_PACKAGE_MEMBER"
            ),
            AcquisitionArtifact(
                TIGER_MEMBER, tiger, "application/zip", SOURCE_URL, "ANALYSIS_REFERENCE"
            ),
        )
        return AcquireResult(
            hdf,
            artifacts[0].sha256,
            "application/x-hdf",
            artifacts=artifacts,
            detail={
                "object_metadata": info,
                "cmr_granule_id": entry["id"],
                "cmr_updated": entry.get("updated"),
                "fixture": fixture_dir is not None,
            },
        )

    def restore_artifacts(
        self, definition: SourceDefinition, run_id: str, store: ArtifactMemberStore
    ) -> RetainedInputs:
        members = {member.name: member for member in store.list_artifact_members(run_id)}
        if set(members) != set(MEMBERS):
            raise ValueError("MOD13Q1 requires exact named HDF, CMR and TIGER members")
        payloads = {name: store.load_artifact_member(run_id, name=name) for name in MEMBERS}
        state = cast(CheckpointStore, store).load(run_id)
        checkpoint = state.checkpoint(Stage.ACQUIRE) if state else None
        detail = checkpoint.detail if checkpoint else {}
        return RetainedInputs(
            payloads,
            {name: members[name].sha256 for name in MEMBERS},
            {name: members[name].artifact_id for name in MEMBERS},
            cast(dict[str, str | int | None], detail.get("object_metadata", {})),
            checkpoint.completed_at if checkpoint else None,
            detail.get("fixture") is True,
        )

    def restore_raw_payload(self, definition: SourceDefinition, raw_payload: bytes) -> Any:
        raise ValueError("MOD13Q1 requires all named run-pinned artifacts")

    def validate_payload(self, definition: SourceDefinition, payload: Any) -> ValidationResult:
        try:
            inputs = self._inputs(payload)
            self._validate(inputs)
        except (KeyError, OSError, TypeError, ValueError) as error:
            return ValidationResult(
                False, [ValidationIssue("MOD13_INVALID", str(error), FailureCategory.SCHEMA)]
            )
        return ValidationResult(True)

    def normalize(self, definition: SourceDefinition, payload: Any) -> NormalizeResult:
        raise TypeError("MOD13Q1 requires bounded streaming normalization")

    def normalize_iter(
        self, definition: SourceDefinition, payload: Any
    ) -> StreamingNormalizeResult:
        inputs = self._inputs(payload)
        return StreamingNormalizeResult(self._records(definition, inputs), TRANSFORM_VERSION)

    @staticmethod
    def _inputs(payload: Any) -> RetainedInputs:
        if not isinstance(payload, RetainedInputs):
            raise TypeError("MOD13Q1 requires retained named artifacts")
        return payload

    @staticmethod
    def _validate(inputs: RetainedInputs) -> None:
        if set(inputs.payloads) != set(MEMBERS) or not inputs.payloads[HDF_MEMBER].startswith(
            HDF_MAGIC
        ):
            raise ValueError("MOD13Q1 member set or HDF signature changed")
        for name in MEMBERS:
            if hashlib.sha256(inputs.payloads[name]).hexdigest() != inputs.sha256[name]:
                raise ValueError(f"{name} replay digest mismatch")
        _hdf_url(_cmr_entry(inputs.payloads[CMR_MEMBER]))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / f"{GRANULE}.hdf"
            path.write_bytes(inputs.payloads[HDF_MEMBER])
            hdf = SD(str(path), SDC.READ)
            try:
                _hdf_metadata(hdf, fixture=inputs.fixture)
            finally:
                hdf.end()
        if not inputs.fixture and inputs.sha256[TIGER_MEMBER] != SELECTED_ARTIFACT_SHA256:
            raise ValueError("Approved TIGER replay digest changed")

    def _records(
        self, definition: SourceDefinition, inputs: RetainedInputs
    ) -> Iterator[dict[str, object]]:
        self._validate(inputs)
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
        county = counties["48081"]
        cmr = _cmr_entry(inputs.payloads[CMR_MEMBER])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / f"{GRANULE}.hdf"
            path.write_bytes(inputs.payloads[HDF_MEMBER])
            hdf = SD(str(path), SDC.READ)
            try:
                affine, core = _hdf_metadata(hdf, fixture=inputs.fixture)
                yield from self._county_rows(definition, inputs, county, cmr, hdf, affine, core)
            finally:
                hdf.end()

    @staticmethod
    def _county_rows(
        definition: SourceDefinition,
        inputs: RetainedInputs,
        county: CountyAnalysisGeometry,
        cmr: dict[str, Any],
        hdf: Any,
        affine: Affine,
        core: dict[str, str],
    ) -> Iterator[dict[str, object]]:
        native_county = project_geometry(
            county.geometry, county.lineage.storage_crs, CRS_SIN.to_wkt()
        )
        shape = hdf.select(SDS["ndvi"]).info()[2]
        width, height = int(shape[1]), int(shape[0])
        west, south, east, north = native_county.bounds
        col0 = max(0, math.floor((west - affine.c) / affine.a))
        col1 = min(width, math.ceil((east - affine.c) / affine.a))
        row0 = max(0, math.floor((north - affine.f) / affine.e))
        row1 = min(height, math.ceil((south - affine.f) / affine.e))
        areas: dict[str, float] = defaultdict(float)
        sums = {"ndvi": 0.0, "evi": 0.0}
        qa_counts: dict[str, int] = defaultdict(int)
        doys: set[int] = set()
        intersected = 0.0
        grid_id = hashlib.sha256(
            f"{GRANULE}:{width}:{height}:{tuple(affine)}:{CRS_SIN.to_wkt()}".encode()
        ).hexdigest()
        for row in range(row0, row1, 128):
            for col in range(col0, col1, 128):
                nr, nc = min(128, row1 - row), min(128, col1 - col)
                window_affine = affine @ Affine.translation(col, row)
                weights = _pixel_weights(county, native_county, window_affine, (nr, nc))
                if not np.any(weights):
                    continue
                values = {
                    kind: np.asarray(hdf.select(name).get(start=(row, col), count=(nr, nc)))
                    for kind, name in SDS.items()
                }
                qa = values["qa"].astype(np.uint16)
                source_supported, strict, categories = _qa_masks(values)
                intersected += float(weights.sum())
                areas["source_supported"] += float(weights[source_supported].sum())
                areas["qa_valid"] += float(weights[strict].sum())
                for category, mask in categories.items():
                    areas[category] += float(weights[mask].sum())
                for bit_value, count in zip(
                    *np.unique(qa[weights > 0], return_counts=True), strict=True
                ):
                    qa_counts[str(int(bit_value))] += int(count)
                if np.any(strict):
                    for kind in ("ndvi", "evi"):
                        sums[kind] += float(
                            np.dot(weights[strict], values[kind][strict].astype(float))
                        )
                    doys.update(int(day) for day in np.unique(values["doy"][strict]))
        expected = project_geometry(
            county.geometry, county.lineage.storage_crs, county.analysis_crs
        ).area
        supported = areas["source_supported"]
        valid = areas["qa_valid"]
        fraction = valid / supported if supported else None
        if intersected == 0 or supported == 0 or intersected / expected < 0.999999:
            status = "SOURCE_MISSING"
        elif fraction is None or fraction + 1e-12 < 0.99:
            status = "PARTIAL_COVERAGE"
        else:
            status = "COMPLETE"
        weight_id = hashlib.sha256(
            f"{grid_id}:{county.lineage.normalized_geometry_sha256}:{county.lineage.artifact_sha256}:{WEIGHT_VERSION}".encode()
        ).hexdigest()
        for measure, kind in ((MEASURES[0], "ndvi"), (MEASURES[1], "evi")):
            record_id = f"{definition.resource_key}:48081:2025-07-12:{measure}"
            yield {
                "id": record_id,
                "source_id": definition.source_id,
                "dataset_id": definition.dataset_id,
                "source_definition_version": definition.definition_version,
                "geography_semantics": definition.geography_semantics,
                "temporal_semantics": definition.temporal_semantics,
                "record": {
                    "id": record_id,
                    "county_fips": "48081",
                    "period_start": core["RANGEBEGINNINGDATE"],
                    "period_end": core["RANGEENDINGDATE"],
                    "measure": measure,
                    "source_variable": SDS[kind],
                    "value": sums[kind] / valid / 10000.0 if status == "COMPLETE" else None,
                    "unit": "unitless_index",
                    "denominator": "qa_valid_source_supported_land_area_m2",
                    "source_scale_divisor": 10000,
                    "coverage_status": status,
                    "expected_area_m2": expected,
                    "intersected_area_m2": intersected,
                    "source_supported_area_m2": supported,
                    "valid_area_m2": valid,
                    "source_coverage_fraction": supported / expected if expected else None,
                    "qa_valid_fraction_of_supported_area": fraction,
                    "qa_category_area_m2": dict(sorted(areas.items())),
                    "native_qa_code_pixel_counts": dict(sorted(qa_counts.items())),
                    "valid_composite_doy_min": min(doys) if doys else None,
                    "valid_composite_doy_max": max(doys) if doys else None,
                    "collection": "MOD13Q1.061",
                    "granule_ur": GRANULE,
                    "cmr_granule_id": cmr["id"],
                    "cmr_updated": cmr.get("updated"),
                    "source_production_at": core["PRODUCTIONDATETIME"],
                    "source_object_metadata": inputs.object_metadata,
                    "retrieved_at": inputs.retrieved_at,
                    "first_proven_availability_at": inputs.retrieved_at,
                    "artifact_sha256_by_member": inputs.sha256,
                    "artifact_id_by_member": inputs.artifact_ids,
                    "grid_id": grid_id,
                    "grid_crs": CRS_SIN.to_wkt(),
                    "weight_id": weight_id,
                    "weight_version": WEIGHT_VERSION,
                    "geometry_version": county.lineage.transform_version,
                    "geometry_digest": county.lineage.normalized_geometry_sha256,
                    "transformation_version": TRANSFORM_VERSION,
                    "limitation": (
                        "Observed 16-day vegetation condition; not tick abundance or Lyme risk. "
                        "Historical first availability is unproven."
                    ),
                },
            }
