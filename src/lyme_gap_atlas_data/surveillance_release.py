"""Immutable coverage/triage snapshot candidates; no publication side effects."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .surveillance_coverage_results import serialize_surveillance_coverage
from .surveillance_priority import evaluate_surveillance_priority
from .surveillance_priority_results import serialize_surveillance_priority

CONTRACT_VERSION = "surveillance-release-candidate-v1"
_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")


def build_surveillance_release_candidate(
    results: Sequence[Mapping[str, Any]],
    *,
    release_id: str,
    scope_reference: str,
    expected_result_ids: Sequence[str],
    evidence_basis: str,
) -> dict[str, object]:
    """Bind an exact scoped membership without upgrading its evidence basis.

    Inputs are calculator envelopes, not caller-supplied safe projections or
    triage decisions. Scope completeness refers only to the explicit manifest;
    publisher omission still requires the existing independent source proof.
    """
    for reference in (release_id, scope_reference):
        if not isinstance(reference, str) or not _REFERENCE.fullmatch(reference):
            raise ValueError("safe release and scope references are required")
    expected = list(expected_result_ids)
    if (
        not expected
        or any(not isinstance(item, str) or not item for item in expected)
        or len(set(expected)) != len(expected)
    ):
        raise ValueError("nonempty unique expected result membership is required")
    coverage = [
        serialize_surveillance_coverage(result, evidence_basis=evidence_basis) for result in results
    ]
    ids = [str(result["result_id"]) for result in coverage]
    if len(set(ids)) != len(ids) or set(ids) != set(expected):
        raise ValueError("incomplete, duplicate or unexpected snapshot membership")
    coverage.sort(key=lambda result: str(result["result_id"]))
    priority = [
        serialize_surveillance_priority(evaluate_surveillance_priority(result))
        for result in coverage
    ]
    payload: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "release_id": release_id,
        "scope_reference": scope_reference,
        "expected_result_ids": sorted(expected),
        "evidence_basis": evidence_basis,
        "publication_status": "CANDIDATE_NOT_PUBLISHED",
        "coverage": coverage,
        "priority": priority,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    payload["snapshot_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return payload
