"""Cross-contract compatibility gates composed from the existing semantic validators.

Callers supply authority snapshots; this module does not fetch or publish data.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from lyme_gap_atlas_data.semantic_domain import meaning_signature, validate_measures
from lyme_gap_atlas_data.semantic_lineage import validate_lineage
from lyme_gap_atlas_data.semantic_metadata import validate_metadata, validate_metadata_revisions
from lyme_gap_atlas_data.semantic_source_mappings import _bind_source


class Outcome(StrEnum):
    IDENTICAL = "IDENTICAL"
    COMPATIBLE = "COMPATIBLE"
    REQUIRES_NEW_REVISION = "REQUIRES_NEW_REVISION"
    REQUIRES_NEW_SEMANTIC_VERSION = "REQUIRES_NEW_SEMANTIC_VERSION"
    INCOMPATIBLE = "INCOMPATIBLE"
    NOT_COMPARABLE = "NOT_COMPARABLE"


@dataclass(frozen=True)
class Compatibility:
    outcome: Outcome
    reason_code: str


class SemanticGovernanceError(ValueError):
    """An incompatible or unversioned transition was submitted."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


_BREAKING = {
    "unit": "UNIT_INCOMPATIBLE",
    "denominator": "DENOMINATOR_INCOMPATIBLE",
    "geography_grain": "GEOGRAPHY_INCOMPATIBLE",
    "temporal_semantics": "TEMPORAL_SEMANTICS_INCOMPATIBLE",
    "definition": "SEMANTIC_VERSION_REQUIRED",
    "data_type": "SEMANTIC_VERSION_REQUIRED",
    "origin": "SEMANTIC_VERSION_REQUIRED",
    "indicator_id": "SEMANTIC_VERSION_REQUIRED",
    "methodology_version": "SEMANTIC_VERSION_REQUIRED",
    "allowed_value_states": "SEMANTIC_VERSION_REQUIRED",
}


