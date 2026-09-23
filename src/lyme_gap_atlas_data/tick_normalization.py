"""Governed vocabulary lookup for canonical tick-surveillance records.

This is intentionally a small registry reader, not an adapter.  It never
guesses at source values and it does not decide whether observations can be
pooled, compared, or aggregated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "contracts"
    / "tick-surveillance"
    / "tick-surveillance-normalization-v1.json"
)

NormalizationStatus = Literal["APPROVED", "UNKNOWN", "UNSUPPORTED", "AMBIGUOUS"]


@dataclass(frozen=True)
class NormalizationResult:
    """A mapping result that retains raw value and pinned registry provenance."""

    source_value: str | int | float | bool
    canonical_id: str | None
    canonical_label: str | None
    status: NormalizationStatus
    mapping_rule_id: str | None
    registry_id: str
    registry_version: str
    source_context: dict[str, str]
    disposition: str | None = None

    def as_contract_value(self) -> dict[str, object]:
        """Return the provenance-bearing representation carried by the contract."""
        value: dict[str, object] = {
            "source_value": self.source_value,
            "canonical_id": self.canonical_id,
            "canonical_label": self.canonical_label,
            "status": self.status,
            "mapping_rule_id": self.mapping_rule_id,
            "registry_id": self.registry_id,
            "registry_version": self.registry_version,
            "source_context": self.source_context,
        }
        if self.disposition is not None:
            value["disposition"] = self.disposition
        return value


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    """Load the pinned, source-controlled registry without fetching source data."""
    registry = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(registry, dict):
        raise ValueError("tick normalization registry must be a JSON object")
    if registry.get("registry_id") != "tick-surveillance-normalization-v1":
        raise ValueError("tick normalization registry ID is not approved")
    if registry.get("status") != "APPROVED":
        raise ValueError("tick normalization registry is not approved")
    if not isinstance(registry.get("registry_version"), str):
        raise ValueError("tick normalization registry version is missing")
    if not isinstance(registry.get("mappings"), list):
        raise ValueError("tick normalization registry mappings are invalid")
    return registry


def normalize_value(
    *,
    field: str,
    source_value: str | int | float | bool,
    publisher: str,
    dataset_id: str,
    source_version: str,
    registry: dict[str, Any] | None = None,
) -> NormalizationResult:
    """Return an exact governed mapping or an explicit fail-closed result."""
    current = registry or load_registry()
    context = {
        "publisher": publisher,
        "dataset_id": dataset_id,
        "source_version": source_version,
    }
    matches = [
        rule
        for rule in current["mappings"]
        if rule["field"] == field
        and rule["source_value"] == source_value
        and rule["source_context"] == context
    ]
    if len(matches) != 1:
        return NormalizationResult(
            source_value=source_value,
            canonical_id=None,
            canonical_label=None,
            status="AMBIGUOUS" if len(matches) > 1 else "UNKNOWN",
            mapping_rule_id=None,
            registry_id=current["registry_id"],
            registry_version=current["registry_version"],
            source_context=context,
        )
    rule = matches[0]
    return NormalizationResult(
        source_value=source_value,
        canonical_id=rule["canonical_id"],
        canonical_label=rule["canonical_label"],
        status=rule["status"],
        mapping_rule_id=rule["rule_id"],
        registry_id=current["registry_id"],
        registry_version=current["registry_version"],
        source_context=context,
        disposition=(
            str(rule["disposition"]) if isinstance(rule.get("disposition"), str) else None
        ),
    )


def convert_value(
    *,
    field: Literal["effort_unit", "abundance_unit"],
    value: float,
    from_canonical_id: str,
    to_canonical_id: str,
    denominator_present: bool,
    registry: dict[str, Any] | None = None,
) -> tuple[float, str]:
    """Apply one explicitly-approved dimensional conversion or fail closed."""
    current = registry or load_registry()
    matches = [
        conversion
        for conversion in current["conversions"]
        if conversion["field"] == field
        and conversion["from_canonical_id"] == from_canonical_id
        and conversion["to_canonical_id"] == to_canonical_id
        and conversion["status"] == "APPROVED"
    ]
    if len(matches) != 1:
        raise ValueError("unsupported or ambiguous governed unit conversion")
    conversion = matches[0]
    if conversion["requires_denominator"] and not denominator_present:
        raise ValueError("abundance conversion requires a documented denominator")
    return value * float(conversion["factor"]), str(conversion["rule_id"])
