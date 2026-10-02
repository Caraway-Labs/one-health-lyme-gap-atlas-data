"""Opt-in, fail-closed delivery failure evidence. Never inspect exception text."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from .ingestion.types import FailureCategory

REPOSITORY = "Caraway-Labs/one-health-lyme-gap-atlas-data"
MISSING_REASONS = [
    "NOT_COLLECTED",
    "UNAVAILABLE",
    "INCOMPLETE_LOGS",
    "ROLE_NOT_VISIBLE",
    "QUERY_ID_UNAVAILABLE",
    "REDACTION_REJECTED",
    "NOT_APPLICABLE",
]
FAILURE_CLASSES = [
    "SOFTWARE_DEFECT",
    "PERMISSION_CONFIGURATION",
    "GOVERNANCE_BLOCK",
    "UPSTREAM_OUTAGE",
    "INTENTIONAL_NEGATIVE_TEST",
    "UNKNOWN",
]
REFERENCE_PATTERN = (
    r"^https://github\.com/Caraway-Labs/one-health-lyme-gap-atlas-data/"
    r"(?:pull/[1-9][0-9]*|issues/[1-9][0-9]*|commit/[0-9a-f]{40}|"
    r"actions/runs/[1-9][0-9]*(?:/job/[1-9][0-9]*)?)$"
)


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": list(properties),
        "additionalProperties": False,
        "properties": properties,
    }


def _observed(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "oneOf": [
            _object({"state": {"const": "KNOWN"}, "value": value}),
            _object({"state": {"const": "UNKNOWN"}, "reason": {"enum": MISSING_REASONS}}),
        ]
    }


SHA = {"type": "string", "pattern": "^[0-9a-f]{40}$"}
DIGEST = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
REFERENCE = {"type": "string", "maxLength": 220, "pattern": REFERENCE_PATTERN}
PROOF = _object(
    {
        "state": {"enum": ["PASS", "FAIL", "UNKNOWN"]},
        "kind": {"enum": ["STATIC", "BEHAVIORAL", "UNKNOWN"]},
        "reference": _observed(REFERENCE),
    }
)
PROOF["allOf"] = [
    {
        "if": {"properties": {"state": {"enum": ["PASS", "FAIL"]}}},
        "then": {"properties": {"reference": {"properties": {"state": {"const": "KNOWN"}}}}},
    }
]
PROOF["allOf"].append(
    {
        "if": {"properties": {"state": {"const": "PASS"}}},
        "then": {"properties": {"kind": {"enum": ["STATIC", "BEHAVIORAL"]}}},
    }
)
FIELDS = {
    "schema_version": {"const": "1"},
    "repository": {"const": REPOSITORY},
    "recorded_at": {"type": "string", "format": "date-time", "maxLength": 35},
    "identity": _object(
        {
            "requested_sha": _observed(SHA),
            "workload_sha": _observed(SHA),
            "workflow_head_sha": _observed(SHA),
            "workflow_id": _observed({"type": "integer", "minimum": 1}),
            "run_id": _observed({"type": "integer", "minimum": 1}),
            "job_id": _observed({"type": "integer", "minimum": 1}),
            "attempt": _observed({"type": "integer", "minimum": 1}),
        }
    ),
    "environment": {"enum": ["LOCAL", "DEV", "PROD", "UNKNOWN"]},
    "effective_role": _observed(
        {
            "enum": [
                "OH_LYME_DEV_READ",
                "OH_LYME_DEV_OWNER",
                "OH_LYME_DEV_RUNTIME",
                "OH_LYME_DEV_MIGRATION_DEPLOYER",
                "OH_LYME_DEV_STREAMLIT_OWNER",
                "OH_LYME_PROD_READ",
                "OH_LYME_PROD_OWNER",
                "OH_LYME_PROD_RUNTIME",
                "OH_LYME_PROD_MIGRATION_DEPLOYER",
                "OH_LYME_PROD_STREAMLIT_OWNER",
            ]
        }
    ),
    "boundary": {
        "enum": [
            "CONNECTOR_WRITE",
            "PROCEDURE_BINDING",
            "CANONICAL_COVERAGE",
            "RELEASE_AUTHORITY",
            "ACQUIRE",
            "VALIDATE",
            "NORMALIZE",
            "LOAD",
            "QUALITY",
            "PUBLISH_STAGE",
            "MIGRATION",
            "DEPLOYMENT",
            "UNKNOWN",
        ]
    },
    "operation": {"enum": ["SOURCE_RUN", "MIGRATION", "SEMANTIC_RELEASE", "DEPLOYMENT", "UNKNOWN"]},
    "migration": _observed({"type": "string", "pattern": "^V[0-9]{3}$"}),
    "artifacts": _object(
        {
            name: _observed(DIGEST)
            for name in (
                "tested_artifact",
                "deployed_artifact",
                "semantic_bundle",
                "api_contract",
            )
        }
    ),
    "failure_class": {"enum": FAILURE_CLASSES},
    "operational_category": {"enum": [item.value for item in FailureCategory] + ["UNKNOWN"]},
    "diagnostic_code": {
        "enum": [
            "BATCH_WRITE_FAILED",
            "VARIANT_BIND_FAILED",
            "COVERAGE_CHECK_FAILED",
            "RELEASE_PRIVILEGE_FAILED",
            "OPERATION_FAILED",
            "UNKNOWN",
        ]
    },
    "query_ids": _observed(
        {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "uniqueItems": True,
            "items": {
                "type": "string",
                "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            },
        }
    ),
    "verified_facts": {"type": "array", "maxItems": 16, "items": REFERENCE},
    "unknowns": {
        "type": "array",
        "maxItems": 16,
        "uniqueItems": True,
        "items": {"enum": MISSING_REASONS},
    },
    "missing_check": {
        "enum": [
            "DRIVER_BATCH_EXECUTION",
            "DRIVER_VARIANT_EXECUTION",
            "CANONICAL_FIXTURE_EXECUTION",
            "INTENDED_ROLE_EXECUTION",
            "UNKNOWN",
        ]
    },
    "reproduction": _observed(REFERENCE),
    "regression": PROOF,
    "repair": PROOF,
    "risk": {"enum": ["PROSE_ONLY", "DB", "PERMISSIONS", "DEPLOYMENT", "CONTRACT", "UNKNOWN"]},
    "next_action": {
        "enum": [
            "INVESTIGATE_READ_ONLY",
            "RUN_LOCAL_REGRESSION",
            "REQUEST_BOUNDED_INTEGRATION_AUTHORIZATION",
            "REQUEST_MISSING_EVIDENCE",
            "INDEPENDENT_REVIEW",
        ]
    },
    "correlation_key": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
}
PACKET_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Atlas sanitized failure packet v1",
    **_object(FIELDS),
    "allOf": [
        {
            "if": {"properties": {"repair": {"properties": {"state": {"const": "PASS"}}}}},
            "then": {
                "properties": {
                    "repair": {"properties": {"kind": {"const": "BEHAVIORAL"}}},
                    "regression": {
                        "properties": {
                            "state": {"const": "PASS"},
                            "kind": {"const": "BEHAVIORAL"},
                        }
                    },
                }
            },
        }
    ],
}
VALIDATOR = Draft202012Validator(PACKET_SCHEMA, format_checker=Draft202012Validator.FORMAT_CHECKER)


def unknown(reason: str = "NOT_COLLECTED") -> dict[str, str]:
    """Explicit absence of evidence, never a confirmed absence of capability."""
    return {"state": "UNKNOWN", "reason": reason}


def validate_packet(packet: object) -> None:
    """Raise a constant diagnostic without echoing rejected input or schema paths."""
    if not VALIDATOR.is_valid(packet):
        raise ValueError("failure evidence rejected")
    assert isinstance(packet, dict)
    if packet["correlation_key"] != correlation_key(packet):
        raise ValueError("failure evidence rejected")


def correlation_key(packet: Mapping[str, Any]) -> str:
    """Correlate public failure identity; exclude attempts, time and private error text."""
    material = {
        name: packet[name]
        for name in (
            "repository",
            "environment",
            "boundary",
            "operation",
            "migration",
            "failure_class",
            "operational_category",
            "diagnostic_code",
        )
    }
    material["workload_sha"] = packet["identity"]["workload_sha"]
    digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    return "sha256:" + digest


def build_packet(context: Mapping[str, Any]) -> dict[str, Any]:
    """Build from reviewed metadata only; unknown keys reject rather than leak."""
    packet = copy.deepcopy(dict(context))
    packet["correlation_key"] = correlation_key(packet)
    validate_packet(packet)
    return packet


def collect_failure(
    context: Mapping[str, Any],
    sink: Callable[[dict[str, Any]], None],
) -> str:
    """Optional sink cannot replace an original exception or alter pipeline state.

    Call from an existing exception handler before its bare raise. Never pass an
    exception, logs, SQL, parameters, environment dump, or provider response.
    The sink is explicitly supplied; this utility performs no I/O or retries.
    """
    try:
        packet = build_packet(context)
    except Exception:
        return "REDACTION_REJECTED"
    try:
        sink(packet)
    except Exception:
        return "COLLECTION_UNAVAILABLE"
    return "COLLECTED"


def review_context(packet: dict[str, Any]) -> dict[str, Any]:
    """Fresh-context falsification checklist; never equate green static CI with repair."""
    validate_packet(packet)
    return {
        "correlation_key": packet["correlation_key"],
        "boundary": packet["boundary"],
        "unknowns": packet["unknowns"],
        "missing_check": packet["missing_check"],
        "next_action": packet["next_action"],
        "independent_behavioral_evidence_required": packet["risk"] != "PROSE_ONLY",
        "checks": [
            "Verify actual workload and artifact against workflow head independently.",
            "Falsify the boundary hypothesis with the required regression.",
            "Check intended role behavior; missing visibility remains UNKNOWN.",
            "Verify authorization before any integration execution or mutation.",
            "Verify regression and repair references; static PASS alone cannot prove repair.",
        ],
    }
