"""DATA429 source-supported interpretation over existing governed mappings.

No ingestion or release hook is installed. Existing metadata/lineage/publication
gates remain authoritative. The v1 synthetic scaffold is retained unchanged.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .semantic_consumer import project_consumer
from .semantic_lineage import lineage_id
from .semantic_metadata import _safe
from .semantic_source_mappings import map_record
from .surveillance_evidence import STATES as FIXTURE_STATES
from .tick_normalization import normalize_value

CONTRACT_VERSION = "atlas-surveillance-evidence-v3"
_REPORTED_ARTIFACT_SHA256 = "e35a5066a7c77b2e79c50f315a18e042405ab7baa8a414a1a907792bb25d2adc"
STATES = (FIXTURE_STATES - {"detected_below_establishment_criteria"}) | {
    "detected_below_establishment"
}
_LIMITATIONS = [
    "No qualifying record is not biological absence.",
    "Site/event evidence is not county representative.",
    "Detection alone does not establish prevalence or establishment criteria.",
    "No freshness, pooling, public admission or scientific approval is inferred.",
]


def _classify(record: Mapping[str, Any], mapping: Mapping[str, Any]) -> tuple[str, str]:
    output = record["source_output"]
    raw = output.get(mapping["field"])
    identity = mapping["id"]
    if identity in {"county_tick_status", "county_pathogen_status"}:
        resource = (
            "cdc_tick_ixodes_county_status"
            if identity == "county_tick_status"
            else "cdc_tick_ixodes_pathogen_status"
        )
        if (
            mapping.get("resource_key") != resource
            or mapping.get("vintage") != "2025"
            or mapping.get("definition_version") != 1
            or mapping.get("grain") != "COUNTY"
            or mapping.get("time") != "CUMULATIVE_THROUGH_DATE"
            or record["temporal"].get("date") != "2025-12-31"
            or mapping.get("field")
            != ("scapularis_status" if identity == "county_tick_status" else "burgdorferi_status")
        ):
            return "unknown", "SOURCE_RULE_UNSUPPORTED"
        if raw == "No records":
            return "no_qualifying_record", "PUBLISHER_NO_RECORDS"
        if identity == "county_tick_status" and raw == "Established":
            return "established", "PUBLISHER_ESTABLISHED"
        if identity == "county_tick_status" and raw == "Reported":
            if not record.get("edges") or not all(
                edge.get("source_id") == "cdc_arbonet_tick_module"
                and edge.get("dataset_id") == "cdc-ixodes-county-status-2025"
                and edge.get("artifact_sha256") == _REPORTED_ARTIFACT_SHA256
                for edge in record["edges"]
            ):
                return "unknown", "REPORTED_SOURCE_PROOF_UNSUPPORTED"
            return "detected_below_establishment", "PUBLISHER_REPORTED_ESTABLISHMENT_NOT_DOCUMENTED"
        if raw in ("Reported", "Present"):
            return "unknown", "DETECTION_ESTABLISHMENT_RELATION_UNPROVEN"
        return "unknown", "SOURCE_STATE_UNSUPPORTED"
    if identity == "neon_pathogen_test":
        if (
            mapping.get("resource_key") != "neon_tick_release_2026"
            or mapping.get("product") != "DP1.10092.001"
            or mapping.get("vintage") != "RELEASE-2026"
            or mapping.get("definition_version") != 1
            or mapping.get("grain") != "SITE_EVENT"
            or mapping.get("field") != "ticks_positive"
            or record["geography"].get("site_id") != "BLAN"
            or not str(record["temporal"].get("date", "")).startswith("2016-05-")
        ):
            return "unknown", "SOURCE_RULE_UNSUPPORTED"
        event = output.get("sampling_event", {})
        if (
            output.get("ticks_tested") != 1
            or type(output.get("ticks_tested")) is not int
            or raw != 0
            or type(raw) is not int
            or not event.get("source_testing_id")
            or not event.get("source_sample_id")
            or output.get("quality_flags") != []
        ):
            return "unknown", "QUALIFYING_TEST_UNPROVEN"
        proofs = output.get("normalization", {}).get("mappings", {})
        # Legacy records may omit these optional fields; explicit evidence must
        # agree with the individual negative test rather than be ignored.
        if (
            "testing_scope" in output and output["testing_scope"] != "INDIVIDUAL_PATHOGEN_TEST"
        ) or ("test_result" in output and output["test_result"] != "NOT_DETECTED"):
            return "unknown", "CONTRADICTORY_OR_UNPROVEN_TEST_EVIDENCE"
        candidates = []
        for proof in proofs.values():
            if not isinstance(proof, Mapping):
                continue
            source_value = proof.get("source_value")
            if not isinstance(source_value, str | int | float | bool):
                continue
            expected = normalize_value(
                field="test_result",
                source_value=source_value,
                publisher="NSF NEON",
                dataset_id="DP1.10092.001",
                source_version="RELEASE-2026",
            )
            if proof.get("canonical_id") == "DETECTED" or expected.canonical_id == "DETECTED":
                return "unknown", "CONTRADICTORY_OR_UNPROVEN_TEST_EVIDENCE"
            if expected.canonical_id == "NOT_DETECTED" and proof == expected.as_contract_value():
                candidates.append(proof)
        if len(candidates) == 1:
            return "sampled_not_detected", "SOURCE_NORMALIZED_INDIVIDUAL_NEGATIVE_TEST"
        return "unknown", "NEGATIVE_TEST_NORMALIZATION_UNPROVEN"
    return "unknown", "SOURCE_RULE_UNSUPPORTED"


def map_surveillance_evidence(
    record: Mapping[str, Any],
    metadata: Mapping[str, Any],
    authority: Mapping[str, Any],
    mappings: Mapping[str, Mapping[str, Any]],
    *,
    fixture_mode: bool = False,
) -> dict[str, Any]:
    """Reuse canonical→semantic validation before applying exact source rules.

    Missing records cannot enter this boundary. No caller assertion or approval
    boolean can select an evidence state. Quality and source values are untouched.
    """
    if type(fixture_mode) is not bool:
        raise ValueError("fixture_mode requires a literal boolean")
    if fixture_mode and not all(
        str(edge.get("source_version_id", "")).startswith("fixture-")
        for edge in record.get("edges", [])
    ):
        raise ValueError("fixture mode requires synthetic source versions")
    mapped = map_record(record, metadata, authority, mappings, fixture_mode=fixture_mode)
    mapping = mappings[record["mapping_id"]]
    state, reason = _classify(record, mapping)
    observation = mapped["observation"]
    evidence = {
        "contract_version": CONTRACT_VERSION,
        "state": state,
        "reason_codes": [reason],
        "evidence_tier": "SYNTHETIC_FIXTURE" if fixture_mode else "GOVERNED_MAPPING",
        "observation_key": observation["observation_key"],
        "revision_id": observation["revision_id"],
        "lineage_id": mapped["lineage_id"],
        "value_state": observation["value_state"],
        "source_rule_id": f"{record['mapping_id']}:evidence-v3",
        "limitations": list(_LIMITATIONS),
    }
    if state == "detected_below_establishment":
        evidence["limitations"].extend(
            [
                "Detected; establishment criteria not documented as met in the source.",
                "Publisher cumulative Reported label for Ixodes scapularis through 2025-12-31; "
                "not a 2025 collection event.",
                "No tick count, life stage, collection date, effort, current ecological "
                "non-establishment or sampling completeness is inferred.",
            ]
        )
    # Bind all canonical evidence (including private method/test/quality proof)
    # through a digest rather than copying private payload fields to consumers.
    evidence["canonical_evidence_sha256"] = hashlib.sha256(
        json.dumps(record["source_output"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    evidence["evidence_revision_id"] = (
        "evidence:v3:"
        + hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return {**mapped, "surveillance_evidence": evidence}


def project_surveillance_evidence(
    record: Mapping[str, Any],
    metadata: Mapping[str, Any],
    authority: Mapping[str, Any],
    mappings: Mapping[str, Mapping[str, Any]],
    *,
    fixture_mode: bool = False,
) -> dict[str, Any]:
    """Companion projection through existing consumer gates; no public hook.

    Fixture mode can exercise consumer-safe metadata with a synthetic trace.
    Real mappings retain their internal visibility and cannot bypass admission.
    """
    mapped = map_surveillance_evidence(
        record, metadata, authority, mappings, fixture_mode=fixture_mode
    )
    lineage = copy.deepcopy(mapped["lineage"])
    if fixture_mode and metadata["visibility"] == "CONSUMER_SAFE":
        lineage["visibility"] = "CONSUMER_SAFE"
        lineage["lineage_id"] = lineage_id(lineage)
    semantic = project_consumer(lineage, authority, fixture_mode=fixture_mode)
    evidence = mapped["surveillance_evidence"]
    payload = {
        "contract_version": "atlas-surveillance-evidence-consumer-v2",
        "semantic": semantic,
        "surveillance_evidence": {
            key: evidence[key]
            for key in (
                "contract_version",
                "state",
                "reason_codes",
                "evidence_tier",
                "observation_key",
                "revision_id",
                "value_state",
                "source_rule_id",
                "limitations",
                "evidence_revision_id",
            )
        },
    }
    _safe(payload)
    return payload
