"""Deterministic analytical quality profiles for canonical surveillance evidence.

This module describes evidence already retained by the canonical contract.  It
does not score, aggregate, authorize a source, or infer surveillance coverage,
biological absence, disease risk, or method comparability.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

QUALITY_METHOD_VERSION = "surveillance-quality-profile-v1"

DIMENSIONS = (
    "TECHNICAL_SOURCE_VALIDITY",
    "PROVENANCE_COMPLETENESS",
    "EFFORT_DENOMINATOR_COMPLETENESS",
    "METHOD_DOCUMENTATION",
    "SPATIAL_REPRESENTATIVENESS",
    "TEMPORAL_COVERAGE_CONTINUITY",
    "TAXONOMIC_LIFE_STAGE_RESOLUTION",
    "PATHOGEN_TESTING_DENOMINATOR_VALIDITY",
    "COMPARABILITY_ELIGIBILITY",
    "FRESHNESS_REVISION_STATE",
    "KNOWN_SOURCE_LIMITATIONS",
)

_STATUS_TYPES = {"VECTOR_PRESENCE_STATUS", "PATHOGEN_PRESENCE_STATUS"}
_NEON_DATASETS = {"DP1.10093.001", "DP1.10092.001"}
_NEON_RELEASE = "RELEASE-2026"
_STALE_FLAGS = {"STALE_OR_REVISION_SENSITIVE", "SOURCE_REVISION_SENSITIVE"}


def _component(dimension: str, state: str, *reason_codes: str) -> dict[str, object]:
    return {
        "dimension": dimension,
        "state": state,
        "reason_codes": list(dict.fromkeys(reason_codes)),
    }


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _quality_flags(observation: Mapping[str, Any]) -> set[str]:
    flags = observation.get("quality_flags", [])
    return {flag for flag in flags if isinstance(flag, str)} if isinstance(flags, list) else set()


def _missingness(observation: Mapping[str, Any], field: str) -> str | None:
    values = observation.get("missingness", {})
    value = values.get(field) if isinstance(values, Mapping) else None
    return value if isinstance(value, str) else None


def _is_neon_release(observation: Mapping[str, Any]) -> bool:
    return (
        observation.get("source_dataset_id") in _NEON_DATASETS
        and observation.get("data_source_version_id") == _NEON_RELEASE
    )


def assess_surveillance_quality(observation: Mapping[str, Any]) -> dict[str, object]:
    """Return the v1 analytical profile for one structurally valid observation.

    The caller is responsible for canonical schema validation.  The profile is
    deliberately component-level: ``ASSESSED`` says evidence was evaluated,
    not that it is universally high quality.  Limiting evidence is carried by
    reason codes, while absent evidence remains ``UNKNOWN``.
    """
    observation_type = observation.get("observation_type")
    flags = _quality_flags(observation)
    is_status = observation_type in _STATUS_TYPES
    is_neon = _is_neon_release(observation)

    components: list[dict[str, object]] = [
        _component(
            "TECHNICAL_SOURCE_VALIDITY",
            "ASSESSED",
            "CANONICAL_RECORD_STRUCTURALLY_VALID",
        )
    ]

    lineage_fields = (
        "canonical_observation_id",
        "source_dataset_id",
        "data_source_version_id",
        "source_record_id",
        "ingestion_run_id",
        "artifact_id",
        "retrieved_at",
        "method_version",
    )
    components.append(
        _component(
            "PROVENANCE_COMPLETENESS",
            "ASSESSED"
            if all(_has_text(observation.get(field)) for field in lineage_fields)
            else "UNKNOWN",
            "CANONICAL_LINEAGE_RETAINED"
            if all(_has_text(observation.get(field)) for field in lineage_fields)
            else "PROVENANCE_INCOMPLETE",
        )
    )

    if is_status:
        components.append(
            _component(
                "EFFORT_DENOMINATOR_COMPLETENESS",
                "NOT_APPLICABLE",
                "STATUS_DESIGN_NO_ACTIVE_EFFORT",
            )
        )
    elif "SAMPLING_IMPRACTICAL" in flags:
        components.append(
            _component("EFFORT_DENOMINATOR_COMPLETENESS", "UNKNOWN", "SAMPLING_IMPRACTICAL")
        )
    elif isinstance(observation.get("collection_effort_value"), (int, float)) and not isinstance(
        observation.get("collection_effort_value"), bool
    ):
        effort_codes = ["EFFORT_DOCUMENTED"]
        if observation.get("ticks_collected") == 0:
            effort_codes.append("VALID_ZERO_WITH_DOCUMENTED_EFFORT")
        components.append(_component("EFFORT_DENOMINATOR_COMPLETENESS", "ASSESSED", *effort_codes))
    else:
        components.append(
            _component(
                "EFFORT_DENOMINATOR_COMPLETENESS",
                "UNKNOWN",
                "EFFORT_UNKNOWN"
                if _missingness(observation, "collection_effort_value") == "UNKNOWN"
                else "EFFORT_UNAVAILABLE",
            )
        )

    components.append(
        _component(
            "METHOD_DOCUMENTATION",
            "ASSESSED" if _has_text(observation.get("collection_method")) else "UNKNOWN",
            "METHOD_DOCUMENTED"
            if _has_text(observation.get("collection_method"))
            else "METHOD_NOT_REPORTED",
        )
    )

    relationship = observation.get("county_relationship")
    if is_status:
        spatial = _component("SPATIAL_REPRESENTATIVENESS", "ASSESSED", "COUNTY_NATIVE_STATUS")
    elif isinstance(relationship, Mapping):
        codes = ["SITE_EVENT_NOT_COUNTY_REPRESENTATIVE"]
        mapping_status = relationship.get("mapping_status")
        if mapping_status == "UNMAPPED":
            codes.append("UNMAPPED_SITE_GEOGRAPHY")
        elif mapping_status == "AMBIGUOUS":
            codes.append("AMBIGUOUS_SITE_GEOGRAPHY")
        else:
            codes.append("PARTIAL_SPATIAL_COVERAGE")
        spatial = _component("SPATIAL_REPRESENTATIVENESS", "ASSESSED", *codes)
    else:
        spatial = _component("SPATIAL_REPRESENTATIVENESS", "UNKNOWN", "REPRESENTATIVENESS_UNKNOWN")
    components.append(spatial)

    temporal = observation.get("temporal_semantics")
    if temporal == "CUMULATIVE_THROUGH_DATE":
        components.append(
            _component("TEMPORAL_COVERAGE_CONTINUITY", "ASSESSED", "CUMULATIVE_STATUS_ONLY")
        )
    elif _has_text(temporal) and (
        _has_text(observation.get("surveillance_period_start"))
        or _has_text(observation.get("surveillance_period_end"))
    ):
        components.append(
            _component("TEMPORAL_COVERAGE_CONTINUITY", "ASSESSED", "OBSERVATION_TIME_RETAINED")
        )
    else:
        components.append(
            _component("TEMPORAL_COVERAGE_CONTINUITY", "UNKNOWN", "TEMPORAL_COVERAGE_UNKNOWN")
        )

    life_stage = observation.get("life_stage")
    components.append(
        _component(
            "TAXONOMIC_LIFE_STAGE_RESOLUTION",
            "ASSESSED"
            if _has_text(life_stage) and life_stage not in {"UNKNOWN", "NOT_REPORTED", "MIXED"}
            else "UNKNOWN",
            "TAXON_LIFE_STAGE_DOCUMENTED"
            if _has_text(life_stage) and life_stage not in {"UNKNOWN", "NOT_REPORTED", "MIXED"}
            else "LIFE_STAGE_NOT_RESOLVED",
        )
    )

    ticks_tested = observation.get("ticks_tested")
    if observation_type != "PATHOGEN_TESTING":
        components.append(
            _component(
                "PATHOGEN_TESTING_DENOMINATOR_VALIDITY",
                "NOT_APPLICABLE",
                "NOT_A_PATHOGEN_TESTING_OBSERVATION",
            )
        )
    elif isinstance(ticks_tested, int) and not isinstance(ticks_tested, bool) and ticks_tested > 0:
        denominator_codes = ["INDIVIDUAL_TEST_DENOMINATOR_VALID"]
        if is_neon:
            denominator_codes.append("NON_RANDOM_PATHOGEN_TEST_SELECTION")
        components.append(
            _component("PATHOGEN_TESTING_DENOMINATOR_VALIDITY", "ASSESSED", *denominator_codes)
        )
    else:
        components.append(
            _component(
                "PATHOGEN_TESTING_DENOMINATOR_VALIDITY", "UNKNOWN", "TEST_DENOMINATOR_UNAVAILABLE"
            )
        )

    components.append(
        _component(
            "COMPARABILITY_ELIGIBILITY",
            "ASSESSED",
            "METHOD_COMPARABILITY_NOT_ESTABLISHED",
        )
    )

    freshness_codes = ["SOURCE_VERSION_AND_RETRIEVAL_RETAINED"]
    if flags & _STALE_FLAGS:
        freshness_codes.append("STALE_OR_REVISION_SENSITIVE")
    components.append(_component("FRESHNESS_REVISION_STATE", "ASSESSED", *freshness_codes))

    if is_neon:
        source_codes = ["SOURCE_LIMITATION_RETAINED", "VARIABLE_SAMPLING_INTENSITY"]
        if observation_type == "PATHOGEN_TESTING":
            source_codes.append("NON_RANDOM_PATHOGEN_TEST_SELECTION")
        components.append(_component("KNOWN_SOURCE_LIMITATIONS", "ASSESSED", *source_codes))
    elif is_status:
        status_code = (
            "REPORTED_NO_RECORDS_NOT_BIOLOGICAL_ABSENCE"
            if observation.get("presence_status") == "NO_RECORDS"
            else "STATUS_SOURCE_LIMITATION_RETAINED"
        )
        components.append(_component("KNOWN_SOURCE_LIMITATIONS", "ASSESSED", status_code))
    else:
        components.append(
            _component("KNOWN_SOURCE_LIMITATIONS", "UNKNOWN", "SOURCE_LIMITATIONS_NOT_DOCUMENTED")
        )

    return {
        "canonical_observation_id": observation.get("canonical_observation_id"),
        "source_dataset_id": observation.get("source_dataset_id"),
        "data_source_version_id": observation.get("data_source_version_id"),
        "source_record_id": observation.get("source_record_id"),
        "ingestion_run_id": observation.get("ingestion_run_id"),
        "artifact_id": observation.get("artifact_id"),
        "retrieved_at": observation.get("retrieved_at"),
        "canonical_method_version": observation.get("method_version"),
        "quality_method_version": QUALITY_METHOD_VERSION,
        "components": components,
    }
