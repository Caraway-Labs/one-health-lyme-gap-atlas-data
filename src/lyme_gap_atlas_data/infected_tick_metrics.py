"""Pure Story #168 calculations for the two approved site/event tick metrics.

The caller supplies canonical observations. This module neither acquires source
data nor persists or publishes the derived envelopes.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from .surveillance_quality import assess_surveillance_quality
from .surveillance_quality_propagation import propagate_surveillance_quality
from .tick_normalization import convert_value, load_registry

METHODOLOGY_VERSION = "infected-tick-metrics-v1"
CALCULATION_VERSION = "infected-tick-calculation-v1"
PREVALENCE = "OBSERVED_PATHOGEN_PREVALENCE"
DENSITY = "EFFORT_NORMALIZED_COLLECTION_DENSITY"
_DATASETS = {PREVALENCE: "DP1.10092.001", DENSITY: "DP1.10093.001"}
_LIFE_STAGES = {"LARVA", "NYMPH", "ADULT"}
_METHODS = {"DRAG_CLOTH", "FLAG_CLOTH"}
_REQUIRED_LINEAGE = (
    "canonical_observation_id",
    "source_dataset_id",
    "data_source_version_id",
    "source_record_id",
    "ingestion_run_id",
    "artifact_id",
    "retrieved_at",
    "method_version",
)


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _part(observation: Mapping[str, Any], parent: str, child: str) -> object:
    value = observation.get(parent)
    return value.get(child) if isinstance(value, Mapping) else None


def _flag_codes(observation: Mapping[str, Any]) -> set[str]:
    flags = observation.get("quality_flags")
    if not isinstance(flags, list):
        return set()
    return {
        code
        for flag in flags
        if (
            code := flag
            if isinstance(flag, str)
            else flag.get("canonical_id")
            if isinstance(flag, Mapping)
            else None
        )
        and isinstance(code, str)
    }


def _mapping(observation: Mapping[str, Any], field: str) -> Mapping[str, Any] | None:
    normalization = observation.get("normalization")
    if (
        not isinstance(normalization, Mapping)
        or normalization.get("registry_id") != "tick-surveillance-normalization-v1"
    ):
        return None
    registry = load_registry()
    if normalization.get("registry_version") != registry["registry_version"]:
        return None
    mappings = normalization.get("mappings")
    if not isinstance(mappings, Mapping):
        return None
    matches = [
        entry
        for entry in mappings.values()
        if isinstance(entry, Mapping)
        and isinstance(entry.get("source_context"), Mapping)
        and entry.get("status") == "APPROVED"
        and entry.get("registry_id") == registry["registry_id"]
        and entry.get("registry_version") == registry["registry_version"]
        and any(
            rule.get("field") == field
            and rule.get("rule_id") == entry.get("mapping_rule_id")
            and rule.get("status") == "APPROVED"
            and rule.get("canonical_id") == entry.get("canonical_id")
            and rule.get("canonical_label") == entry.get("canonical_label")
            and rule.get("source_value") == entry.get("source_value")
            and rule.get("source_context") == entry.get("source_context")
            and entry.get("source_context", {}).get("publisher") == "NSF NEON"
            and entry.get("source_context", {}).get("source_version") == "RELEASE-2026"
            for rule in registry["mappings"]
        )
    ]
    return matches[0] if len(matches) == 1 else None


def _component(profile: Mapping[str, Any], dimension: str) -> Mapping[str, Any]:
    return next(item for item in profile["components"] if item["dimension"] == dimension)


def _quality_reasons(profile: Mapping[str, Any], metric_id: str) -> list[str]:
    reasons = []
    required = {
        "TECHNICAL_SOURCE_VALIDITY": "CANONICAL_RECORD_STRUCTURALLY_VALID",
        "PROVENANCE_COMPLETENESS": "CANONICAL_LINEAGE_RETAINED",
    }
    if metric_id == PREVALENCE:
        required["PATHOGEN_TESTING_DENOMINATOR_VALIDITY"] = "INDIVIDUAL_TEST_DENOMINATOR_VALID"
    else:
        required["EFFORT_DENOMINATOR_COMPLETENESS"] = "EFFORT_DOCUMENTED"
        required["METHOD_DOCUMENTATION"] = "METHOD_DOCUMENTED"
    for dimension, evidence in required.items():
        component = _component(profile, dimension)
        if component["state"] != "ASSESSED" or evidence not in component["reason_codes"]:
            reasons.append(f"QUALITY_EVIDENCE_MISSING_{dimension}")
    return reasons


def _base_reasons(observation: Mapping[str, Any], metric_id: str) -> list[str]:
    reasons = []
    if observation.get("observation_type") != (
        "PATHOGEN_TESTING" if metric_id == PREVALENCE else "COLLECTION_ABUNDANCE"
    ):
        reasons.append("INELIGIBLE_OBSERVATION_TYPE")
    if (
        observation.get("source_agency") != "NSF NEON"
        or observation.get("source_dataset_id") != _DATASETS[metric_id]
        or observation.get("data_source_version_id") != "RELEASE-2026"
    ):
        reasons.append("INELIGIBLE_SOURCE_SCOPE")
    if observation.get("native_sampling_grain") != "SITE_EVENT":
        reasons.append("INCOMPATIBLE_NATIVE_GRAIN")
    if any(not _text(observation.get(field)) for field in _REQUIRED_LINEAGE):
        reasons.append("MISSING_REQUIRED_PROVENANCE")
    if not _text(_part(observation, "sampling_site", "source_site_id")) or not _text(
        _part(observation, "sampling_event", "source_event_id")
    ):
        reasons.append("MISSING_SITE_EVENT_IDENTITY")
    if observation.get("surveillance_period_start") != observation.get(
        "surveillance_period_end"
    ) or not _text(observation.get("surveillance_period_start")):
        reasons.append("INCOMPATIBLE_EVENT_OR_PERIOD")
    if (
        _part(observation, "county_relationship", "representativeness")
        != "NOT_COUNTY_REPRESENTATIVE"
    ):
        reasons.append("MISSING_REPRESENTATIVENESS_BOUNDARY")
    if (
        _part(observation, "county_relationship", "mapping_status") == "UNMAPPED"
        and _part(observation, "county_relationship", "county_fips") is not None
    ):
        reasons.append("INVALID_UNMAPPED_COUNTY_RELATIONSHIP")
    taxon = _mapping(observation, "tick_taxon")
    if (
        taxon is None
        or taxon.get("canonical_label") != observation.get("tick_species")
        or taxon.get("canonical_id") == "IXODES_SCAPULARIS_OR_PACIFICUS"
    ):
        reasons.append("UNRESOLVED_TAXON")
    stage = _mapping(observation, "life_stage")
    if (
        observation.get("life_stage") not in _LIFE_STAGES
        or stage is None
        or stage.get("canonical_id") != observation.get("life_stage")
    ):
        reasons.append("UNRESOLVED_LIFE_STAGE")
    if _flag_codes(observation) & {
        "SOURCE_REVISION_AMBIGUOUS",
        "REVISION_SELECTION_NOT_APPROVED",
    }:
        reasons.append("REVISION_SELECTION_NOT_APPROVED")
    return reasons


def _prevalence_reasons(observation: Mapping[str, Any]) -> list[str]:
    reasons = []
    if (
        not _text(observation.get("pathogen_name"))
        or (pathogen := _mapping(observation, "pathogen_target")) is None
        or pathogen.get("canonical_label") != observation.get("pathogen_name")
    ):
        reasons.append("UNSUPPORTED_PATHOGEN_MAPPING")
    tested = observation.get("ticks_tested")
    positive = observation.get("ticks_positive")
    if not isinstance(tested, int) or isinstance(tested, bool):
        reasons.append("TESTED_DENOMINATOR_UNAVAILABLE")
    elif tested == 0:
        reasons.append("ZERO_TESTED_DENOMINATOR")
    elif tested < 0:
        reasons.append("INVALID_TESTED_DENOMINATOR")
    if not isinstance(positive, int) or isinstance(positive, bool) or positive < 0:
        reasons.append("INVALID_POSITIVE_COUNT")
    elif isinstance(tested, int) and positive > tested:
        reasons.append("POSITIVE_EXCEEDS_TESTED")
    if observation.get("testing_grain", "INDIVIDUAL") != "INDIVIDUAL" or tested != 1:
        reasons.append("POOLED_TESTING_UNSUPPORTED")
    if not _text(_part(observation, "sampling_event", "source_testing_id")):
        reasons.append("MISSING_TESTING_SCOPE")
    result = _mapping(observation, "test_result")
    if result is None or result.get("canonical_id") not in {"DETECTED", "NOT_DETECTED"}:
        reasons.append("UNSUPPORTED_TEST_RESULT")
    elif (
        isinstance(positive, int)
        and positive in {0, 1}
        and result["canonical_id"] != ("DETECTED" if positive else "NOT_DETECTED")
    ):
        reasons.append("TEST_RESULT_COUNT_MISMATCH")
    return reasons


def _density_reasons(observation: Mapping[str, Any]) -> list[str]:
    reasons = []
    count = observation.get("ticks_collected")
    effort = observation.get("collection_effort_value")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        reasons.append("INVALID_COLLECTION_COUNT")
    if effort is None:
        reasons.append(
            "EFFORT_UNKNOWN"
            if _part(observation, "missingness", "collection_effort_value") == "UNKNOWN"
            else "EFFORT_UNAVAILABLE"
        )
    elif (
        not isinstance(effort, (int, float))
        or isinstance(effort, bool)
        or not math.isfinite(effort)
    ):
        reasons.append("NONFINITE_OR_INVALID_EFFORT")
    elif effort <= 0:
        reasons.append("ZERO_EFFORT" if effort == 0 else "NEGATIVE_EFFORT")
    if observation.get("collection_effort_unit") != "square metre":
        reasons.append("UNSUPPORTED_EFFORT_UNIT")
    effort_unit = _mapping(observation, "effort_unit")
    if (
        effort_unit is None
        or effort_unit.get("canonical_id") != "SQUARE_METRE"
        or effort_unit.get("canonical_label") != observation.get("collection_effort_unit")
    ):
        reasons.append("MISSING_APPROVED_EFFORT_UNIT_MAPPING")
    method = _mapping(observation, "collection_method")
    if (
        method is None
        or method.get("canonical_id") not in _METHODS
        or method.get("canonical_label") != observation.get("collection_method")
    ):
        reasons.append("INCOMPATIBLE_COLLECTION_METHOD")
    if "SAMPLING_IMPRACTICAL" in _flag_codes(observation):
        reasons.append("SAMPLING_IMPRACTICAL")
    return reasons


def _stratum(observation: Mapping[str, Any], metric_id: str) -> dict[str, object]:
    event = observation.get("sampling_event")
    event = event if isinstance(event, Mapping) else {}
    return {
        "source_agency": observation.get("source_agency"),
        "source_dataset_id": observation.get("source_dataset_id"),
        "data_source_version_id": observation.get("data_source_version_id"),
        "canonical_method_version": observation.get("method_version"),
        "sampling_site": observation.get("sampling_site"),
        "source_geography": observation.get("source_geography"),
        "event": {
            key: event.get(key)
            for key in (
                "source_event_id",
                "source_sample_id",
                "source_subsample_id",
                "source_batch_id",
            )
        },
        "date": observation.get("surveillance_period_start"),
        "tick_species": observation.get("tick_species"),
        "life_stage": observation.get("life_stage"),
        "pathogen_name": observation.get("pathogen_name") if metric_id == PREVALENCE else None,
        "collection_method": observation.get("collection_method") if metric_id == DENSITY else None,
    }


def calculate_infected_tick_metric(
    metric_id: str,
    observations: Sequence[Mapping[str, Any]],
    *,
    output_unit: str | None = None,
) -> dict[str, object]:
    """Calculate one approved native stratum, or return its unavailable evidence."""
    if metric_id not in _DATASETS:
        raise ValueError("metric is not approved by infected-tick-metrics-v1")
    if not observations:
        raise ValueError("at least one canonical input is required")
    ordered = sorted(observations, key=lambda item: str(item.get("canonical_observation_id", "")))
    ids = [item.get("canonical_observation_id") for item in ordered]
    if any(not _text(item) for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("canonical input IDs must be present and unique")
    profiles = [assess_surveillance_quality(item) for item in ordered]
    reasons = []
    for item, profile in zip(ordered, profiles, strict=True):
        reasons.extend(_base_reasons(item, metric_id))
        reasons.extend(_quality_reasons(profile, metric_id))
        reasons.extend(
            _prevalence_reasons(item) if metric_id == PREVALENCE else _density_reasons(item)
        )
    first = ordered[0]
    stratum = _stratum(first, metric_id)
    if any(_stratum(item, metric_id) != stratum for item in ordered[1:]):
        reasons.append("INCOMPATIBLE_NATIVE_STRATUM")
    if metric_id == DENSITY and len(ordered) != 1:
        reasons.append("CROSS_RECORD_DENSITY_AGGREGATION_NOT_APPROVED")
    if metric_id == PREVALENCE and len({item.get("source_record_id") for item in ordered}) != len(
        ordered
    ):
        reasons.append("REVISION_SELECTION_NOT_APPROVED")
    unit = "proportion" if metric_id == PREVALENCE else "ticks_per_square_metre"
    if output_unit not in (None, unit, "ticks_per_hectare" if metric_id == DENSITY else unit):
        reasons.append("UNSUPPORTED_OUTPUT_CONVERSION")
    numerator: int | None = None
    denominator: int | float | None = None
    value: float | None = None
    presentation_conversion: dict[str, object] | None = None
    if metric_id == PREVALENCE:
        counts = [item.get("ticks_positive") for item in ordered]
        tested = [item.get("ticks_tested") for item in ordered]
        if all(isinstance(item, int) and not isinstance(item, bool) for item in counts):
            numerator = sum(item for item in counts if isinstance(item, int))
        if all(isinstance(item, int) and not isinstance(item, bool) for item in tested):
            denominator = sum(item for item in tested if isinstance(item, int))
    else:
        numerator = (
            first.get("ticks_collected")
            if isinstance(first.get("ticks_collected"), int)
            and not isinstance(first.get("ticks_collected"), bool)
            else None
        )
        effort = first.get("collection_effort_value")
        denominator = (
            effort
            if isinstance(effort, (int, float))
            and not isinstance(effort, bool)
            and math.isfinite(effort)
            else None
        )
    if not reasons and numerator is not None and denominator is not None:
        try:
            value = numerator / denominator
        except OverflowError:
            value = None
        if value is None or not math.isfinite(value):
            value = None
            reasons.append("NONFINITE_CALCULATED_VALUE")
        elif output_unit == "ticks_per_hectare":
            converted_value, conversion_rule = convert_value(
                field="abundance_unit",
                value=value,
                from_canonical_id="TICKS_PER_SQUARE_METRE",
                to_canonical_id="TICKS_PER_HECTARE",
                denominator_present=True,
            )
            if math.isfinite(converted_value):
                presentation_conversion = {
                    "value": converted_value,
                    "unit": "ticks_per_hectare",
                    "conversion_rule_id": conversion_rule,
                }
    identity = {
        "metric_id": metric_id,
        "methodology_version": METHODOLOGY_VERSION,
        "stratum": stratum,
        "inputs": [
            {
                "canonical_observation_id": item.get("canonical_observation_id"),
                "source_record_id": item.get("source_record_id"),
                "ingestion_run_id": item.get("ingestion_run_id"),
                "artifact_id": item.get("artifact_id"),
            }
            for item in ordered
        ],
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    metric_identity = f"tickmetric:v1:{digest}"
    unique_reasons = list(dict.fromkeys(reasons))
    propagation = propagate_surveillance_quality(
        ordered,
        profiles,
        transformation_id=metric_identity,
        transformation_version=CALCULATION_VERSION,
        added_reason_codes=unique_reasons,
        added_limitations=["NOT_COUNTY_REPRESENTATIVE"],
    )
    return {
        "metric_identity": metric_identity,
        "metric_id": metric_id,
        "methodology_version": METHODOLOGY_VERSION,
        "calculation_version": CALCULATION_VERSION,
        "state": "NUMERIC" if value is not None else "UNAVAILABLE",
        "value": value,
        "numerator": numerator,
        "denominator": denominator,
        "unit": unit,
        "native_grain": "SITE_EVENT",
        "stratum": stratum,
        "source_geography": first.get("source_geography"),
        "county_relationship": first.get("county_relationship"),
        "representativeness": "NOT_COUNTY_REPRESENTATIVE",
        "input_canonical_observation_ids": ids,
        "source_lineage": [
            {key: item.get(key) for key in _REQUIRED_LINEAGE}
            | {
                "normalization": item.get("normalization"),
                "source_testing_id": _part(item, "sampling_event", "source_testing_id"),
            }
            for item in ordered
        ],
        "presentation_conversion": presentation_conversion,
        "unavailable_reasons": unique_reasons,
        "quality_propagation": propagation,
    }
