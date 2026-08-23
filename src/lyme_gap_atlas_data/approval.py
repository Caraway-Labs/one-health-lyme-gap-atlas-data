"""Validation shared by the Snowflake approval console and unit tests."""

from __future__ import annotations

from typing import Final

DECISIONS: Final = frozenset(
    {"APPROVED", "APPROVED_WITH_CONDITIONS", "REJECTED", "RETIRED", "DEFERRED"}
)
CONDITIONS_REQUIRED: Final = frozenset(
    {"APPROVED_WITH_CONDITIONS", "REJECTED", "RETIRED", "DEFERRED"}
)


def validate_decision(decision: str, rationale: str, conditions: list[str]) -> None:
    """Reject incomplete review input before it reaches the controlled procedure."""
    if decision not in DECISIONS:
        raise ValueError("Choose a supported decision")
    if not 10 <= len(rationale.strip()) <= 10_000:
        raise ValueError("Provide a rationale between 10 and 10,000 characters")
    if decision in CONDITIONS_REQUIRED and not any(item.strip() for item in conditions):
        raise ValueError("Provide at least one condition, action, or deferral reason")


def approval_prerequisites_met(detail: dict[str, object]) -> bool:
    """Mirror the summary prerequisites; the procedure remains authoritative."""
    document_count = detail.get("document_snapshot_count")
    schema_count = detail.get("schema_snapshot_count")
    return (
        isinstance(document_count, int)
        and document_count > 0
        and isinstance(schema_count, int)
        and schema_count > 0
        and detail.get("profile_version") is not None
        and detail.get("assessment_status") == "PENDING_REVIEW"
        and not bool(detail.get("has_material_schema_change", False))
        and not bool(detail.get("has_material_document_change", False))
        and not bool(detail.get("has_blocking_issue", False))
    )
