"""Consumer-safe internal serialization of unordered #172 triage results."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from .surveillance_priority import (
    DECISION,
    DISPOSITIONS,
    METHODOLOGY_VERSION,
    NOT_DEFENSIBLE,
    UNAVAILABLE,
    evaluate_surveillance_priority,
)

CONTRACT_VERSION = "surveillance-priority-result-v1"
_UNSAFE = re.compile(
    r"(?:[a-z][a-z0-9+.-]*://|[?&](?:token|signature|credential|password|secret)=|"
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----)",
    re.IGNORECASE,
)
_UNSAFE_KEY = re.compile(
    r"(?:artifact|raw|secret|token|credential|password|private.key|signed)", re.IGNORECASE
)


def _safe(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or _UNSAFE.search(key) or _UNSAFE_KEY.search(key):
                raise ValueError("unsafe priority output key")
            _safe(item)
    elif isinstance(value, list):
        for item in value:
            _safe(item)
    elif isinstance(value, str) and _UNSAFE.search(value):
        raise ValueError("unsafe priority output value")


def serialize_surveillance_priority(result: Mapping[str, Any]) -> dict[str, object]:
    """Allowlist a priority result; preserve #171 quality and safe lineage."""
    coverage = result.get("coverage")
    if not isinstance(coverage, Mapping):
        raise ValueError("underlying safe coverage result is required")
    expected = evaluate_surveillance_priority(coverage)
    for field in (
        "disposition",
        "comparison_cohort",
        "comparison_cohort_id",
        "tie_group_id",
        "reason_codes",
    ):
        if result.get(field) != expected[field]:
            raise ValueError("triage decision does not match approved methodology")
    construct = result.get("construct_id")
    if construct not in DISPOSITIONS or result.get("coverage_state") not in DISPOSITIONS[construct]:
        raise ValueError("unapproved construct or state")
    if (
        result.get("methodology_version") != METHODOLOGY_VERSION
        or result.get("operational_decision") != DECISION
        or result.get("coverage_result_id") != coverage.get("result_id")
        or result.get("coverage_result_revision") != coverage.get("result_revision")
        or result.get("coverage_identity") != coverage.get("coverage_identity")
        or result.get("coverage_state") != coverage.get("state")
        or result.get("construct_id") != coverage.get("construct_id")
    ):
        raise ValueError("triage result does not match coverage evidence")
    if (
        result.get("disposition") in {UNAVAILABLE, NOT_DEFENSIBLE}
        and result.get("tie_group_id") is not None
    ):
        raise ValueError("unavailable or incomparable evidence cannot have a tie group")
    if result.get("display_key") != coverage.get("result_id"):
        raise ValueError("display key must be stable coverage identity")
    document: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "operational_decision": DECISION,
        "construct_id": construct,
        "coverage_result_id": result["coverage_result_id"],
        "coverage_result_revision": result["coverage_result_revision"],
        "coverage_identity": result["coverage_identity"],
        "coverage_state": result["coverage_state"],
        "disposition": result["disposition"],
        "comparison_cohort": result.get("comparison_cohort"),
        "comparison_cohort_id": result.get("comparison_cohort_id"),
        "tie_group_id": result.get("tie_group_id"),
        "display_key": result["display_key"],
        "reason_codes": result.get("reason_codes", []),
        "source_scope": coverage.get("source_scope"),
        "native_grain": coverage.get("native_grain"),
        "temporal_semantics": coverage.get("temporal_semantics"),
        "date": coverage.get("date"),
        "county_fips": coverage.get("county_fips"),
        "site": coverage.get("site"),
        "event": coverage.get("event"),
        "county_relationship": coverage.get("county_relationship"),
        "representativeness": coverage.get("representativeness"),
        "safe_lineage": coverage.get("safe_lineage"),
        "quality": coverage.get("quality"),
        "evidence_basis": coverage.get("evidence_basis"),
        "interpretation": (
            "This evidence unit warrants the stated kind of surveillance-data review or "
            "follow-up under surveillance-priority-v1. It is not disease risk, biological "
            "absence, proven underreporting, agency performance, or a resource-allocation order."
        ),
        "publication_status": "INTERNAL_DEV_ONLY",
    }
    _safe(document)
    revision = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    document["result_revision"] = revision
    document["result_id"] = f"surveillance-priority-result:v1:{revision}"
    return document