def _version(value: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def compare_measure(old: Mapping[str, Any], new: Mapping[str, Any]) -> Compatibility:
    """Classify exact reviewed measure transitions; never infer comparability."""
    validate_measures([old])
    validate_measures([new])
    if old["measure_id"] != new["measure_id"]:
        return Compatibility(Outcome.NOT_COMPARABLE, "MEASURE_ID_DIFFERENT")
    prior = _version(old["semantic_version"])
    candidate = _version(new["semantic_version"])
    if candidate < prior:
        return Compatibility(Outcome.INCOMPATIBLE, "SEMANTIC_VERSION_REGRESSION")
    for field, reason in _BREAKING.items():
        if old[field] != new[field]:
            return Compatibility(Outcome.REQUIRES_NEW_SEMANTIC_VERSION, reason)
    old_strata = set(old["allowed_strata"])
    new_strata = set(new["allowed_strata"])
    if not old_strata <= new_strata:
        return Compatibility(Outcome.INCOMPATIBLE, "STRATUM_REMOVED")
    if old_strata != new_strata:
        return Compatibility(Outcome.COMPATIBLE, "OPTIONAL_STRATUM_ADDED")
    if meaning_signature(old) == meaning_signature(new):
        return Compatibility(
            Outcome.IDENTICAL if prior == candidate else Outcome.COMPATIBLE,
            "MEANING_UNCHANGED",
        )
    return Compatibility(Outcome.INCOMPATIBLE, "UNKNOWN_SEMANTIC_CHANGE")


def require_measure_transition(old: Mapping[str, Any], new: Mapping[str, Any]) -> Compatibility:
    result = compare_measure(old, new)
    old_version = _version(old["semantic_version"])
    new_version = _version(new["semantic_version"])
    if result.outcome == Outcome.REQUIRES_NEW_SEMANTIC_VERSION:
        if new_version[0] <= old_version[0]:
            raise SemanticGovernanceError(result.reason_code)
    elif result.reason_code == "OPTIONAL_STRATUM_ADDED":
        if new_version[:2] <= old_version[:2]:
            raise SemanticGovernanceError("SEMANTIC_VERSION_REQUIRED")
    elif result.outcome in {Outcome.INCOMPATIBLE, Outcome.NOT_COMPARABLE}:
        raise SemanticGovernanceError(result.reason_code)
    return result


def compare_metadata(old: Mapping[str, Any], new: Mapping[str, Any]) -> Compatibility:
    try:
        validate_metadata(old)
        validate_metadata(new)
    except ValueError as exc:
        raise SemanticGovernanceError("METADATA_REVISION_INVALID") from exc
    if old["metadata_id"] != new["metadata_id"]:
        return Compatibility(Outcome.NOT_COMPARABLE, "METADATA_ID_DIFFERENT")
    if old["revision_id"] == new["revision_id"]:
        if old != new:
            raise SemanticGovernanceError("IMMUTABLE_METADATA_COLLISION")
        return Compatibility(Outcome.IDENTICAL, "METADATA_IDENTICAL")
    if new["metadata_revision"] != old["metadata_revision"] + 1:
        raise SemanticGovernanceError("METADATA_REVISION_INVALID")
    if (
        old["meaning_signature"] != new["meaning_signature"]
        or old["definition"] != new["definition"]
    ):
        raise SemanticGovernanceError("SEMANTIC_VERSION_REQUIRED")
    if old["limitations"] != new["limitations"] and new["steward_review"]["state"] != "REVIEWED":
        raise SemanticGovernanceError("METADATA_REVISION_INVALID")
    return Compatibility(Outcome.COMPATIBLE, "METADATA_REVISION_VALID")


def compare_mapping(old: Mapping[str, Any], new: Mapping[str, Any]) -> Compatibility:
    if old["id"] != new["id"]:
        return Compatibility(Outcome.NOT_COMPARABLE, "MAPPING_ID_DIFFERENT")
    if old == new:
        return Compatibility(Outcome.IDENTICAL, "MAPPING_IDENTICAL")
    meaning_fields = ("measure_id", "origin", "grain", "time", "field", "required_strata")
    if any(old.get(field) != new.get(field) for field in meaning_fields):
        return Compatibility(Outcome.REQUIRES_NEW_SEMANTIC_VERSION, "MAPPING_MEANING_CHANGED")
    source_fields = ("resource_key", "source_id", "dataset_id", "product", "definition_version")
    if any(old.get(field) != new.get(field) for field in source_fields):
        return Compatibility(Outcome.INCOMPATIBLE, "UNKNOWN_GOVERNED_MAPPING")
    if old.get("vintage") != new.get("vintage"):
        return Compatibility(Outcome.REQUIRES_NEW_REVISION, "SOURCE_VINTAGE_CHANGED")
    return Compatibility(Outcome.INCOMPATIBLE, "UNKNOWN_MAPPING_CHANGE")


def compare_revision(old: Mapping[str, Any], new: Mapping[str, Any]) -> Compatibility:
    if old["observation_key"] != new["observation_key"]:
        return Compatibility(Outcome.NOT_COMPARABLE, "OBSERVATION_KEY_DIFFERENT")
    if old["revision_id"] == new["revision_id"]:
        if old != new:
            raise SemanticGovernanceError("IMMUTABLE_REVISION_COLLISION")
        return Compatibility(Outcome.IDENTICAL, "REVISION_IDENTICAL")
    return Compatibility(Outcome.REQUIRES_NEW_REVISION, "OBSERVATION_PAYLOAD_CHANGED")


def compare_lineage(old: Mapping[str, Any], new: Mapping[str, Any]) -> Compatibility:
    if old["observation"]["observation_key"] != new["observation"]["observation_key"]:
        return Compatibility(Outcome.NOT_COMPARABLE, "OBSERVATION_KEY_DIFFERENT")
    if old["lineage_id"] == new["lineage_id"]:
        if old != new:
            raise SemanticGovernanceError("IMMUTABLE_LINEAGE_COLLISION")
        return Compatibility(Outcome.IDENTICAL, "LINEAGE_IDENTICAL")
    return Compatibility(Outcome.REQUIRES_NEW_REVISION, "LINEAGE_CHANGED")


def validate_mapping_transition(
    old: Mapping[str, Mapping[str, Any]],
    new: Mapping[str, Mapping[str, Any]],
    deprecations: Mapping[str, Mapping[str, Any]],
) -> None:
    """Preserve mapping identities; removals require machine-readable migration."""
    for identity, prior in old.items():
        if identity not in new:
            record = deprecations.get(identity)
            if (
                not record
                or record.get("identity") != identity
                or record.get("kind") != "SOURCE_MAPPING"
                or record.get("state") != "DEPRECATED"
                or not isinstance(record.get("effective_semantic_version"), str)
                or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", record["effective_semantic_version"])
                or not (
                    record.get("replacement_identity") is None
                    or record.get("replacement_identity") in new
                )
                or not record.get("migration_expectation")
            ):
                raise SemanticGovernanceError("MAPPING_REMOVAL_UNDECLARED")
            continue
        result = compare_mapping(prior, new[identity])
        if result.outcome == Outcome.REQUIRES_NEW_REVISION:
            raise SemanticGovernanceError("SOURCE_MAPPING_REVISION_REQUIRED")
        if result.outcome in {Outcome.INCOMPATIBLE, Outcome.REQUIRES_NEW_SEMANTIC_VERSION}:
            raise SemanticGovernanceError(result.reason_code)


def compare_release(old: Mapping[str, Any], new: Mapping[str, Any]) -> Compatibility:
    """Compare one candidate to the immutable published county contract snapshot."""
    fields = (
        "schema",
        "schema_version",
        "methodology_version",
        "scope",
        "transformation",
        "county_count",
        "observations_per_county",
        "source_slots",
        "source_identities",
        "score_defaults",
        "observation_slots",
        "public_views",
        "value_state_samples",
        "historical_exceptions",
    )
    if any(old.get(field) != new.get(field) for field in fields):
        return Compatibility(Outcome.INCOMPATIBLE, "RELEASE_BASELINE_REGRESSION")
    if old.get("release_id") == new.get("release_id"):
        if old == new:
            return Compatibility(Outcome.IDENTICAL, "RELEASE_IDENTICAL")
        return Compatibility(Outcome.INCOMPATIBLE, "RELEASE_ID_REUSED")
    return Compatibility(Outcome.REQUIRES_NEW_REVISION, "NEW_RELEASE_REQUIRED")


def validate_historical_release_adapter(
    measure_id: str,
    native_grain: str,
    lineage_source_slots: Sequence[str],
    baseline: Mapping[str, Any],
) -> None:
    """Block unsupported reinterpretation of two historical physical slots."""
    exceptions = baseline["historical_exceptions"]
    if measure_id == "incidence_floor_2023":
        required = exceptions[measure_id]["required_inputs"]
        if len(lineage_source_slots) != len(required) or set(lineage_source_slots) != set(required):
            raise SemanticGovernanceError("HISTORICAL_INPUTS_INCOMPLETE")
    if measure_id == "state_unallocated_records_2023":
        if native_grain != exceptions[measure_id]["native_grain"]:
            raise SemanticGovernanceError("GEOGRAPHY_INCOMPATIBLE")
        if not exceptions[measure_id]["county_observation_adapter_allowed"]:
            raise SemanticGovernanceError("STATE_NATIVE_ADAPTER_UNSUPPORTED")


def validate_cross_contract(
    measures: Sequence[Mapping[str, Any]],
    metadata: Sequence[Mapping[str, Any]],
    lineages: Sequence[Mapping[str, Any]],
    authority: Mapping[str, Any],
    mappings: Mapping[str, Mapping[str, Any]],
    mapped_records: Sequence[Mapping[str, Any]] = (),
) -> None:
    """Resolve exact measure, metadata, lineage, source and result references."""
    validate_measures(measures)
    try:
        validate_metadata_revisions(metadata)
    except ValueError as exc:
        raise SemanticGovernanceError("METADATA_REVISION_INVALID") from exc
    measure_ids = {(m["measure_id"], m["semantic_version"]) for m in measures}
    metadata_ids = {(m["metadata_id"], m["revision_id"]) for m in metadata}
    for rule in mappings.values():
        if not any(m[0] == rule["measure_id"] for m in measure_ids):
            raise SemanticGovernanceError("MEASURE_REFERENCE_INVALID")
    for lineage in lineages:
        observation = lineage["observation"]
        if (observation["measure_id"], observation["measure_version"]) not in measure_ids:
            raise SemanticGovernanceError("MEASURE_REFERENCE_INVALID")
        embedded = lineage["metadata"]
        if (embedded["metadata_id"], embedded["revision_id"]) not in metadata_ids:
            raise SemanticGovernanceError("METADATA_REVISION_INVALID")
        if not any(m["revision_id"] == embedded["revision_id"] for m in metadata):
            raise SemanticGovernanceError("METADATA_REVISION_INVALID")
        try:
            validate_lineage(lineage, authority)
        except ValueError as exc:
            raise SemanticGovernanceError("LINEAGE_REFERENCE_INVALID") from exc
    lineage_ids = {item["lineage_id"] for item in lineages}
    for item in mapped_records:
        mapping_id = item.get("mapping_id")
        mapping = mappings.get(mapping_id) if isinstance(mapping_id, str) else None
        if mapping is None:
            raise SemanticGovernanceError("UNKNOWN_GOVERNED_MAPPING")
        if item.get("measure_id") != mapping["measure_id"]:
            raise SemanticGovernanceError("MEASURE_REFERENCE_INVALID")
        if item.get("lineage_id") not in lineage_ids or item.get("lineage") not in lineages:
            raise SemanticGovernanceError("LINEAGE_REFERENCE_INVALID")
        lineage = item["lineage"]
        if item.get("metadata_revision_id") != lineage["metadata_revision_id"]:
            raise SemanticGovernanceError("METADATA_REVISION_INVALID")
        try:
            for edge in lineage["edges"]:
                _bind_source(edge, mapping, authority)
        except ValueError as exc:
            raise SemanticGovernanceError("UNKNOWN_GOVERNED_MAPPING") from exc
