"""Consumer-safe, versioned projection for categorical surveillance coverage."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any

from .surveillance_coverage import (
    CALCULATION_VERSION,
    CONSTRUCTS,
    COUNTY,
    METHODOLOGY_VERSION,
)
from .surveillance_eligibility import approved_source_tuple
from .surveillance_quality_propagation import serialize_safe_propagation
from .surveillance_safe import has_sensitive_path

CONTRACT_VERSION = "surveillance-coverage-result-v2"
_SCIENTIFIC_KEYS = frozenset(
    {
        "coverage_identity",
        "construct_id",
        "methodology_version",
        "calculation_version",
        "state",
        "reason_codes",
        "native_grain",
        "source_scope",
        "county_fips",
        "dimension",
        "dimension_label",
        "site",
        "event",
        "source_geography",
        "county_relationship",
        "representativeness",
        "temporal_semantics",
        "date",
        "period_start",
        "period_end",
        "tick_species",
        "publisher_status",
        "life_stage",
        "pathogen_name",
        "collection_method",
        "collection_effort_value",
        "missingness",
        "collection_effort_unit",
        "ticks_tested",
        "ticks_positive",
        "input_canonical_observation_ids",
        "safe_lineage",
        "scientific_eligibility",
        "testing_scope_attestation",
        "source_only_evidence",
        "quality",
    }
)
_STATES = {
    CONSTRUCTS[0]: {
        "REPORTED_STATUS",
        "PUBLISHER_NO_RECORDS",
        "NOT_REPORTED_IN_DATASET",
        "UNKNOWN",
        "UNAVAILABLE",
        "NOT_APPLICABLE",
    },
    CONSTRUCTS[1]: {
        "SAMPLED_EVENT",
        "SAMPLING_IMPRACTICAL",
        "UNKNOWN",
        "UNAVAILABLE",
        "NOT_APPLICABLE",
    },
    CONSTRUCTS[2]: {
        "DOCUMENTED_POSITIVE_EFFORT",
        "MISSING_EFFORT",
        "ZERO_EFFORT",
        "SAMPLING_IMPRACTICAL",
        "UNKNOWN",
        "UNAVAILABLE",
    },
    CONSTRUCTS[3]: {
        "DOCUMENTED_POSITIVE_TEST_DENOMINATOR",
        "MISSING_TEST_DENOMINATOR",
        "ZERO_TEST_DENOMINATOR",
        "UNKNOWN",
        "UNAVAILABLE",
        "NOT_APPLICABLE",
    },
}
_UNSAFE = re.compile(
    r"(?:[a-z][a-z0-9+.-]*://|[?&](?:token|signature|credential|password|secret)=|"
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----)",
    re.IGNORECASE,
)


def _select(value: object, fields: tuple[str, ...]) -> dict[str, object]:
    source = value if isinstance(value, Mapping) else {}
    return {field: source.get(field) for field in fields}


def _safe(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or _UNSAFE.search(key):
                raise ValueError("unsafe coverage output key")
            _safe(item)
    elif isinstance(value, list):
        for item in value:
            _safe(item)
    elif isinstance(value, str) and (_UNSAFE.search(value) or has_sensitive_path(value)):
        raise ValueError("unsafe coverage output value")


def _safe_lineage(item: object) -> dict[str, object]:
    source = item if isinstance(item, Mapping) else {}
    safe = _select(
        source,
        (
            "canonical_observation_id",
            "source_dataset_id",
            "data_source_version_id",
            "source_record_id",
            "source_revision_id",
            "ingestion_run_id",
            "retrieved_at",
            "method_version",
        ),
    )
    normalization = source.get("normalization")
    normalization = normalization if isinstance(normalization, Mapping) else {}
    mappings = normalization.get("mappings")
    mappings = mappings if isinstance(mappings, Mapping) else {}
    safe["normalization_registry_id"] = normalization.get("registry_id")
    safe["normalization_registry_version"] = normalization.get("registry_version")
    safe["normalization_rule_ids"] = sorted(
        mapping["mapping_rule_id"]
        for mapping in mappings.values()
        if isinstance(mapping, Mapping) and isinstance(mapping.get("mapping_rule_id"), str)
    )
    return safe


def serialize_surveillance_coverage(
    result: Mapping[str, Any], *, evidence_basis: str
) -> dict[str, object]:
    """Allowlist one categorical profile, excluding private artifact lineage."""
    if evidence_basis not in {"SYNTHETIC_FIXTURE", "CURRENT_CODE_SOURCE_BACKED_REPLAY"}:
        raise ValueError("unsupported evidence basis")
    construct = result.get("construct_id")
    if construct not in _STATES or result.get("state") not in _STATES[construct]:
        raise ValueError("unapproved construct or state")
    if (
        result.get("methodology_version") != METHODOLOGY_VERSION
        or result.get("calculation_version") != CALCULATION_VERSION
    ):
        raise ValueError("unapproved methodology or calculation version")
    if not isinstance(result.get("coverage_identity"), str) or not result[
        "coverage_identity"
    ].startswith("coverage:v2:"):
        raise ValueError("coverage identity is required")
    if result.get("native_grain") != ("COUNTY" if construct == COUNTY else "SITE_EVENT"):
        raise ValueError("native grain conflicts with construct")
    if result.get("representativeness") != (
        "COUNTY_NATIVE_STATUS" if construct == COUNTY else "NOT_COUNTY_REPRESENTATIVE"
    ):
        raise ValueError("representativeness conflicts with construct")
    allowed_time = (
        {"CUMULATIVE_THROUGH_DATE"} if construct == COUNTY else {"POINT_IN_TIME", "PERIOD"}
    )
    if result.get("temporal_semantics") not in allowed_time:
        raise ValueError("time semantics conflict with construct")
    context = result.get("source_context")
    if not isinstance(context, Mapping):
        raise ValueError("source context is required")
    state = result["state"]
    positive = state in {
        "REPORTED_STATUS",
        "PUBLISHER_NO_RECORDS",
        "NOT_REPORTED_IN_DATASET",
        "SAMPLED_EVENT",
        "DOCUMENTED_POSITIVE_EFFORT",
        "DOCUMENTED_POSITIVE_TEST_DENOMINATOR",
    }
    if positive and construct != COUNTY and result.get("temporal_semantics") != "POINT_IN_TIME":
        raise ValueError("positive active state requires point-in-time evidence")
    if positive and (context.get("approved") is not True or context.get("available") is not True):
        raise ValueError("positive coverage state requires approved available source")
    if positive and not approved_source_tuple(str(construct), context):
        raise ValueError("positive coverage state requires approved source vintage tuple")
    eligibility = result.get("scientific_eligibility")
    if not isinstance(eligibility, list) or not eligibility:
        raise ValueError("scientific eligibility evidence is required")
    if positive and any(
        not isinstance(item, Mapping) or item.get("eligibility") != "ELIGIBLE"
        for item in eligibility
    ):
        raise ValueError("positive coverage state requires proven scientific eligibility")
    testing_scope_attestation = result.get("testing_scope_attestation")
    if state == "DOCUMENTED_POSITIVE_TEST_DENOMINATOR" and (
        not isinstance(testing_scope_attestation, Mapping)
        or testing_scope_attestation.get("eligibility") != "ELIGIBLE"
        or testing_scope_attestation.get("testing_scope") != "INDIVIDUAL_PATHOGEN_TEST"
    ):
        raise ValueError("positive testing state requires proven individual scope")
    if (
        construct == COUNTY
        and positive
        and (
            context.get("snapshot_complete") is not True
            or context.get("scope_approved") is not True
            or not context.get("snapshot_evidence_id")
            or context.get("snapshot_source_version_id") != context.get("source_version_id")
        )
    ):
        raise ValueError("county representation requires complete scoped snapshot evidence")
    if state == "REPORTED_STATUS" and result.get("publisher_status") not in {
        "ESTABLISHED",
        "REPORTED",
        "PRESENT",
    }:
        raise ValueError("reported status requires source status")
    if state == "PUBLISHER_NO_RECORDS" and result.get("publisher_status") != "NO_RECORDS":
        raise ValueError("publisher no-records requires explicit source status")
    ids = result.get("input_canonical_observation_ids")
    lineage = result.get("source_lineage")
    if not isinstance(ids, list) or not isinstance(lineage, list) or len(ids) != len(lineage):
        raise ValueError("canonical IDs and lineage must align")
    safe_lineage = [_safe_lineage(item) for item in lineage]
    if [item["canonical_observation_id"] for item in safe_lineage] != ids:
        raise ValueError("lineage does not match exact canonical inputs")
    if (
        state
        in {
            "REPORTED_STATUS",
            "PUBLISHER_NO_RECORDS",
            "SAMPLED_EVENT",
            "DOCUMENTED_POSITIVE_EFFORT",
            "DOCUMENTED_POSITIVE_TEST_DENOMINATOR",
        }
        and not ids
    ):
        raise ValueError("positive observed state requires canonical input")
    if state == "NOT_REPORTED_IN_DATASET" and (
        ids
        or context.get("snapshot_complete") is not True
        or context.get("scope_approved") is not True
        or not context.get("snapshot_evidence_id")
        or context.get("snapshot_source_version_id") != context.get("source_version_id")
    ):
        raise ValueError("county omission requires complete scoped snapshot evidence")
    if state in {"SAMPLED_EVENT", "DOCUMENTED_POSITIVE_EFFORT"}:
        effort = result.get("collection_effort_value")
        if (
            isinstance(effort, bool)
            or not isinstance(effort, (int, float))
            or not math.isfinite(effort)
            or effort <= 0
            or result.get("collection_effort_unit") != "square metre"
            or not result.get("collection_method")
        ):
            raise ValueError("positive active state requires documented method and effort")
    if state == "DOCUMENTED_POSITIVE_TEST_DENOMINATOR":
        tested, detected = result.get("ticks_tested"), result.get("ticks_positive")
        if (
            isinstance(tested, bool)
            or not isinstance(tested, int)
            or tested <= 0
            or isinstance(detected, bool)
            or not isinstance(detected, int)
            or not 0 <= detected <= tested
        ):
            raise ValueError("positive testing state requires valid individual denominator")
    quality = result.get("quality_propagation")
    safe_quality = serialize_safe_propagation(quality) if isinstance(quality, Mapping) else None
    if positive and state != "NOT_REPORTED_IN_DATASET" and safe_quality is None:
        raise ValueError("positive observed state requires quality propagation")
    if (
        safe_quality is not None
        and safe_quality["transformation_id"] != result["coverage_identity"]
    ):
        raise ValueError("quality propagation belongs to another result")
    county = _select(
        result.get("county_relationship"),
        (
            "mapping_status",
            "county_fips",
            "mapping_method",
            "mapping_version",
        ),
    )
    if construct != COUNTY:
        if (
            county["mapping_status"] in {"UNMAPPED", "AMBIGUOUS"}
            and county["county_fips"] is not None
        ):
            raise ValueError("unmapped or ambiguous site has county FIPS")
        county["representativeness"] = "NOT_COUNTY_REPRESENTATIVE"
    else:
        county = {}
    scientific: dict[str, object] = {
        "coverage_identity": result["coverage_identity"],
        "construct_id": construct,
        "methodology_version": METHODOLOGY_VERSION,
        "calculation_version": CALCULATION_VERSION,
        "state": result["state"],
        "reason_codes": result.get("reason_codes", []),
        "native_grain": result["native_grain"],
        "source_scope": _select(
            context,
            (
                "source_family",
                "publisher",
                "source_dataset_id",
                "source_version_id",
                "source_vintage",
                "snapshot_evidence_id",
                "snapshot_source_version_id",
                "publisher_scope_version",
                "canonical_universe_version",
                "cumulative_through_date",
            ),
        ),
        "county_fips": result.get("county_fips") if construct == COUNTY else None,
        "dimension": result.get("dimension") if construct == COUNTY else None,
        "dimension_label": result.get("dimension_label") if construct == COUNTY else None,
        "site": _select(
            result.get("sampling_site"),
            (
                "source_site_id",
                "source_plot_id",
                "source_location_id",
            ),
        ),
        "event": _select(
            result.get("sampling_event"),
            (
                "source_event_id",
                "source_sample_id",
                "source_subsample_id",
                "source_replicate_id",
                "source_batch_id",
            ),
        ),
        "source_geography": _select(
            result.get("source_geography"),
            (
                "source_location_id",
                "geography_kind",
                "coordinate_reference_system",
                "longitude",
                "latitude",
                "spatial_uncertainty_meters",
            ),
        ),
        "county_relationship": county,
        "representativeness": result["representativeness"],
        "temporal_semantics": result["temporal_semantics"],
        "date": result.get("date"),
        "period_start": result.get("period_start"),
        "period_end": result.get("period_end"),
        "tick_species": result.get("tick_species"),
        "publisher_status": result.get("publisher_status"),
        "life_stage": result.get("life_stage"),
        "pathogen_name": result.get("pathogen_name"),
        "collection_method": result.get("collection_method"),
        "collection_effort_value": result.get("collection_effort_value"),
        "missingness": _select(result.get("missingness"), ("collection_effort_value",)),
        "collection_effort_unit": result.get("collection_effort_unit"),
        "ticks_tested": result.get("ticks_tested"),
        "ticks_positive": result.get("ticks_positive"),
        "input_canonical_observation_ids": ids,
        "safe_lineage": safe_lineage,
        "scientific_eligibility": eligibility,
        "testing_scope_attestation": testing_scope_attestation,
        "quality": safe_quality,
    }
    source_only = result.get("source_only_evidence")
    if source_only is not None:
        if construct != COUNTY or state != "UNKNOWN" or result.get("county_fips") is not None:
            raise ValueError("source-only evidence cannot establish canonical county coverage")
        if not isinstance(source_only, Mapping) or "county_fips" in source_only:
            raise ValueError("source-only evidence cannot contain county FIPS")
        safe_source_only = _select(
            source_only,
            (
                "source_record_id",
                "source_revision_id",
                "ingestion_run_id",
                "reported_geography",
                "source_geography_type",
                "mapping_status",
                "mapping_reason",
                "normalization_registry_id",
                "normalization_registry_version",
                "normalization_rule_id",
                "scientific_dimension",
                "retrieved_at",
            ),
        )
        if safe_source_only["mapping_status"] not in {"UNMAPPED", "AMBIGUOUS"}:
            raise ValueError("source-only county evidence must be unresolved")
        scientific["source_only_evidence"] = {
            "contract_version": "surveillance-source-only-county-evidence-v1",
            "linked_coverage_identity": result["coverage_identity"],
            "source_dataset_id": context.get("source_dataset_id"),
            "publisher": context.get("publisher"),
            "source_version_id": context.get("source_version_id"),
            "source_vintage": context.get("source_vintage"),
            "evidence_basis": evidence_basis,
            **safe_source_only,
            "representativeness": "NOT_COUNTY_REPRESENTATIVE",
        }
    _safe(scientific)
    revision = hashlib.sha256(
        json.dumps(
            {"scientific": scientific, "evidence_basis": evidence_basis},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    document = {
        "contract_version": CONTRACT_VERSION,
        "result_id": f"coverage-result:v2:{revision}",
        "result_revision": revision,
        **scientific,
        "evidence_basis": evidence_basis,
        "publication_status": "INTERNAL_DEV_ONLY",
    }
    _safe(document)
    return document


def safe_coverage_revision_valid(document: Mapping[str, Any]) -> bool:
    """Verify that a safe result's immutable ID binds its evidence basis."""
    if document.get("contract_version") != CONTRACT_VERSION:
        return False
    scientific = {key: value for key, value in document.items() if key in _SCIENTIFIC_KEYS}
    try:
        digest = hashlib.sha256(
            json.dumps(
                {"scientific": scientific, "evidence_basis": document.get("evidence_basis")},
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
    except (TypeError, ValueError):
        return False
    return (
        document.get("result_revision") == digest
        and document.get("result_id") == f"coverage-result:v2:{digest}"
    )
