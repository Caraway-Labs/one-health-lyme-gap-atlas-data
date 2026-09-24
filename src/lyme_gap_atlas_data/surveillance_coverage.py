"""Categorical, source-native surveillance evidence profiles for Story #171.

Callers supply governed canonical observations and explicit source context. This
module neither acquires data nor infers a publisher snapshot from input rows.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from .surveillance_eligibility import (
    MODEL_VERSION,
    approved_source_tuple,
    attest_scientific_fields,
    proven,
    scientific_attestation,
)
from .surveillance_quality import assess_surveillance_quality
from .surveillance_quality_propagation import propagate_surveillance_quality
from .tick_normalization import load_registry

METHODOLOGY_VERSION = "surveillance-coverage-v1"
CALCULATION_VERSION = "surveillance-coverage-calculation-v2"
COUNTY = "COUNTY_STATUS_DATASET_REPRESENTATION"
SAMPLING = "ACTIVE_SITE_EVENT_SAMPLING"
EFFORT = "ACTIVE_EFFORT_DOCUMENTATION"
TESTING = "ACTIVE_TESTING_DENOMINATOR_AVAILABILITY"
CONSTRUCTS = (COUNTY, SAMPLING, EFFORT, TESTING)
_STATUS_TYPES = {"VECTOR_PRESENCE_STATUS", "PATHOGEN_PRESENCE_STATUS"}
_CDC_TYPES = {
    "CDC_IXODES_COUNTY_STATUS": "VECTOR_PRESENCE_STATUS",
    "CDC_PATHOGEN_COUNTY_STATUS": "PATHOGEN_PRESENCE_STATUS",
}
_CDC_DATASETS = {
    "CDC_IXODES_COUNTY_STATUS": "cdc-ixodes-county-status-2025",
    "CDC_PATHOGEN_COUNTY_STATUS": "cdc-ixodes-pathogen-status-2025",
}
_NEON_DATASETS = {SAMPLING: "DP1.10093.001", EFFORT: "DP1.10093.001", TESTING: "DP1.10092.001"}
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


def _part(value: Mapping[str, Any], parent: str, child: str) -> object:
    item = value.get(parent)
    return item.get(child) if isinstance(item, Mapping) else None


def _flags(observation: Mapping[str, Any]) -> set[str]:
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


def _quality_missing(profile: Mapping[str, Any], construct: str) -> list[str]:
    required = {
        "TECHNICAL_SOURCE_VALIDITY": "CANONICAL_RECORD_STRUCTURALLY_VALID",
        "PROVENANCE_COMPLETENESS": "CANONICAL_LINEAGE_RETAINED",
    }
    if construct in (SAMPLING, EFFORT):
        required["EFFORT_DENOMINATOR_COMPLETENESS"] = "EFFORT_DOCUMENTED"
        required["METHOD_DOCUMENTATION"] = "METHOD_DOCUMENTED"
    elif construct == TESTING:
        required["PATHOGEN_TESTING_DENOMINATOR_VALIDITY"] = "INDIVIDUAL_TEST_DENOMINATOR_VALID"
    components = {item["dimension"]: item for item in profile["components"]}
    return [
        f"QUALITY_EVIDENCE_MISSING_{dimension}"
        for dimension, reason in required.items()
        if components[dimension]["state"] != "ASSESSED"
        or reason not in components[dimension]["reason_codes"]
    ]


def _source_context(construct: str, context: Mapping[str, Any]) -> list[str]:
    if context.get("approved") is not True or context.get("available") is not True:
        return ["SOURCE_VERSION_UNAVAILABLE_OR_UNAPPROVED"]
    if not _text(context.get("source_dataset_id")) or not _text(context.get("source_version_id")):
        return ["SOURCE_VERSION_IDENTITY_MISSING"]
    if not approved_source_tuple(construct, context):
        return ["SOURCE_VINTAGE_TUPLE_UNPROVEN"]
    if construct == COUNTY:
        family = context.get("source_family")
        if family not in _CDC_TYPES or context.get("source_dataset_id") != _CDC_DATASETS[family]:
            return ["INELIGIBLE_SOURCE_SCOPE"]
    elif (
        context.get("source_dataset_id") != _NEON_DATASETS[construct]
        or context.get("source_version_id") != "RELEASE-2026"
    ):
        return ["INELIGIBLE_SOURCE_SCOPE"]
    return []


def _county_state(
    observations: Sequence[Mapping[str, Any]],
    context: Mapping[str, Any],
    county_fips: str | None,
    profiles: Sequence[Mapping[str, Any]],
    dimension: str | None,
) -> tuple[str, list[str]]:
    if context.get("source_geography_in_scope") is False:
        return "NOT_APPLICABLE", ["SOURCE_GEOGRAPHY_OUTSIDE_PUBLISHER_SCOPE"]
    if not _text(county_fips):
        return "UNKNOWN", ["UNRESOLVED_CANONICAL_COUNTY"]
    if not isinstance(county_fips, str) or len(county_fips) != 5 or not county_fips.isdigit():
        return "UNKNOWN", ["INVALID_CANONICAL_COUNTY_IDENTITY"]
    scope = context.get("publisher_scope")
    universe = context.get("canonical_eligible_universe")
    if not isinstance(scope, list) or not isinstance(universe, list):
        return "UNKNOWN", ["PUBLISHER_SCOPE_OR_UNIVERSE_UNPROVEN"]
    if county_fips not in scope or county_fips not in universe:
        return "NOT_APPLICABLE", ["OUTSIDE_PUBLISHER_SCOPE_OR_CANONICAL_UNIVERSE"]
    complete = (
        context.get("snapshot_complete") is True
        and context.get("scope_approved") is True
        and _text(context.get("snapshot_evidence_id"))
        and context.get("snapshot_source_version_id") == context.get("source_version_id")
        and _text(context.get("publisher_scope_version"))
        and _text(context.get("canonical_universe_version"))
        and _text(context.get("cumulative_through_date"))
    )
    if not complete:
        return "UNKNOWN", ["SNAPSHOT_COMPLETENESS_UNPROVEN"]
    expected_type = _CDC_TYPES[str(context["source_family"])]
    if any(item.get("observation_type") != expected_type for item in observations):
        return "NOT_APPLICABLE", ["INELIGIBLE_OBSERVATION_TYPE"]
    if any(item.get("county_fips") != county_fips for item in observations):
        return "UNKNOWN", ["UNRESOLVED_CANONICAL_COUNTY"]
    if any(item.get("source_agency") != "CDC" for item in observations):
        return "UNAVAILABLE", ["INELIGIBLE_SOURCE_SCOPE"]
    field = "tick_taxon" if expected_type == "VECTOR_PRESENCE_STATUS" else "pathogen_target"
    observed_field = "tick_species" if field == "tick_taxon" else "pathogen_name"
    attested = [
        scientific_attestation(
            item,
            field=field,
            role=COUNTY,
            represented_value=item.get(observed_field),
            source_context=context,
        )
        for item in observations
    ]
    if observations and (
        any(not proven(item) for item in attested)
        or any(
            dimension not in (item["canonical_id"], item["canonical_label"]) for item in attested
        )
        or len({item["canonical_id"] for item in attested}) != 1
    ):
        return "UNKNOWN", ["COUNTY_SCIENTIFIC_DIMENSION_UNPROVEN"]
    if not observations:
        external = context.get("dimension_mapping")
        attestation = scientific_attestation(
            {
                "normalization": {
                    "registry_id": load_registry()["registry_id"],
                    "registry_version": load_registry()["registry_version"],
                    "mappings": {"dimension": external},
                }
            },
            field=field,
            role=COUNTY,
            represented_value=dimension,
            source_context=context,
        )
        if not proven(attestation):
            return "UNKNOWN", ["COUNTY_SCIENTIFIC_DIMENSION_UNPROVEN"]
        return "NOT_REPORTED_IN_DATASET", ["COMPLETE_SCOPED_SNAPSHOT_OMISSION"]
    if any(_quality_missing(profile, COUNTY) for profile in profiles):
        return "UNAVAILABLE", ["REQUIRED_STRUCTURAL_OR_PROVENANCE_EVIDENCE_MISSING"]
    if any(item.get("temporal_semantics") != "CUMULATIVE_THROUGH_DATE" for item in observations):
        return "UNKNOWN", ["INCOMPATIBLE_TIME_SEMANTICS"]
    if any(
        not _text(
            item.get(
                "tick_species" if expected_type == "VECTOR_PRESENCE_STATUS" else "pathogen_name"
            )
        )
        for item in observations
    ):
        return "UNKNOWN", ["MISSING_REPORTED_DIMENSION"]
    statuses = {item.get("presence_status") for item in observations}
    revisions = {item.get("source_revision_id") for item in observations}
    if (
        len(statuses) != 1
        or len(revisions) > 1
        or len({item.get("source_record_id") for item in observations}) > 1
        or any(
            _flags(item) & {"SOURCE_REVISION_AMBIGUOUS", "REVISION_SELECTION_NOT_APPROVED"}
            for item in observations
        )
    ):
        return "UNKNOWN", ["UNRECONCILED_SOURCE_REVISION"]
    status = next(iter(statuses))
    if status not in {"ESTABLISHED", "REPORTED", "PRESENT", "NO_RECORDS"}:
        return "UNKNOWN", ["MISSING_PUBLISHER_STATUS"]
    return ("PUBLISHER_NO_RECORDS" if status == "NO_RECORDS" else "REPORTED_STATUS"), []


def _active_state(
    construct: str,
    observation: Mapping[str, Any],
    profile: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[str, list[str]]:
    kind = observation.get("observation_type")
    expected = "PATHOGEN_TESTING" if construct == TESTING else "COLLECTION_ABUNDANCE"
    if kind != expected:
        return "NOT_APPLICABLE" if construct != EFFORT else "UNAVAILABLE", [
            "INELIGIBLE_OBSERVATION_TYPE"
        ]
    if (
        observation.get("source_agency") != "NSF NEON"
        or observation.get("method_version") != "tick-surveillance-v1.2"
    ):
        return "UNAVAILABLE", ["INELIGIBLE_SOURCE_OR_CANONICAL_VERSION"]
    if any(not _text(observation.get(field)) for field in _REQUIRED_LINEAGE):
        return "UNAVAILABLE", ["MISSING_REQUIRED_PROVENANCE"]
    if (
        observation.get("native_sampling_grain") != "SITE_EVENT"
        or not _text(_part(observation, "sampling_site", "source_site_id"))
        or not _text(_part(observation, "sampling_event", "source_event_id"))
    ):
        return "UNAVAILABLE", ["MISSING_SITE_EVENT_IDENTITY"]
    if observation.get("surveillance_period_start") != observation.get(
        "surveillance_period_end"
    ) or not _text(observation.get("surveillance_period_start")):
        return "UNAVAILABLE", ["INCOMPATIBLE_EVENT_OR_PERIOD"]
    if observation.get("temporal_semantics") != "POINT_IN_TIME":
        return "UNKNOWN", ["INCOMPATIBLE_TIME_SEMANTICS"]
    if (
        _part(observation, "county_relationship", "representativeness")
        != "NOT_COUNTY_REPRESENTATIVE"
    ):
        return "UNAVAILABLE", ["MISSING_REPRESENTATIVENESS_BOUNDARY"]
    if any(
        code in _quality_missing(profile, construct)
        for code in (
            "QUALITY_EVIDENCE_MISSING_TECHNICAL_SOURCE_VALIDITY",
            "QUALITY_EVIDENCE_MISSING_PROVENANCE_COMPLETENESS",
        )
    ):
        return "UNAVAILABLE", ["REQUIRED_STRUCTURAL_OR_PROVENANCE_EVIDENCE_MISSING"]
    if _flags(observation) & {"SOURCE_REVISION_AMBIGUOUS", "REVISION_SELECTION_NOT_APPROVED"}:
        return "UNKNOWN", ["UNRECONCILED_SOURCE_REVISION"]
    if construct == TESTING:
        if observation.get("testing_scope") != "INDIVIDUAL_PATHOGEN_TEST" or not _text(
            _part(observation, "sampling_event", "source_testing_id")
        ):
            return "UNKNOWN", ["INDIVIDUAL_TEST_SCOPE_UNRESOLVED"]
        pathogen = scientific_attestation(
            observation,
            field="pathogen_target",
            role=TESTING,
            represented_value=observation.get("pathogen_name"),
            source_context=context,
        )
        result = scientific_attestation(
            observation,
            field="test_result",
            role=TESTING,
            represented_value=observation.get("test_result"),
            source_context=context,
        )
        if (
            not proven(pathogen)
            or not proven(result)
            or result.get("canonical_id") not in {"DETECTED", "NOT_DETECTED"}
        ):
            return "UNKNOWN", ["PATHOGEN_OR_RESULT_MAPPING_UNRESOLVED"]
        tested, positive = observation.get("ticks_tested"), observation.get("ticks_positive")
        if tested is None:
            return "MISSING_TEST_DENOMINATOR", ["TEST_DENOMINATOR_UNAVAILABLE"]
        if not isinstance(tested, int) or isinstance(tested, bool) or tested < 0:
            return "UNKNOWN", ["INVALID_TEST_DENOMINATOR"]
        if (
            not isinstance(positive, int)
            or isinstance(positive, bool)
            or not 0 <= positive <= tested
        ):
            return "UNKNOWN", ["INVALID_POSITIVE_COUNT"]
        if tested == 0:
            return "ZERO_TEST_DENOMINATOR", ["ZERO_TESTED_DENOMINATOR"]
        if tested != 1 or result["canonical_id"] != ("DETECTED" if positive else "NOT_DETECTED"):
            return "UNKNOWN", ["INDIVIDUAL_RESULT_COUNT_MISMATCH"]
        if _quality_missing(profile, TESTING):
            return "UNKNOWN", _quality_missing(profile, TESTING)
        return "DOCUMENTED_POSITIVE_TEST_DENOMINATOR", []
    if "SAMPLING_IMPRACTICAL" in _flags(observation):
        return "SAMPLING_IMPRACTICAL", ["SAMPLING_IMPRACTICAL"]
    effort = observation.get("collection_effort_value")
    if effort is not None and _part(observation, "missingness", "collection_effort_value") in {
        "UNKNOWN",
        "UNAVAILABLE",
        "NOT_REPORTED",
    }:
        return "UNKNOWN", ["CONFLICTING_EFFORT_MISSINGNESS"]
    if effort is None:
        reason = (
            "EFFORT_UNKNOWN"
            if _part(observation, "missingness", "collection_effort_value") == "UNKNOWN"
            else "EFFORT_UNAVAILABLE"
        )
        return ("MISSING_EFFORT" if construct == EFFORT else "UNKNOWN"), [reason]
    if (
        not isinstance(effort, (int, float))
        or isinstance(effort, bool)
        or not math.isfinite(effort)
        or effort < 0
    ):
        return "UNKNOWN", ["NONFINITE_OR_INVALID_EFFORT"]
    if effort == 0:
        return ("ZERO_EFFORT" if construct == EFFORT else "UNKNOWN"), ["ZERO_EFFORT"]
    taxon = scientific_attestation(
        observation,
        field="tick_taxon",
        role=construct,
        represented_value=observation.get("tick_species"),
        source_context=context,
    )
    stage = scientific_attestation(
        observation,
        field="life_stage",
        role=construct,
        represented_value=observation.get("life_stage"),
        source_context=context,
    )
    unit = scientific_attestation(
        observation,
        field="effort_unit",
        role=construct,
        represented_value=observation.get("collection_effort_unit"),
        source_context=context,
    )
    method = scientific_attestation(
        observation,
        field="collection_method",
        role=construct,
        represented_value=observation.get("collection_method"),
        source_context=context,
    )
    if not proven(taxon) or not proven(stage):
        return "UNKNOWN", ["COLLECTION_SCIENTIFIC_STRATUM_UNPROVEN"]
    if not proven(unit) or unit.get("canonical_id") != "SQUARE_METRE":
        return "UNKNOWN", ["MISSING_APPROVED_EFFORT_UNIT_MAPPING"]
    if not proven(method) or method.get("canonical_id") not in {"DRAG_CLOTH", "FLAG_CLOTH"}:
        return "UNKNOWN", ["COLLECTION_METHOD_UNRESOLVED"]
    if _quality_missing(profile, construct):
        return "UNKNOWN", _quality_missing(profile, construct)
    if construct == SAMPLING:
        ticks = observation.get("ticks_collected")
        if not isinstance(ticks, int) or isinstance(ticks, bool) or ticks < 0:
            return "UNKNOWN", ["COLLECTION_COMPLETION_UNRESOLVED"]
        return "SAMPLED_EVENT", []
    return "DOCUMENTED_POSITIVE_EFFORT", []


def evaluate_surveillance_coverage(
    construct: str,
    observations: Sequence[Mapping[str, Any]],
    *,
    source_context: Mapping[str, Any],
    county_fips: str | None = None,
    dimension: str | None = None,
    source_only_evidence: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Evaluate one county/dimension or one native active observation.

    County omission requires an independently approved complete snapshot marker,
    explicit publisher scope, and canonical eligible universe. A caller cannot
    establish completeness by supplying an empty observation list alone.
    """
    if construct not in CONSTRUCTS:
        raise ValueError("construct is not approved by surveillance-coverage-v1")
    if construct != COUNTY and len(observations) > 1:
        raise ValueError("active construct requires one native observation")
    if construct == COUNTY and not _text(dimension):
        raise ValueError("county construct requires an explicit taxon or pathogen dimension")
    if construct == COUNTY and any(
        item.get("observation_type") in _STATUS_TYPES
        and (
            not isinstance(item.get("county_fips"), str)
            or len(item["county_fips"]) != 5
            or not item["county_fips"].isdigit()
        )
        for item in observations
    ):
        raise ValueError("unresolved source county row requires separate source-only evidence")
    if source_only_evidence is not None and (
        construct != COUNTY or observations or county_fips is not None
    ):
        raise ValueError(
            "source-only county evidence requires unresolved county and no canonical rows"
        )
    distinct = {json.dumps(item, sort_keys=True, default=str): item for item in observations}
    ordered = sorted(
        distinct.values(),
        key=lambda item: (
            str(item.get("canonical_observation_id", "")),
            json.dumps(item, sort_keys=True, default=str),
        ),
    )
    source_errors = _source_context(construct, source_context)
    if not source_errors and any(
        item.get("source_dataset_id") != source_context["source_dataset_id"]
        or item.get("data_source_version_id") != source_context["source_version_id"]
        for item in ordered
    ):
        source_errors = ["SOURCE_CONTEXT_INPUT_MISMATCH"]
    profiles = [assess_surveillance_quality(item) for item in ordered]
    if source_errors:
        state, reasons = "UNAVAILABLE", source_errors
    elif construct == COUNTY:
        state, reasons = _county_state(ordered, source_context, county_fips, profiles, dimension)
    elif not ordered:
        state, reasons = "UNKNOWN", ["CANONICAL_EVENT_ABSENT_COMPLETENESS_UNPROVEN"]
    else:
        state, reasons = _active_state(construct, ordered[0], profiles[0], source_context)
    for profile in profiles:
        components = profile["components"]
        if not isinstance(components, list):
            raise ValueError("quality profile components must be a list")
        for component in components:
            if component["dimension"] in {
                "SPATIAL_REPRESENTATIVENESS",
                "FRESHNESS_REVISION_STATE",
                "COMPARABILITY_ELIGIBILITY",
                "KNOWN_SOURCE_LIMITATIONS",
            }:
                codes = component["reason_codes"]
                if isinstance(codes, list):
                    reasons.extend(str(code) for code in codes)
    ids = [str(item.get("canonical_observation_id")) for item in ordered]
    if len(ids) != len(set(ids)):
        # A repeated identical row has one scientific input, not extra coverage.
        unique = {json.dumps(item, sort_keys=True, default=str): item for item in ordered}
        ordered = sorted(
            unique.values(), key=lambda item: str(item.get("canonical_observation_id", ""))
        )
        profiles = [assess_surveillance_quality(item) for item in ordered]
        ids = [str(item.get("canonical_observation_id")) for item in ordered]
        if len(ids) != len(set(ids)):
            state, reasons = "UNKNOWN", ["CONFLICTING_CANONICAL_INPUT_ID"]
    first = ordered[0] if ordered else {}
    attestations = attest_scientific_fields(construct, first, source_context, dimension=dimension)
    by_field = {str(item["field"]): item for item in attestations}

    def canonical(field: str, fallback: object) -> object:
        item = by_field.get(field)
        return item["canonical_id"] if item is not None and proven(item) else fallback

    def display(field: str, fallback: object) -> object:
        item = by_field.get(field)
        return item["canonical_label"] if item is not None and proven(item) else fallback

    if state in {
        "REPORTED_STATUS",
        "PUBLISHER_NO_RECORDS",
        "NOT_REPORTED_IN_DATASET",
        "SAMPLED_EVENT",
        "DOCUMENTED_POSITIVE_EFFORT",
        "DOCUMENTED_POSITIVE_TEST_DENOMINATOR",
    } and not all(proven(item) for item in attestations):
        state, reasons = "UNKNOWN", ["SCIENTIFIC_ELIGIBILITY_UNPROVEN"]
    testing_attestation: dict[str, object] | None = None
    if construct == TESTING and state == "DOCUMENTED_POSITIVE_TEST_DENOMINATOR":
        source_testing_id = _part(first, "sampling_event", "source_testing_id")
        if _text(source_testing_id):
            testing_attestation = {
                "attestation_version": MODEL_VERSION,
                "source_dataset_id": source_context.get("source_dataset_id"),
                "source_version_id": source_context.get("source_version_id"),
                "testing_scope": "INDIVIDUAL_PATHOGEN_TEST",
                "source_testing_identity_sha256": hashlib.sha256(
                    f"{first.get('artifact_id')}:{source_testing_id}".encode()
                ).hexdigest(),
                "pathogen_target_id": attestations[0]["canonical_id"],
                "test_result_id": attestations[1]["canonical_id"],
                "normalization_rule_ids": [
                    attestations[0]["normalization_rule_id"],
                    attestations[1]["normalization_rule_id"],
                ],
                "eligibility": "ELIGIBLE",
            }
    identity = {
        "construct_id": construct,
        "methodology_version": METHODOLOGY_VERSION,
        "source_dataset_id": source_context.get("source_dataset_id"),
        "source_version_id": source_context.get("source_version_id"),
        "source_vintage": source_context.get("source_vintage"),
        "source_only_record_id": source_only_evidence.get("source_record_id")
        if source_only_evidence is not None
        else None,
        "source_only_geography": source_only_evidence.get("reported_geography")
        if source_only_evidence is not None
        else None,
        "temporal_semantics": first.get("temporal_semantics"),
        "scientific_ids": [item.get("canonical_id") for item in attestations],
        "county_fips": county_fips if construct == COUNTY else None,
        "dimension": canonical(
            "tick_taxon"
            if source_context.get("source_family") == "CDC_IXODES_COUNTY_STATUS"
            else "pathogen_target",
            dimension,
        )
        if construct == COUNTY
        else None,
        "sampling_site": first.get("sampling_site"),
        "sampling_event": first.get("sampling_event"),
        "period_start": first.get("surveillance_period_start"),
        "period_end": first.get("surveillance_period_end")
        or (source_context.get("cumulative_through_date") if construct == COUNTY else None),
        "taxon": canonical("tick_taxon", first.get("tick_species")),
        "life_stage": canonical("life_stage", first.get("life_stage")),
        "pathogen": canonical("pathogen_target", first.get("pathogen_name")),
        "test_result": canonical("test_result", first.get("test_result")),
        "method": canonical("collection_method", first.get("collection_method")),
        "effort_unit": canonical("effort_unit", first.get("collection_effort_unit")),
        "canonical_input_ids": ids,
        "source_record_ids": [item.get("source_record_id") for item in ordered],
        "source_revision_ids": [item.get("source_revision_id") for item in ordered],
        "snapshot_evidence_id": source_context.get("snapshot_evidence_id")
        if construct == COUNTY
        else None,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    result_identity = f"coverage:v2:{digest}"
    added_limitations = ["NOT_COUNTY_REPRESENTATIVE"] if construct != COUNTY else []
    propagation = (
        propagate_surveillance_quality(
            ordered,
            profiles,
            transformation_id=result_identity,
            transformation_version=CALCULATION_VERSION,
            added_reason_codes=reasons,
            added_limitations=added_limitations,
        )
        if ordered
        and len(ids) == len(set(ids))
        and all(_text(item.get("canonical_observation_id")) for item in ordered)
        else None
    )
    return {
        "coverage_identity": result_identity,
        "construct_id": construct,
        "methodology_version": METHODOLOGY_VERSION,
        "calculation_version": CALCULATION_VERSION,
        "state": state,
        "reason_codes": list(dict.fromkeys(reasons)),
        "native_grain": "COUNTY" if construct == COUNTY else "SITE_EVENT",
        "source_context": dict(source_context),
        "scientific_eligibility": attestations,
        "testing_scope_attestation": testing_attestation,
        "source_only_evidence": dict(source_only_evidence)
        if source_only_evidence is not None
        else None,
        "county_fips": county_fips if construct == COUNTY else None,
        "dimension": canonical(
            "tick_taxon"
            if source_context.get("source_family") == "CDC_IXODES_COUNTY_STATUS"
            else "pathogen_target",
            dimension,
        )
        if construct == COUNTY
        else None,
        "dimension_label": display(
            "tick_taxon"
            if source_context.get("source_family") == "CDC_IXODES_COUNTY_STATUS"
            else "pathogen_target",
            dimension,
        )
        if construct == COUNTY
        else None,
        "source_geography": first.get("source_geography"),
        "sampling_site": first.get("sampling_site"),
        "sampling_event": first.get("sampling_event"),
        "county_relationship": first.get("county_relationship"),
        "representativeness": "COUNTY_NATIVE_STATUS"
        if construct == COUNTY
        else "NOT_COUNTY_REPRESENTATIVE",
        "temporal_semantics": first.get("temporal_semantics")
        if first
        else ("CUMULATIVE_THROUGH_DATE" if construct == COUNTY else "POINT_IN_TIME"),
        "date": (
            first.get("surveillance_period_end") or source_context.get("cumulative_through_date")
        )
        if construct == COUNTY
        else first.get("surveillance_period_start"),
        "period_start": first.get("surveillance_period_start"),
        "period_end": first.get("surveillance_period_end")
        or (source_context.get("cumulative_through_date") if construct == COUNTY else None),
        "tick_species": display("tick_taxon", first.get("tick_species")),
        "publisher_status": first.get("presence_status") if construct == COUNTY else None,
        "life_stage": display("life_stage", first.get("life_stage")),
        "pathogen_name": display("pathogen_target", first.get("pathogen_name")),
        "collection_method": display("collection_method", first.get("collection_method")),
        "collection_effort_value": first.get("collection_effort_value"),
        "missingness": first.get("missingness"),
        "collection_effort_unit": display("effort_unit", first.get("collection_effort_unit")),
        "ticks_tested": first.get("ticks_tested"),
        "ticks_positive": first.get("ticks_positive"),
        "input_canonical_observation_ids": ids,
        "source_lineage": [
            {key: item.get(key) for key in _REQUIRED_LINEAGE}
            | {
                "source_revision_id": item.get("source_revision_id"),
                "normalization": item.get("normalization"),
            }
            for item in ordered
        ],
        "quality_propagation": propagation,
    }
