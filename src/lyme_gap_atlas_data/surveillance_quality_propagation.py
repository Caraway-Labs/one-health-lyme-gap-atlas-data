"""Pure, non-metric propagation of canonical surveillance quality evidence.

This module carries already-assessed ``surveillance-quality-profile-v1``
components into a bounded transformation envelope.  It deliberately does not
calculate an epidemiological value, pool sources, aggregate geography, decide
comparability, assign a score, or create a persistent record.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .surveillance_quality import DIMENSIONS, QUALITY_METHOD_VERSION

PROPAGATION_SCHEMA_VERSION = "surveillance-quality-propagation-v1"

_SAFE_INPUT_FIELDS = (
    "canonical_observation_id",
    "source_dataset_id",
    "data_source_version_id",
    "source_record_id",
    "method_version",
    "observation_type",
    "reported_or_derived",
    "missingness",
    "quality_flags",
    "limitations",
)
_RETAINED_VALUE_FIELDS = (
    "ticks_collected",
    "collection_effort_value",
    "ticks_tested",
    "ticks_positive",
)
_STATES = {"ASSESSED", "UNKNOWN", "NOT_APPLICABLE"}


def propagate_surveillance_quality(
    observations: Sequence[Mapping[str, Any]],
    quality_profiles: Sequence[Mapping[str, Any]],
    *,
    transformation_id: str,
    transformation_version: str,
    added_reason_codes: Sequence[str] = (),
    added_limitations: Sequence[str] = (),
) -> dict[str, object]:
    """Return a deterministic metadata envelope for a bounded transformation.

    ``observations`` are retained as distinct inputs; their values are copied
    without calculation solely so a reported zero cannot become missing.  The
    input profile is retained per input.  The per-dimension summary is
    deliberately conservative: any ``UNKNOWN`` stays ``UNKNOWN``; otherwise
    an ``ASSESSED`` input stays ``ASSESSED``; only all-``NOT_APPLICABLE`` is
    ``NOT_APPLICABLE``.  This is metadata propagation, not an aggregation rule.
    """
    if not transformation_id.strip() or not transformation_version.strip():
        raise ValueError("transformation_id and transformation_version are required")
    if not observations or len(observations) != len(quality_profiles):
        raise ValueError("observations and quality_profiles must be non-empty and aligned")

    inputs = []
    profiles_by_id: dict[str, Mapping[str, Any]] = {}
    for observation, profile in zip(observations, quality_profiles, strict=True):
        observation_id = _required_text(observation, "canonical_observation_id")
        if _required_text(profile, "canonical_observation_id") != observation_id:
            raise ValueError("quality profile must match its canonical observation")
        if profile.get("quality_method_version") != QUALITY_METHOD_VERSION:
            raise ValueError("quality profile must use surveillance-quality-profile-v1")
        if observation_id in profiles_by_id:
            raise ValueError("input canonical observation IDs must be unique")
        _validated_components(profile)
        profiles_by_id[observation_id] = profile
        inputs.append(_input_envelope(observation, profile))

    return {
        "propagation_schema_version": PROPAGATION_SCHEMA_VERSION,
        "transformation_id": transformation_id,
        "transformation_version": transformation_version,
        "quality_method_version": QUALITY_METHOD_VERSION,
        "input_canonical_observation_ids": list(profiles_by_id),
        "inputs": inputs,
        "propagated_components": [
            _propagated_component(dimension, profiles_by_id) for dimension in DIMENSIONS
        ],
        "inherited_limitations": _inherited_limitations(observations, quality_profiles),
        "transformation_added_reason_codes": _unique_text(added_reason_codes),
        "transformation_added_limitations": _unique_text(added_limitations),
    }


def serialize_safe_propagation(envelope: Mapping[str, Any]) -> dict[str, object]:
    """Project an envelope for consumers without raw values or artifact lineage.

    The projection keeps source/version, quality components, limitation text,
    and transformation identity.  It intentionally omits artifact IDs/URIs,
    signed URLs, credentials, source-record payloads, and retained numeric
    input values.
    """
    _required_text(envelope, "transformation_id")
    _required_text(envelope, "transformation_version")
    if envelope.get("quality_method_version") != QUALITY_METHOD_VERSION:
        raise ValueError("envelope must retain surveillance-quality-profile-v1")
    inputs = envelope.get("inputs")
    components = envelope.get("propagated_components")
    if not isinstance(inputs, list) or not isinstance(components, list):
        raise ValueError("envelope inputs and propagated_components must be lists")
    return {
        "propagation_schema_version": PROPAGATION_SCHEMA_VERSION,
        "transformation_id": envelope["transformation_id"],
        "transformation_version": envelope["transformation_version"],
        "quality_method_version": QUALITY_METHOD_VERSION,
        "input_canonical_observation_ids": list(envelope["input_canonical_observation_ids"]),
        "input_sources": [
            {
                "canonical_observation_id": item["canonical_observation_id"],
                "source_dataset_id": item["source_dataset_id"],
                "data_source_version_id": item["data_source_version_id"],
                "canonical_method_version": item["canonical_method_version"],
            }
            for item in inputs
        ],
        "propagated_components": components,
        "inherited_limitations": list(envelope["inherited_limitations"]),
        "transformation_added_reason_codes": list(envelope["transformation_added_reason_codes"]),
        "transformation_added_limitations": list(envelope["transformation_added_limitations"]),
    }


def _input_envelope(
    observation: Mapping[str, Any], profile: Mapping[str, Any]
) -> dict[str, object]:
    safe = {field: observation.get(field) for field in _SAFE_INPUT_FIELDS if field in observation}
    safe["canonical_method_version"] = safe.pop("method_version", None)
    safe["quality_profile"] = {
        "quality_method_version": profile["quality_method_version"],
        "components": profile["components"],
    }
    safe["retained_input_values"] = {
        field: observation.get(field) for field in _RETAINED_VALUE_FIELDS if field in observation
    }
    return safe


def _propagated_component(
    dimension: str, profiles_by_id: Mapping[str, Mapping[str, Any]]
) -> dict[str, object]:
    input_components = []
    for observation_id, profile in profiles_by_id.items():
        component = next(
            item for item in _validated_components(profile) if item["dimension"] == dimension
        )
        input_components.append(
            {
                "canonical_observation_id": observation_id,
                "state": component["state"],
                "reason_codes": list(component["reason_codes"]),
            }
        )
    states = [str(item["state"]) for item in input_components]
    summary_state = (
        "UNKNOWN"
        if "UNKNOWN" in states
        else "ASSESSED"
        if "ASSESSED" in states
        else "NOT_APPLICABLE"
    )
    return {
        "dimension": dimension,
        "state": summary_state,
        "reason_codes": _unique_text(
            code for item in input_components for code in item["reason_codes"]
        ),
        "input_components": input_components,
    }


def _inherited_limitations(
    observations: Sequence[Mapping[str, Any]], quality_profiles: Sequence[Mapping[str, Any]]
) -> list[str]:
    values: list[object] = []
    for observation in observations:
        values.extend(observation.get("limitations", []))
        relationship = observation.get("county_relationship")
        if isinstance(relationship, Mapping) and relationship.get("representativeness"):
            values.append(f"REPRESENTATIVENESS_{relationship['representativeness']}")
    for profile in quality_profiles:
        for component in _validated_components(profile):
            values.extend(component["reason_codes"])
    return _unique_text(values)


def _validated_components(profile: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    components = profile.get("components")
    if not isinstance(components, list) or len(components) != len(DIMENSIONS):
        raise ValueError("quality profile must contain each v1 component exactly once")
    by_dimension: dict[str, Mapping[str, Any]] = {}
    for component in components:
        if not isinstance(component, Mapping):
            raise ValueError("quality profile components must be objects")
        dimension = component.get("dimension")
        state = component.get("state")
        reason_codes = component.get("reason_codes")
        if dimension not in DIMENSIONS or dimension in by_dimension or state not in _STATES:
            raise ValueError("quality profile components are invalid")
        if (
            not isinstance(reason_codes, list)
            or not reason_codes
            or not all(isinstance(code, str) and code for code in reason_codes)
        ):
            raise ValueError("quality profile reason codes are invalid")
        by_dimension[str(dimension)] = component
    if set(by_dimension) != set(DIMENSIONS):
        raise ValueError("quality profile must contain each v1 component exactly once")
    return [by_dimension[dimension] for dimension in DIMENSIONS]


def _required_text(value: Mapping[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{field} is required")
    return item


def _unique_text(values: Sequence[object] | Any) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if isinstance(value, str) and value))
