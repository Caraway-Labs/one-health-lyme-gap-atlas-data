"""Exact-source scientific eligibility shared by coverage and priority.

The registry describes lexical mappings.  This boundary additionally binds a
mapping to the observation, construct, and approved source vintage.  It never
derives eligibility from global canonical membership.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .tick_normalization import load_registry

MODEL_VERSION = "surveillance-scientific-eligibility-v1"
_TUPLES_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/contracts/tick-surveillance/surveillance-scientific-eligibility-v1.json"
)


def approved_source_tuple(construct: str, context: Mapping[str, Any]) -> bool:
    """Require one governed publisher/product/version/vintage/role tuple."""
    policy = json.loads(_TUPLES_PATH.read_text(encoding="utf-8"))
    return any(
        row["construct_id"] == construct
        and all(
            context.get(key) == row[key]
            for key in (
                "source_family",
                "publisher",
                "source_dataset_id",
                "source_version_id",
                "source_vintage",
            )
        )
        for row in policy["approved_tuples"]
    )


def scientific_attestation(
    observation: Mapping[str, Any],
    *,
    field: str,
    role: str,
    represented_value: object,
    source_context: Mapping[str, Any],
) -> dict[str, object]:
    """Attest one scientific value against its exact source mapping.

    IDs and labels are accepted at the boundary and normalized to canonical ID.
    The retained source value is checked against the registry rule, but is never
    copied into this consumer-safe attestation.
    """
    registry = load_registry()
    normalization = observation.get("normalization")
    mappings = normalization.get("mappings") if isinstance(normalization, Mapping) else None
    expected_context = {
        "publisher": source_context.get("publisher"),
        "dataset_id": source_context.get("source_dataset_id"),
        "source_version": source_context.get("source_version_id"),
    }
    base: dict[str, object] = {
        "attestation_version": MODEL_VERSION,
        "field": field,
        "semantic_role": role,
        "publisher": expected_context["publisher"],
        "source_dataset_id": expected_context["dataset_id"],
        "source_version_id": expected_context["source_version"],
        "registry_id": registry["registry_id"],
        "registry_version": registry["registry_version"],
        "canonical_id": None,
        "canonical_label": None,
        "normalization_rule_id": None,
        "mapping_status": "UNPROVEN",
        "aggregate": None,
        "eligibility": "UNPROVEN",
    }
    if (
        not isinstance(normalization, Mapping)
        or normalization.get("registry_id") != registry["registry_id"]
        or normalization.get("registry_version") != registry["registry_version"]
        or not isinstance(mappings, Mapping)
    ):
        return base
    candidates = [
        (entry, rule)
        for entry in mappings.values()
        if isinstance(entry, Mapping)
        for rule in registry["mappings"]
        if rule.get("field") == field
        and entry.get("mapping_rule_id") == rule.get("rule_id")
        and entry.get("source_value") == rule.get("source_value")
        and entry.get("source_context") == expected_context
        and rule.get("source_context") == expected_context
        and entry.get("canonical_id") == rule.get("canonical_id")
        and entry.get("canonical_label") == rule.get("canonical_label")
        and entry.get("status") == rule.get("status")
        and entry.get("registry_id") == registry["registry_id"]
        and entry.get("registry_version") == registry["registry_version"]
    ]
    if len(candidates) != 1:
        base["mapping_status"] = "AMBIGUOUS" if len(candidates) > 1 else "UNPROVEN"
        return base
    entry, rule = candidates[0]
    canonical_id = rule.get("canonical_id")
    label = rule.get("canonical_label")
    canonical = next(
        (
            value
            for value in registry["canonical_values"].get(field, [])
            if value.get("id") == canonical_id and value.get("label") == label
        ),
        None,
    )
    base.update(
        canonical_id=canonical_id,
        canonical_label=label,
        normalization_rule_id=rule["rule_id"],
        mapping_status=rule["status"],
        aggregate=canonical.get("aggregate", False) if canonical else None,
    )
    if (
        rule["status"] == "APPROVED"
        and canonical is not None
        and not canonical.get("aggregate", False)
        and represented_value in (canonical_id, label)
    ):
        base["eligibility"] = "ELIGIBLE"
    return base


def proven(attestation: Mapping[str, Any] | None) -> bool:
    return isinstance(attestation, Mapping) and attestation.get("eligibility") == "ELIGIBLE"


def verify_safe_attestation(
    attestation: Mapping[str, Any], *, construct: str, context: Mapping[str, Any]
) -> bool:
    """Recheck consumer-safe proof against the pinned exact-source registry."""
    if (
        attestation.get("attestation_version") != MODEL_VERSION
        or attestation.get("semantic_role") != construct
        or attestation.get("eligibility") != "ELIGIBLE"
        or attestation.get("aggregate") is not False
        or attestation.get("mapping_status") != "APPROVED"
        or attestation.get("publisher") != context.get("publisher")
        or attestation.get("source_dataset_id") != context.get("source_dataset_id")
        or attestation.get("source_version_id") != context.get("source_version_id")
    ):
        return False
    registry = load_registry()
    if (
        attestation.get("registry_id") != registry["registry_id"]
        or attestation.get("registry_version") != registry["registry_version"]
    ):
        return False
    expected_context = {
        "publisher": context.get("publisher"),
        "dataset_id": context.get("source_dataset_id"),
        "source_version": context.get("source_version_id"),
    }
    matches = [
        rule
        for rule in registry["mappings"]
        if rule.get("field") == attestation.get("field")
        and rule.get("rule_id") == attestation.get("normalization_rule_id")
        and rule.get("canonical_id") == attestation.get("canonical_id")
        and rule.get("canonical_label") == attestation.get("canonical_label")
        and rule.get("status") == "APPROVED"
        and rule.get("source_context") == expected_context
    ]
    return len(matches) == 1 and any(
        value.get("id") == attestation.get("canonical_id")
        and value.get("label") == attestation.get("canonical_label")
        and not value.get("aggregate", False)
        for value in registry["canonical_values"].get(str(attestation.get("field")), [])
    )


def attest_scientific_fields(
    construct: str,
    observation: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    dimension: object = None,
) -> list[dict[str, object]]:
    """Return every construct-required dimension, including failed proof."""
    if construct == "COUNTY_STATUS_DATASET_REPRESENTATION":
        field = (
            "tick_taxon"
            if context.get("source_family") == "CDC_IXODES_COUNTY_STATUS"
            else "pathogen_target"
        )
        value = observation.get("tick_species" if field == "tick_taxon" else "pathogen_name")
        if not observation:
            registry = load_registry()
            observation = {
                "normalization": {
                    "registry_id": registry["registry_id"],
                    "registry_version": registry["registry_version"],
                    "mappings": {"dimension": context.get("dimension_mapping")},
                }
            }
            value = dimension
        return [
            scientific_attestation(
                observation,
                field=field,
                role=construct,
                represented_value=value,
                source_context=context,
            )
        ]
    fields: tuple[tuple[str, str], ...]
    if construct == "ACTIVE_TESTING_DENOMINATOR_AVAILABILITY":
        fields = (("pathogen_target", "pathogen_name"), ("test_result", "test_result"))
    else:
        fields = (
            ("tick_taxon", "tick_species"),
            ("life_stage", "life_stage"),
            ("collection_method", "collection_method"),
            ("effort_unit", "collection_effort_unit"),
        )
    return [
        scientific_attestation(
            observation,
            field=field,
            role=construct,
            represented_value=observation.get(key),
            source_context=context,
        )
        for field, key in fields
    ]
