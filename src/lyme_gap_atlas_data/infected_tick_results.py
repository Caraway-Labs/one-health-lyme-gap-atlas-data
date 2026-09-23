"""Versioned, consumer-safe projection of Story #168 metric envelopes.

This module does not calculate metrics, publish a semantic release, or read raw
artifacts.  Persistence callers may store the returned document unchanged.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any

from .infected_tick_metrics import CALCULATION_VERSION, DENSITY, METHODOLOGY_VERSION, PREVALENCE
from .surveillance_quality_propagation import serialize_safe_propagation

CONTRACT_VERSION = "infected-tick-derived-result-v1"
_UNSAFE_TEXT = re.compile(
    r"(?:[a-z][a-z0-9+.-]*://|[?&](?:token|signature|credential|password|secret)=|"
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----)",
    re.IGNORECASE,
)
_EVIDENCE_BASIS = {
    "SYNTHETIC_FIXTURE",
    "CURRENT_CODE_CI_TESTED_SOURCE_REPLAY_LIMITED",
}
_SITE_FIELDS = ("source_site_id", "source_plot_id", "source_location_id")
_EVENT_FIELDS = (
    "source_event_id",
    "source_sample_id",
    "source_subsample_id",
    "source_batch_id",
)
_GEOGRAPHY_FIELDS = (
    "source_location_id",
    "geography_kind",
    "coordinate_reference_system",
    "longitude",
    "latitude",
    "spatial_uncertainty_meters",
)
_COUNTY_FIELDS = ("mapping_status", "county_fips", "mapping_method", "mapping_version")


def _object(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _selected(value: object, fields: tuple[str, ...], name: str) -> dict[str, object]:
    source = {} if value is None else _object(value, name)
    return {field: source.get(field) for field in fields}


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text or null")
    return value


def _safe_values(value: object) -> None:
    """Reject private locations and credential material even in allowed fields."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or _UNSAFE_TEXT.search(key):
                raise ValueError("unsafe output key")
            _safe_values(item)
    elif isinstance(value, list):
        for item in value:
            _safe_values(item)
    elif isinstance(value, str) and _UNSAFE_TEXT.search(value):
        raise ValueError("unsafe output value")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def serialize_infected_tick_result(
    result: Mapping[str, Any], *, evidence_basis: str
) -> dict[str, object]:
    """Validate and project one calculated result into the internal v1 contract.

    ``evidence_basis`` is a bounded claim about *this calculation*. Historical
    #162 ingestion is recorded separately and never upgrades that claim.
    """
    if evidence_basis not in _EVIDENCE_BASIS:
        raise ValueError("unsupported or unverified calculation evidence basis")
    metric_id = result.get("metric_id")
    if metric_id not in (PREVALENCE, DENSITY):
        raise ValueError("unsupported metric")
    if result.get("methodology_version") != METHODOLOGY_VERSION:
        raise ValueError("unsupported methodology version")
    if result.get("calculation_version") != CALCULATION_VERSION:
        raise ValueError("unsupported calculation version")
    if result.get("native_grain") != "SITE_EVENT":
        raise ValueError("only SITE_EVENT results are supported")
    if result.get("representativeness") != "NOT_COUNTY_REPRESENTATIVE":
        raise ValueError("site/event output must retain non-county representativeness")
    state = result.get("state")
    value = result.get("value")
    if state == "NUMERIC":
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("numeric state requires a finite value")
        if result.get("unavailable_reasons"):
            raise ValueError("numeric state cannot have unavailable reasons")
    elif state == "UNAVAILABLE":
        if value is not None or not result.get("unavailable_reasons"):
            raise ValueError("unavailable state requires null value and reasons")
    else:
        raise ValueError("unsupported result state")
    expected_unit = "proportion" if metric_id == PREVALENCE else "ticks_per_square_metre"
    if result.get("unit") != expected_unit:
        raise ValueError("incompatible base unit")
    numerator = result.get("numerator")
    denominator = result.get("denominator")
    numeric_value = (
        float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    )
    if state == "NUMERIC" and (
        isinstance(numerator, bool)
        or not isinstance(numerator, int)
        or numerator < 0
        or isinstance(denominator, bool)
        or not isinstance(denominator, (int, float))
        or not math.isfinite(denominator)
        or denominator <= 0
        or numeric_value is None
        or not math.isclose(numeric_value, numerator / denominator)
    ):
        raise ValueError("numeric value must match its valid numerator and denominator")
    stratum = _object(result.get("stratum"), "stratum")
    site = _selected(stratum.get("sampling_site"), _SITE_FIELDS, "sampling_site")
    event = _selected(stratum.get("event"), _EVENT_FIELDS, "event")
    if state == "NUMERIC":
        _required_text(site["source_site_id"], "source_site_id")
        _required_text(event["source_event_id"], "source_event_id")
        _required_text(stratum.get("date"), "date")
    geography = _selected(result.get("source_geography"), _GEOGRAPHY_FIELDS, "source_geography")
    county = _selected(result.get("county_relationship"), _COUNTY_FIELDS, "county_relationship")
    relationship = result.get("county_relationship")
    if (
        relationship is not None
        and _object(relationship, "county_relationship").get("representativeness")
        != "NOT_COUNTY_REPRESENTATIVE"
    ):
        raise ValueError("county relationship cannot imply county representativeness")
    if county["mapping_status"] in ("UNMAPPED", "AMBIGUOUS") and county["county_fips"] is not None:
        raise ValueError("unmapped site cannot have county FIPS")
    if county["mapping_status"] not in (
        None,
        "UNMAPPED",
        "AMBIGUOUS",
        "SOURCE_REPORTED_COUNTY",
        "ATLAS_DERIVED_MATCH",
    ):
        raise ValueError("unsupported county relationship")
    if state == "NUMERIC" and county["mapping_status"] is None:
        raise ValueError("numeric site/event result requires a county mapping state")
    ids = result.get("input_canonical_observation_ids")
    lineage = result.get("source_lineage")
    if (
        not isinstance(ids, list)
        or not ids
        or not isinstance(lineage, list)
        or len(ids) != len(lineage)
    ):
        raise ValueError("canonical input IDs and lineage must align")
    safe_lineage = []
    for item in lineage:
        source = _object(item, "source_lineage")
        normalization = source.get("normalization")
        normalization = _object(normalization, "normalization") if normalization is not None else {}
        mappings = normalization.get("mappings")
        mappings = _object(mappings, "normalization mappings") if mappings is not None else {}
        safe_lineage.append(
            {
                "canonical_observation_id": _required_text(
                    source.get("canonical_observation_id"), "canonical_observation_id"
                ),
                "source_dataset_id": _optional_text(
                    source.get("source_dataset_id"), "source_dataset_id"
                ),
                "source_version_id": _optional_text(
                    source.get("data_source_version_id"), "data_source_version_id"
                ),
                "source_record_id": _optional_text(
                    source.get("source_record_id"), "source_record_id"
                ),
                "source_testing_id": (
                    source.get("source_testing_id") if metric_id == PREVALENCE else None
                ),
                "ingestion_run_id": _optional_text(
                    source.get("ingestion_run_id"), "ingestion_run_id"
                ),
                "canonical_method_version": _optional_text(
                    source.get("method_version"), "method_version"
                ),
                "retrieved_at": _optional_text(source.get("retrieved_at"), "retrieved_at"),
                "normalization_registry_id": _optional_text(
                    normalization.get("registry_id"), "registry_id"
                ),
                "normalization_registry_version": _optional_text(
                    normalization.get("registry_version"), "registry_version"
                ),
                "normalization_rule_ids": sorted(
                    _required_text(
                        _object(mapping, "mapping").get("mapping_rule_id"), "mapping_rule_id"
                    )
                    for mapping in mappings.values()
                    if _object(mapping, "mapping").get("mapping_rule_id") is not None
                ),
            }
        )
    if [item["canonical_observation_id"] for item in safe_lineage] != ids:
        raise ValueError("lineage does not match exact canonical inputs")
    if state == "NUMERIC" and any(
        item[field] is None
        for item in safe_lineage
        for field in (
            "source_dataset_id",
            "source_version_id",
            "source_record_id",
            "ingestion_run_id",
            "canonical_method_version",
            "retrieved_at",
            "normalization_registry_id",
            "normalization_registry_version",
        )
    ):
        raise ValueError("numeric result requires complete safe lineage")
    quality = serialize_safe_propagation(
        _object(result.get("quality_propagation"), "quality_propagation")
    )
    if quality["transformation_id"] != result.get("metric_identity"):
        raise ValueError("quality propagation is for another metric result")
    conversion = result.get("presentation_conversion")
    if conversion is not None:
        conversion = _selected(
            conversion, ("value", "unit", "conversion_rule_id"), "presentation_conversion"
        )
        converted_value = conversion["value"]
        if (
            state != "NUMERIC"
            or metric_id != DENSITY
            or conversion["unit"] != "ticks_per_hectare"
            or conversion["conversion_rule_id"] != "ABUNDANCE_SQUARE_METRE_TO_HECTARE_V1"
            or isinstance(converted_value, bool)
            or not isinstance(converted_value, (int, float))
            or numeric_value is None
            or not math.isfinite(converted_value)
            or not math.isclose(converted_value, numeric_value * 10000)
        ):
            raise ValueError("unsupported presentation conversion")
    scientific = {
        "metric_identity": _required_text(result.get("metric_identity"), "metric_identity"),
        "metric_id": metric_id,
        "methodology_version": METHODOLOGY_VERSION,
        "calculation_version": CALCULATION_VERSION,
        "state": state,
        "value": value,
        "numerator": numerator,
        "denominator": denominator,
        "unit": expected_unit,
        "native_grain": "SITE_EVENT",
        "source_scope": {
            "publisher": stratum.get("source_agency"),
            "dataset_id": stratum.get("source_dataset_id"),
            "source_version_id": stratum.get("data_source_version_id"),
        },
        "site": site,
        "event": event,
        "source_geography": geography,
        "county_relationship": county | {"representativeness": "NOT_COUNTY_REPRESENTATIVE"},
        "date": stratum["date"],
        "tick_species": stratum.get("tick_species"),
        "life_stage": stratum.get("life_stage"),
        "pathogen_name": stratum.get("pathogen_name"),
        "collection_method": stratum.get("collection_method"),
        "input_canonical_observation_ids": ids,
        "safe_lineage": safe_lineage,
        "unavailable_reasons": list(result.get("unavailable_reasons", [])),
        "quality": quality,
    }
    _safe_values(scientific)
    revision = _digest(scientific)
    document = {
        "contract_version": CONTRACT_VERSION,
        "result_id": f"tickresult:v1:{revision}",
        "result_revision": revision,
        **scientific,
        "presentation_conversion": conversion,
        "evidence_status": {
            "calculation_basis": evidence_basis,
            "historical_ingestion_context": {
                "run_id": "ea8db548-62b0-4632-84ca-02eee97ead41",
                "relationship": "SEPARATE_162_EVIDENCE_NOT_RESULT_LINEAGE",
            },
            "current_code_source_backed_replay": "EVIDENCE_LIMITED",
        },
        "publication_status": "INTERNAL_DEV_ONLY",
    }
    _safe_values(document)
    return document
