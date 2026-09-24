"""Unordered, source-native surveillance evidence triage for Story #172."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

from .surveillance_coverage import COUNTY, EFFORT, SAMPLING, TESTING
from .tick_normalization import load_registry

METHODOLOGY_VERSION = "surveillance-priority-v1"
DECISION = "SURVEILLANCE_EVIDENCE_REVIEW"
FOLLOW_UP = "EVIDENCE_GAP_FOLLOW_UP"
VERIFY = "EVIDENCE_VERIFICATION"
EXPLAIN = "EXPLANATORY_LIMITATION"
NO_GAP = "NO_CURRENT_GAP_SIGNAL"
UNAVAILABLE = "UNAVAILABLE"
NOT_DEFENSIBLE = "NOT_DEFENSIBLE"

# This is a state-to-action classification, not a severity or priority order.
DISPOSITIONS = {
    COUNTY: {
        "REPORTED_STATUS": NO_GAP,
        "PUBLISHER_NO_RECORDS": EXPLAIN,
        "NOT_REPORTED_IN_DATASET": FOLLOW_UP,
        "UNKNOWN": VERIFY,
        "UNAVAILABLE": UNAVAILABLE,
        "NOT_APPLICABLE": NOT_DEFENSIBLE,
    },
    SAMPLING: {
        "SAMPLED_EVENT": NO_GAP,
        "SAMPLING_IMPRACTICAL": EXPLAIN,
        "UNKNOWN": VERIFY,
        "UNAVAILABLE": UNAVAILABLE,
        "NOT_APPLICABLE": NOT_DEFENSIBLE,
    },
    EFFORT: {
        "DOCUMENTED_POSITIVE_EFFORT": NO_GAP,
        "MISSING_EFFORT": FOLLOW_UP,
        "ZERO_EFFORT": FOLLOW_UP,
        "SAMPLING_IMPRACTICAL": EXPLAIN,
        "UNKNOWN": VERIFY,
        "UNAVAILABLE": UNAVAILABLE,
    },
    TESTING: {
        "DOCUMENTED_POSITIVE_TEST_DENOMINATOR": NO_GAP,
        "MISSING_TEST_DENOMINATOR": FOLLOW_UP,
        "ZERO_TEST_DENOMINATOR": FOLLOW_UP,
        "UNKNOWN": VERIFY,
        "UNAVAILABLE": UNAVAILABLE,
        "NOT_APPLICABLE": NOT_DEFENSIBLE,
    },
}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


_UNRESOLVED_CONTEXT = frozenset(
    {
        "MISSING",
        "UNKNOWN",
        "UNRESOLVED",
        "AMBIGUOUS",
        "UNSUPPORTED",
        "NOT_REPORTED",
        "NOT_APPLICABLE",
        "MIXED",
        "AGGREGATE",
        "MULTIPLE",
        "COMBINED",
        "UNAVAILABLE",
        "NULL",
    }
)
_UNRESOLVED_PARTS = frozenset(
    {
        "MISSING",
        "UNKNOWN",
        "UNRESOLVED",
        "AMBIGUOUS",
        "UNSUPPORTED",
        "MIXED",
        "AGGREGATE",
        "MULTIPLE",
        "COMBINED",
        "UNAVAILABLE",
    }
)


def _resolved(value: object, *, dimension: str) -> bool:
    """Require one resolved value, using governed vocabulary for canonical strata."""
    if not _text(value):
        return False
    normalized = re.sub(r"[\s-]+", "_", str(value).strip().upper())
    parts = set(re.split(r"[_/+,;|]", normalized))
    if normalized in _UNRESOLVED_CONTEXT or parts & _UNRESOLVED_PARTS:
        return False
    labels = _cohort_registry_labels()
    registry_dimension = {
        "collection_method": 0,
        "tick_species": 1,
        "life_stage": 2,
        "pathogen_target": 3,
    }.get(dimension)
    return registry_dimension is None or value in labels[registry_dimension]


@lru_cache(maxsize=1)
def _cohort_registry_labels() -> tuple[frozenset[str], ...]:
    registry = load_registry()
    values = registry["canonical_values"]
    return tuple(
        frozenset(
            value
            for item in values[field]
            if not item.get("aggregate") and item.get("id") not in _UNRESOLVED_CONTEXT
            for value in (item["id"], item["label"])
        )
        for field in ("collection_method", "tick_taxon", "life_stage", "pathogen_target")
    )


def comparison_cohort(coverage: Mapping[str, Any]) -> dict[str, object] | None:
    """Return exact native comparison context, or None if it is unproven."""
    construct = coverage.get("construct_id")
    source = coverage.get("source_scope")
    if construct not in DISPOSITIONS or not isinstance(source, Mapping):
        return None
    cohort: dict[str, object] = {
        "construct_id": construct,
        "source_family": source.get("source_family") if construct == COUNTY else "NSF_NEON",
        "source_dataset_id": source.get("source_dataset_id"),
        "source_version_id": source.get("source_version_id"),
        "source_vintage": source.get("source_vintage"),
        "native_grain": coverage.get("native_grain"),
        "temporal_semantics": coverage.get("temporal_semantics"),
    }
    if construct == COUNTY:
        cohort.update(
            publisher_scope_version=source.get("publisher_scope_version"),
            canonical_universe_version=source.get("canonical_universe_version"),
            cumulative_through_date=source.get("cumulative_through_date"),
            dimension=coverage.get("dimension"),
            status_kind="VECTOR"
            if source.get("source_family") == "CDC_IXODES_COUNTY_STATUS"
            else "PATHOGEN",
        )
    else:
        cohort.update(
            observation_date=coverage.get("date"),
            collection_method=coverage.get("collection_method")
            if construct in {SAMPLING, EFFORT}
            else "NOT_APPLICABLE",
            tick_species=coverage.get("tick_species")
            if construct in {SAMPLING, EFFORT}
            else "NOT_APPLICABLE",
            life_stage=coverage.get("life_stage")
            if construct in {SAMPLING, EFFORT}
            else "NOT_APPLICABLE",
            effort_unit=coverage.get("collection_effort_unit") if construct == EFFORT else None,
            pathogen_target=coverage.get("pathogen_name")
            if construct == TESTING
            else "NOT_APPLICABLE",
            testing_scope=coverage.get("testing_scope", "INDIVIDUAL_PATHOGEN_TEST")
            if construct == TESTING
            else None,
        )
    required: tuple[str, ...] = (
        (
            "source_family",
            "source_dataset_id",
            "source_version_id",
            "source_vintage",
            "native_grain",
            "temporal_semantics",
            "publisher_scope_version",
            "canonical_universe_version",
            "cumulative_through_date",
            "dimension",
        )
        if construct == COUNTY
        else (
            "source_dataset_id",
            "source_version_id",
            "source_vintage",
            "native_grain",
            "temporal_semantics",
            "observation_date",
            "pathogen_target" if construct == TESTING else "collection_method",
        )
    )
    if construct == EFFORT:
        required += ("effort_unit",)
    if construct in {SAMPLING, EFFORT}:
        required += ("tick_species", "life_stage")
    if construct == TESTING:
        required += ("testing_scope",)
    if not all(_resolved(cohort.get(field), dimension=field) for field in required):
        return None
    if coverage.get("native_grain") != ("COUNTY" if construct == COUNTY else "SITE_EVENT"):
        return None
    if coverage.get("temporal_semantics") != (
        "CUMULATIVE_THROUGH_DATE" if construct == COUNTY else "POINT_IN_TIME"
    ):
        return None
    if construct == COUNTY and source.get("source_family") not in {
        "CDC_IXODES_COUNTY_STATUS",
        "CDC_PATHOGEN_COUNTY_STATUS",
    }:
        return None
    if construct == TESTING and cohort["testing_scope"] != "INDIVIDUAL_PATHOGEN_TEST":
        return None
    return cohort


def evaluate_surveillance_priority(coverage: Mapping[str, Any]) -> dict[str, object]:
    """Classify one serialized #171 result; never calculate a relative rank."""
    if coverage.get("contract_version") != "surveillance-coverage-result-v1":
        raise ValueError("approved #171 safe coverage result is required")
    if (
        coverage.get("methodology_version") != "surveillance-coverage-v1"
        or coverage.get("calculation_version") != "surveillance-coverage-calculation-v1"
        or not _text(coverage.get("result_id"))
        or not _text(coverage.get("result_revision"))
        or not _text(coverage.get("coverage_identity"))
    ):
        raise ValueError("coverage identity and versions are required")
    construct = coverage.get("construct_id")
    if construct not in DISPOSITIONS:
        raise ValueError("unapproved coverage construct")
    state = coverage.get("state")
    if state not in DISPOSITIONS[construct]:
        raise ValueError("unapproved coverage state")
    if coverage.get("evidence_basis") not in {
        "SYNTHETIC_FIXTURE",
        "CURRENT_CODE_SOURCE_BACKED_REPLAY",
    }:
        raise ValueError("coverage evidence basis is required")
    source = coverage.get("source_scope")
    if not isinstance(source, Mapping):
        raise ValueError("source scope is required")
    if (
        construct == COUNTY
        and state == "NOT_REPORTED_IN_DATASET"
        and (
            not _text(source.get("snapshot_evidence_id"))
            or source.get("snapshot_source_version_id") != source.get("source_version_id")
            or not _text(source.get("publisher_scope_version"))
            or not _text(source.get("canonical_universe_version"))
            or "COMPLETE_SCOPED_SNAPSHOT_OMISSION" not in coverage.get("reason_codes", [])
        )
    ):
        raise ValueError("county omission requires #171 complete scoped snapshot proof")
    cohort = comparison_cohort(coverage)
    disposition = DISPOSITIONS[construct][state]
    if cohort is None and disposition not in {UNAVAILABLE, VERIFY}:
        disposition = NOT_DEFENSIBLE
    cohort_id = f"priority-cohort:v1:{_digest(cohort)}" if cohort is not None else None
    reasons = [f"COVERAGE_STATE_{state}"]
    reasons.extend(str(item) for item in coverage.get("reason_codes", []))
    if cohort is None:
        reasons.append("COMPARISON_COHORT_UNPROVEN")
    result = {
        "methodology_version": METHODOLOGY_VERSION,
        "operational_decision": DECISION,
        "construct_id": construct,
        "coverage_result_id": coverage["result_id"],
        "coverage_result_revision": coverage["result_revision"],
        "coverage_identity": coverage["coverage_identity"],
        "coverage_state": state,
        "disposition": disposition,
        "comparison_cohort": cohort,
        "comparison_cohort_id": cohort_id,
        "tie_group_id": f"priority-tie:v1:{_digest([cohort_id, disposition])}"
        if cohort_id is not None and disposition not in {UNAVAILABLE, NOT_DEFENSIBLE}
        else None,
        "display_key": str(coverage["result_id"]),
        "reason_codes": list(dict.fromkeys(reasons)),
        "coverage": dict(coverage),
    }
    return result


def stable_display_order(results: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Sort for reproducible display only; refuse a mixed comparison cohort."""
    cohorts = {item.get("comparison_cohort_id") for item in results}
    if len(cohorts) > 1 or (len(results) > 1 and None in cohorts):
        raise ValueError("cross-cohort display requires separate labeled sections")
    return sorted(results, key=lambda item: str(item["display_key"]))
