"""Bounded NSF NEON RELEASE-2026 package adapter for Story #162.

The adapter deliberately owns package transport and native joins only.  All
scientific aliases and controlled values come from the versioned governed registry.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

from ..tick_contract import canonical_observation_id, validate_canonical_observation
from ..tick_normalization import load_registry, normalize_value
from .adapters import AcquireResult, AcquisitionArtifact, AcquisitionError, NormalizeResult
from .types import AdapterKind, FailureCategory, SourceDefinition, ValidationIssue, ValidationResult

_RELEASE = "RELEASE-2026"
_PRODUCTS = {"DP1.10093.001", "DP1.10092.001"}
_NORMALIZATION_REGISTRY_VERSION = "1.0.4"
_TABLES = {
    "DP1.10093.001": (("tck_fielddata", True), ("tck_taxonomyProcessed", True)),
    # NEON publishes the QA table only once, without a basic/expanded edition.
    # Treat it as an unambiguous package member, never as a substitute for an
    # expanded analytical table.
    "DP1.10092.001": (("tck_pathogen", True), ("tck_pathogenqa", False)),
}


class NeonReleasePackageAdapter:
    """Acquire a reviewed, finite NEON release package as an artifact set."""

    kind = AdapterKind.NEON_RELEASE_PACKAGE

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client

    def acquire(
        self, definition: SourceDefinition, *, fixture_dir: Path | None = None
    ) -> AcquireResult:
        if fixture_dir is not None:
            return self._acquire_fixture(definition, fixture_dir)
        token = os.getenv("NEON_API_TOKEN")
        if not token:
            raise AcquisitionError("NEON_API_TOKEN is required", code="NEON_TOKEN_UNAVAILABLE")
        # Signed NEON object URLs carry temporary credentials. Retain only the
        # stable manifest route as provenance and suppress HTTP client URL logs.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        client = self._client or httpx.Client(timeout=60.0, follow_redirects=True)
        try:
            artifacts: list[AcquisitionArtifact] = []
            tables: dict[str, list[dict[str, str]]] = {}
            for scope in _scopes(definition):
                product, site, month = scope["product"], scope["site"], scope["month"]
                route = _manifest_route(definition, product, site, month)
                response = client.get(
                    route, headers={"X-API-Token": token, "Accept": "application/json"}
                )
                if response.status_code in {401, 403}:
                    raise AcquisitionError("NEON authorization failed", code="NEON_AUTHORIZATION")
                response.raise_for_status()
                document = response.json()
                manifest = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
                artifacts.append(
                    AcquisitionArtifact(
                        name=f"{product}-{site}-{month}-manifest.json",
                        payload=manifest,
                        media_type="application/json",
                        source_uri=route,
                        request_purpose="NEON_RELEASE_MANIFEST",
                    )
                )
                files = _files(document)
                selected_names: set[str] = set()
                for table, requires_expanded in _TABLES[product]:
                    file_info = _select_package_file(
                        files, table, requires_expanded=requires_expanded
                    )
                    selected_names.add(str(file_info["name"]))
                    download = str(file_info["url"])
                    data = client.get(download, headers={"X-API-Token": token}).content
                    if hashlib.md5(data, usedforsecurity=False).hexdigest() != str(
                        file_info["md5"]
                    ):
                        raise AcquisitionError(
                            "NEON file checksum changed", code="NEON_FILE_CHECKSUM"
                        )
                    tables.setdefault(table, []).extend(_csv_rows(data))
                    artifacts.append(
                        AcquisitionArtifact(
                            name=str(file_info["name"]),
                            payload=data,
                            media_type="text/csv",
                            source_uri=route,
                            request_purpose="NEON_RELEASE_FILE",
                            row_count=len(_csv_rows(data)),
                        )
                    )
                # Retain every support member of the frozen package separately.
                # Its signed delivery URL is used only for this request; the stable
                # manifest route is the durable provenance identifier.
                for file_info in files:
                    name = str(file_info.get("name", ""))
                    if name in selected_names:
                        continue
                    support_download: Any = file_info.get("url")
                    digest = file_info.get("md5")
                    if (
                        not name
                        or not isinstance(support_download, str)
                        or not isinstance(digest, str)
                    ):
                        raise AcquisitionError(
                            "NEON support-file manifest changed", code="NEON_MANIFEST_SCHEMA"
                        )
                    data = client.get(support_download, headers={"X-API-Token": token}).content
                    if hashlib.md5(data, usedforsecurity=False).hexdigest() != digest:
                        raise AcquisitionError(
                            "NEON support-file checksum changed", code="NEON_FILE_CHECKSUM"
                        )
                    artifacts.append(
                        AcquisitionArtifact(
                            name=name,
                            payload=data,
                            media_type=_media_type(name),
                            source_uri=route,
                            request_purpose="NEON_RELEASE_SUPPORT_FILE",
                        )
                    )
            payload = {"release": _RELEASE, "tables": tables, "scopes": _scopes(definition)}
            # The first artifact is a canonical package manifest built from stable request routes
            # and member checksums, never from temporary signed download URLs.
            package = _package_manifest(payload, artifacts)
            primary = AcquisitionArtifact(
                name="neon-release-package-manifest.json",
                payload=package,
                media_type="application/json",
                source_uri=definition.endpoint_template,
                request_purpose="NEON_RELEASE_PACKAGE",
            )
            all_artifacts = (primary, *artifacts)
            return AcquireResult(
                payload=payload,
                artifact_sha256=primary.sha256,
                media_type=primary.media_type,
                row_count=sum(len(rows) for rows in tables.values()),
                raw_payload=package,
                artifacts=all_artifacts,
                detail={
                    "release": _RELEASE,
                    "artifact_count": len(all_artifacts),
                    "scope_count": len(_scopes(definition)),
                },
            )
        finally:
            if self._client is None:
                client.close()

    def _acquire_fixture(self, definition: SourceDefinition, fixture_dir: Path) -> AcquireResult:
        manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))
        artifacts: list[AcquisitionArtifact] = []
        tables: dict[str, list[dict[str, str]]] = {}
        for item in manifest["files"]:
            payload = (fixture_dir / item["fixture"]).read_bytes()
            table = str(item["table"])
            tables[table] = _csv_rows(payload)
            artifacts.append(
                AcquisitionArtifact(
                    name=str(item["name"]),
                    payload=payload,
                    media_type="text/csv",
                    source_uri=str(item["source_uri"]),
                    request_purpose="NEON_RELEASE_FILE",
                    row_count=len(tables[table]),
                )
            )
        payload = {"release": _RELEASE, "tables": tables, "scopes": _scopes(definition)}
        package = _package_manifest(payload, artifacts)
        primary = AcquisitionArtifact(
            "neon-release-package-manifest.json",
            package,
            "application/json",
            definition.endpoint_template,
            "NEON_RELEASE_PACKAGE",
        )
        return AcquireResult(
            payload,
            primary.sha256,
            primary.media_type,
            sum(map(len, tables.values())),
            {"source": "fixture", "artifact_count": len(artifacts) + 1},
            package,
            (primary, *artifacts),
        )

    def restore_raw_payload(self, definition: SourceDefinition, raw_payload: bytes) -> Any:
        del definition, raw_payload
        raise AcquisitionError(
            "NEON packages resume from durable payload checkpoints", code="NEON_PACKAGE_RESTORE"
        )

    def validate_payload(self, definition: SourceDefinition, payload: Any) -> ValidationResult:
        del definition
        tables = payload.get("tables", {}) if isinstance(payload, dict) else {}
        issues: list[ValidationIssue] = []
        for table, columns in {
            "tck_fielddata": {
                "siteID",
                "plotID",
                "eventID",
                "sampleID",
                "collectDate",
                "samplingMethod",
                "totalSampledArea",
            },
            "tck_taxonomyProcessed": {
                "sampleID",
                "subsampleID",
                "scientificName",
                "sexOrAge",
                "individualCount",
            },
            "tck_pathogen": {
                "subsampleID",
                "testingID",
                "batchID",
                "testedDate",
                "testResult",
                "testPathogenName",
                "individualCount",
            },
            "tck_pathogenqa": {"batchID", "uid"},
        }.items():
            rows = tables.get(table)
            if not rows:
                issues.append(
                    ValidationIssue(
                        "NEON_TABLE_MISSING", f"{table} is required", FailureCategory.SCHEMA
                    )
                )
            elif not columns.issubset(rows[0]):
                issues.append(
                    ValidationIssue(
                        "NEON_SCHEMA_DRIFT", f"{table} columns changed", FailureCategory.SCHEMA
                    )
                )
        return ValidationResult(ok=not issues, issues=issues)

    def normalize(self, definition: SourceDefinition, payload: Any) -> NormalizeResult:
        registry = load_registry()
        if registry["registry_version"] != _NORMALIZATION_REGISTRY_VERSION:
            raise ValueError("NEON normalization registry version is not pinned")
        tables = payload["tables"]
        lineage = payload.get("_acquisition_lineage", {})
        fields = _unique_index(tables["tck_fielddata"], "sampleID", allow_blank=True)
        taxonomy = _unique_index(tables["tck_taxonomyProcessed"], "subsampleID")
        # QA is a retained support table. Its batchID is a many-row grouping,
        # not an approved one-to-one join to pathogen tests. Validate its own
        # publisher identifier without projecting a non-deterministic QA join
        # into the canonical observation.
        _unique_index(tables["tck_pathogenqa"], "uid")
        records: list[dict[str, Any]] = []
        supporting_assays: list[dict[str, Any]] = []
        for taxon in tables["tck_taxonomyProcessed"]:
            field = _one(fields, taxon.get("sampleID"), "sampleID")
            if field is None:
                continue
            records.append(_collection_record(field, taxon, lineage))
        for test in tables["tck_pathogen"]:
            if not test.get("testResult", "").strip():
                raise ValueError("NEON blank pathogen test result is a blocking release failure")
            taxon = _one(taxonomy, test.get("subsampleID"), "subsampleID")
            field = _one(fields, taxon.get("sampleID") if taxon else None, "sampleID")
            if taxon is None or field is None:
                raise ValueError("NEON pathogen test has no unique native collection join")
            pathogen_map = _mapping("pathogen_target", test["testPathogenName"], "DP1.10092.001")
            if pathogen_map.disposition is not None:
                supporting_assays.append(
                    _supporting_assay_record(field, taxon, test, lineage, pathogen_map)
                )
                continue
            if pathogen_map.status != "APPROVED":
                raise ValueError("NEON pathogen_target has unapproved mapping")
            records.append(_testing_record(field, taxon, test, lineage))
        return NormalizeResult(
            records=records,
            transformation_version="neon-release-2026-harmonization-v1",
            detail={
                "canonical_observation_count": len(records),
                "registry_version": _NORMALIZATION_REGISTRY_VERSION,
                "supporting_assay_count": len(supporting_assays),
                "supporting_assays": supporting_assays,
            },
        )


def _collection_record(
    field: dict[str, str], taxon: dict[str, str], lineage: dict[str, Any]
) -> dict[str, Any]:
    taxon_map = _approved("tick_taxon", taxon["scientificName"], "DP1.10093.001")
    stage_map = _approved("life_stage", taxon["sexOrAge"], "DP1.10093.001")
    method_map = _approved("collection_method", field["samplingMethod"], "DP1.10093.001")
    effort_unit_map = _approved("effort_unit", "m2", "DP1.10093.001")
    record = _base(field, taxon, "DP1.10093.001", "COLLECTION_ABUNDANCE", None, lineage)
    record.update(
        {
            "tick_species": taxon_map.canonical_label,
            "life_stage": stage_map.canonical_id,
            "collection_method": method_map.canonical_label,
            "ticks_collected": _integer(taxon["individualCount"]),
            "surveillance_period_start": field["collectDate"],
            "surveillance_period_end": field["collectDate"],
            "collection_effort_value": _number_or_none(field.get("totalSampledArea")),
            "collection_effort_unit": "square metre",
            "quality_flags": _quality_flags(field, taxon),
            "normalization": _envelope(taxon_map, stage_map, method_map, effort_unit_map),
        }
    )
    if record["collection_effort_value"] is None:
        # RELEASE-2026 documents the field but not its blank-value convention.
        # The approved #163 interpretation therefore retains the null and marks
        # its source meaning as UNKNOWN rather than inventing zero or a stronger state.
        record["missingness"] = {"collection_effort_value": "UNKNOWN"}
    return {
        "record": {"source_record_id": record["source_record_id"], "canonical_observation": record}
    }


def _testing_record(
    field: dict[str, str],
    taxon: dict[str, str],
    test: dict[str, str],
    lineage: dict[str, Any],
) -> dict[str, Any]:
    taxon_map = _approved("tick_taxon", taxon["scientificName"], "DP1.10093.001")
    pathogen_map = _approved("pathogen_target", test["testPathogenName"], "DP1.10092.001")
    result_map = _approved("test_result", test["testResult"], "DP1.10092.001")
    record = _base(
        field, {**taxon, **test}, "DP1.10092.001", "PATHOGEN_TESTING", test["testingID"], lineage
    )
    positive = 1 if result_map.canonical_id == "DETECTED" else 0
    record.update(
        {
            "tick_species": taxon_map.canonical_label,
            "pathogen_name": pathogen_map.canonical_label,
            "ticks_tested": 1,
            "ticks_positive": positive,
            "surveillance_period_start": test["testedDate"],
            "surveillance_period_end": test["testedDate"],
            "quality_flags": _quality_flags(field, taxon, test),
            "normalization": _envelope(taxon_map, pathogen_map, result_map),
        }
    )
    validate_canonical_observation(record)
    return {
        "record": {
            "source_record_id": record["source_record_id"],
            "canonical_observation": record,
            "source_quality_context": {},
        }
    }


def _supporting_assay_record(
    field: dict[str, str],
    taxon: dict[str, str],
    test: dict[str, str],
    lineage: dict[str, Any],
    pathogen_map: Any,
) -> dict[str, Any]:
    """Retain reviewed non-pathogen assays without producing a pathogen observation."""
    base = _base(
        field, {**taxon, **test}, "DP1.10092.001", "PATHOGEN_TESTING", test["testingID"], lineage
    )
    return {
        "source_record_id": base["source_record_id"],
        "source_value": test["testPathogenName"],
        "test_result": test["testResult"],
        "test_protocol_version": test.get("testProtocolVersion") or None,
        "disposition": pathogen_map.disposition,
        "normalization": pathogen_map.as_contract_value(),
    }


def _base(
    field: dict[str, str],
    native: dict[str, str],
    product: str,
    observation_type: str,
    testing_id: str | None,
    lineage: dict[str, Any],
) -> dict[str, Any]:
    source_record_id = ":".join(
        [
            _RELEASE,
            product,
            native.get("eventID", field.get("eventID", "")),
            native.get("sampleID", field.get("sampleID", "")),
            native.get("subsampleID", ""),
            testing_id or "",
            native.get("testPathogenName", ""),
        ]
    )
    return {
        "canonical_observation_id": canonical_observation_id(
            source_dataset_id=product,
            data_source_version_id=_RELEASE,
            source_record_id=source_record_id,
            observation_type=observation_type,
            sampling_site_id=field["siteID"],
            sampling_event_id=field["eventID"],
            sample_id=field.get("sampleID") or None,
            subsample_id=native.get("subsampleID") or None,
            testing_id=testing_id,
            replicate_id=None,
            strata={
                "source_taxon": native.get("scientificName"),
                "pathogen": native.get("testPathogenName"),
                "batch_id": native.get("batchID"),
            },
        ),
        "observation_type": observation_type,
        "native_sampling_grain": "SITE_EVENT",
        "source_agency": "NSF NEON",
        "source_dataset_id": product,
        "source_record_id": source_record_id,
        "data_source_version_id": _RELEASE,
        "ingestion_run_id": lineage.get("ingestion_run_id", "fixture-run"),
        "artifact_id": lineage.get("artifact_id", "fixture-artifact"),
        "retrieved_at": lineage.get("retrieved_at", "2026-09-22T00:00:00+00:00"),
        "method_version": "tick-surveillance-v1.2",
        "reported_or_derived": "HARMONIZED",
        "temporal_semantics": "POINT_IN_TIME",
        "quality_flags": [],
        "sampling_site": {"source_site_id": field["siteID"], "source_plot_id": field["plotID"]},
        "sampling_event": {
            "source_event_id": field["eventID"],
            "source_sample_id": field.get("sampleID") or None,
            "source_subsample_id": native.get("subsampleID") or None,
            "source_testing_id": testing_id,
            "source_batch_id": native.get("batchID") or None,
        },
        "source_geography": {
            "source_location_id": field["plotID"],
            "geography_kind": "PLOT",
            "coordinate_reference_system": "EPSG:4326",
            "longitude": _number_or_none(field.get("decimalLongitude")),
            "latitude": _number_or_none(field.get("decimalLatitude")),
            "spatial_uncertainty_meters": _number_or_none(field.get("coordinateUncertainty")),
        },
        "harmonized_geography": {
            "geography_kind": "PLOT",
            "method": "SOURCE_IDENTIFIER_PRESERVED",
            "method_version": "tick-surveillance-v1.1",
        },
        "county_relationship": {
            "mapping_status": "UNMAPPED",
            "county_fips": None,
            "mapping_method": None,
            "mapping_version": None,
            "mapping_artifact_id": None,
            "representativeness": "NOT_COUNTY_REPRESENTATIVE",
        },
    }


def _approved(field: str, value: str | bool, product: str) -> Any:
    result = _mapping(field, value, product)
    if result.status != "APPROVED":
        raise ValueError(f"NEON {field} has unapproved mapping")
    return result


def _mapping(field: str, value: str | bool, product: str) -> Any:
    return normalize_value(
        field=field,
        source_value=value,
        publisher="NSF NEON",
        dataset_id=product,
        source_version=_RELEASE,
    )


def _envelope(*results: Any) -> dict[str, Any]:
    first = results[0]
    return {
        "registry_id": first.registry_id,
        "registry_version": first.registry_version,
        "mappings": {
            item.mapping_rule_id or item.source_context["dataset_id"]: item.as_contract_value()
            for item in results
        },
    }


def _unique_index(
    rows: Iterable[dict[str, str]], key: str, *, allow_blank: bool = False
) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row.get(key, "").strip()
        if not value and allow_blank:
            continue
        if not value or value in index:
            raise ValueError(f"NEON duplicate or blank {key}")
        index[value] = row
    return index


def _one(index: dict[str, dict[str, str]], key: str | None, name: str) -> dict[str, str] | None:
    if not key:
        return None
    return index.get(key)


def _files(document: dict[str, Any]) -> list[dict[str, Any]]:
    files = document.get("data", {}).get("files", [])
    if not isinstance(files, list):
        raise AcquisitionError("NEON manifest has no file list", code="NEON_MANIFEST_SCHEMA")
    return [item for item in files if isinstance(item, dict)]


def _select_package_file(
    files: list[dict[str, Any]], table: str, *, requires_expanded: bool
) -> dict[str, Any]:
    matches = [
        item
        for item in files
        if f".{table}." in str(item.get("name"))
        and (not requires_expanded or ".expanded." in str(item.get("name")))
    ]
    if len(matches) != 1 or not matches[0].get("url") or not matches[0].get("md5"):
        raise AcquisitionError(
            "NEON required package file is absent or ambiguous", code="NEON_PACKAGE_SCHEMA"
        )
    return matches[0]


def _csv_rows(payload: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))


def _package_manifest(payload: dict[str, Any], artifacts: list[AcquisitionArtifact]) -> bytes:
    return json.dumps(
        {
            "release": payload["release"],
            "scopes": payload["scopes"],
            "members": [
                {
                    "name": item.name,
                    "sha256": item.sha256,
                    "byte_count": len(item.payload),
                    "media_type": item.media_type,
                    "source_uri": item.source_uri,
                }
                for item in artifacts
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _scopes(definition: SourceDefinition) -> list[dict[str, str]]:
    scopes = definition.extra.get("package_scopes")
    if not isinstance(scopes, list) or not scopes:
        raise ValueError("neon_release_package requires bounded package_scopes")
    normalized = [
        {key: str(item.get(key, "")) for key in ("product", "site", "month")}
        for item in scopes
        if isinstance(item, dict)
    ]
    if any(
        item["product"] not in _PRODUCTS or not item["site"] or not item["month"]
        for item in normalized
    ):
        raise ValueError("NEON package scope is not approved")
    return normalized


def _manifest_route(definition: SourceDefinition, product: str, site: str, month: str) -> str:
    return definition.endpoint_template.format(
        product=product, site=site, month=month, release=_RELEASE
    )


def _integer(value: str) -> int:
    return int(float(value))


def _number_or_none(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _quality_flags(*rows: dict[str, str]) -> list[dict[str, object]]:
    flags: list[dict[str, object]] = []
    for row in rows:
        if row.get("samplingImpractical", "").casefold() == "true":
            flags.append(_approved("quality_flag", True, "DP1.10093.001").as_contract_value())
        value = row.get("dataQF", "").strip()
        if value:
            product = "DP1.10092.001" if "testingID" in row else "DP1.10093.001"
            flags.append(_approved("quality_flag", value, product).as_contract_value())
    return flags


def _media_type(name: str) -> str:
    if name.endswith(".csv"):
        return "text/csv"
    if name.endswith(".xml"):
        return "application/xml"
    return "text/plain"
