"""Fixture-only DATA429 evidence envelope; no source classifier or publication.

Source-specific scientific rules have not been approved. This boundary exercises
the requested vocabulary without treating a caller's attestation as approval.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .semantic_domain import validate_observation
from .semantic_metadata import _safe

CONTRACT_VERSION = "atlas-surveillance-evidence-v1"
STATES = frozenset(
    {
        "established",
        "detected_below_establishment_criteria",
        "sampled_not_detected",
        "no_qualifying_record",
        "unknown",
    }
)
_LIMITATIONS = [
    "Evidence state is not biological absence, prevalence, density, or individual risk.",
    "Source grain and period remain authoritative; "
    "site/event evidence is not county representative.",
    "Synthetic contract fixture only; scientific review and source-specific rules remain pending.",
]


def evidence_fixture(
    observation: Mapping[str, Any],
    measure: Mapping[str, Any],
    *,
    assertion: Mapping[str, Any] | None = None,
    fixture_mode: bool = False,
) -> dict[str, Any]:
    """Bind a synthetic explicit assertion to one validated semantic revision.

    This does not infer states from a value and cannot run against real sources.
    Missing/incomplete assertions abstain. Conflicting scope fails closed.
    """
    if not fixture_mode:
        raise ValueError("DATA429 scientific review pending; production classification disabled")
    validate_observation(observation, measure)
    provenance = observation["provenance"]
    if observation["origin"] != "REPORTED" or not provenance["source_version_id"].startswith(
        "fixture-"
    ):
        raise ValueError("synthetic reported source identity required")
    if not observation.get("strata", {}).get("tick_taxon"):
        raise ValueError("explicit tick taxon required")
    state, reasons = "unknown", ["SOURCE_STATE_UNSUPPORTED"]
    proof = dict(assertion or {})
    if proof:
        for field in ("observation_key", "revision_id"):
            if proof.get(field) != observation[field]:
                raise ValueError("evidence assertion belongs to another observation or revision")
        candidate = proof.get("state")
        if candidate not in STATES:
            raise ValueError("unsupported evidence vocabulary")
        if candidate != "unknown" and all(
            isinstance(proof.get(field), str) and proof[field].strip()
            for field in ("source_definition_ref", "eligibility_rule_id", "criteria_ref")
        ):
            state, reasons = candidate, ["EXPLICIT_SYNTHETIC_SOURCE_ASSERTION"]
            if candidate == "sampled_not_detected" and not (
                proof.get("qualifying_sampling_proven") is True
                and proof.get("not_detected_proven") is True
                and isinstance(proof.get("sampling_evidence_ref"), str)
                and proof["sampling_evidence_ref"].strip()
            ):
                state, reasons = "unknown", ["QUALIFYING_SAMPLING_OR_RESULT_UNPROVEN"]
        if observation["geography"]["grain"] == "SOURCE_ONLY_COUNTY":
            state, reasons = "unknown", ["GEOGRAPHY_UNRESOLVED"]
    result = {
        "contract_version": CONTRACT_VERSION,
        "evidence_tier": "SYNTHETIC_FIXTURE",
        "state": state,
        "reason_codes": reasons,
        "observation_key": observation["observation_key"],
        "revision_id": observation["revision_id"],
        "scope": {
            field: copy.deepcopy(observation[field])
            for field in ("geography", "temporal", "strata")
        },
        "value_state": observation["value_state"],
        "source_version_id": provenance["source_version_id"],
        "source_vintage": provenance["source_vintage"],
        "source_record_id": provenance.get("source_record_id"),
        "source_row_hash": provenance.get("source_row_hash"),
        "quality_ref": observation.get("quality_ref"),
        "eligibility_ref": observation.get("eligibility_ref"),
        "limitations_ref": observation.get("limitations_ref"),
        "assertion": copy.deepcopy(proof),
        "limitations": list(_LIMITATIONS),
    }
    result["evidence_revision_id"] = (
        "evidence:v1:"
        + hashlib.sha256(
            json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return result


def project_evidence_fixture(
    observation: Mapping[str, Any],
    measure: Mapping[str, Any],
    *,
    assertion: Mapping[str, Any] | None = None,
    fixture_mode: bool = False,
) -> dict[str, Any]:
    """Allowlisted companion payload; existing consumer v1 remains unchanged.

    Revalidate the binding instead of projecting an arbitrary evidence dict.
    Private proof references, source record IDs and warehouse details stay inside.
    """
    result = evidence_fixture(observation, measure, assertion=assertion, fixture_mode=fixture_mode)
    geography = result["scope"]["geography"]
    payload = {
        field: copy.deepcopy(result[field])
        for field in (
            "contract_version",
            "evidence_tier",
            "state",
            "reason_codes",
            "observation_key",
            "revision_id",
            "evidence_revision_id",
            "value_state",
            "limitations",
        )
    }
    payload["scope"] = {
        "geography": {
            field: geography[field]
            for field in ("grain", "county_fips", "representativeness")
            if field in geography
        },
        "temporal": {
            field: result["scope"]["temporal"][field]
            for field in ("semantics", "start", "end", "date")
            if field in result["scope"]["temporal"]
        },
        "strata": copy.deepcopy(result["scope"]["strata"]),
    }
    _safe(payload)
    return payload
