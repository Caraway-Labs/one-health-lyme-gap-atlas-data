"""Bind existing governed records to the #190/#191/#193 semantic contracts.

The caller supplies retained canonical/derived records and an authority snapshot.
This module performs no ingestion, database access, or publication.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lyme_gap_atlas_data.semantic_domain import (
    CONTRACT_VERSION as DOMAIN_VERSION,
)
from lyme_gap_atlas_data.semantic_domain import (
    observation_key,
    revision_id,
    validate_domain,
)
from lyme_gap_atlas_data.semantic_lineage import (
    CONTRACT_VERSION as LINEAGE_VERSION,
)
from lyme_gap_atlas_data.semantic_lineage import (
    lineage_id,
    validate_lineage,
)
from lyme_gap_atlas_data.semantic_metadata import validate_metadata
from lyme_gap_atlas_data.tick_normalization import normalize_value

CONTRACT_VERSION = "atlas-semantic-source-mappings-v1"
_SOURCE_FIELDS = (
    "source_id",
    "dataset_id",
    "source_version_id",
    "source_vintage",
    "ingestion_run_id",
    "artifact_id",
    "source_record_id",
    "source_row_hash",
)


class SemanticMappingError(ValueError):
    """A supplied record is incompatible with its exact governed mapping."""


def load_mapping_registry(path: Path) -> dict[str, Mapping[str, Any]]:
    """Load a versioned mapping document; malformed or duplicate rules fail."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("contract_version") != CONTRACT_VERSION:
        raise SemanticMappingError("unsupported mapping contract version")
    mappings = document.get("mappings")
    if not isinstance(mappings, list) or not mappings:
        raise SemanticMappingError("mapping registry is empty")
    result: dict[str, Mapping[str, Any]] = {}
    for mapping in mappings:
        if not isinstance(mapping, Mapping) or not isinstance(mapping.get("id"), str):
            raise SemanticMappingError("invalid mapping entry")
        for field in ("resource_key", "vintage", "measure_id", "field"):
            _required(mapping, field)
        if (
            not isinstance(mapping.get("definition_version"), int)
            or mapping["definition_version"] < 1
        ):
            raise SemanticMappingError("invalid source definition version")
        if mapping.get("origin") not in {"REPORTED", "DERIVED"} or mapping.get("grain") not in {
            "COUNTY",
            "SITE_EVENT",
            "SOURCE_ONLY_COUNTY",
        }:
            raise SemanticMappingError("invalid mapping origin or grain")
        if mapping.get("time") not in {"PERIOD", "POINT_IN_TIME", "CUMULATIVE_THROUGH_DATE"}:
            raise SemanticMappingError("invalid mapping time")
        if mapping.get("status") not in {"EXISTING_REUSED", "NEW_SEMANTIC_MAPPING"}:
            raise SemanticMappingError("invalid executable mapping status")
        identity = mapping["id"]
        if identity in result:
            raise SemanticMappingError("duplicate mapping identity")
        result[identity] = mapping
    return result


def _required(mapping: Mapping[str, Any], field: str) -> Any:
    value = mapping.get(field)
    if value is None or value == "":
        raise SemanticMappingError(f"missing required {field}")
    return value


def _bind_source(
    edge: Mapping[str, Any], mapping: Mapping[str, Any], authority: Mapping[str, Any]
) -> None:
    versions = authority.get("source_versions")
    version_id = _required(edge, "source_version_id")
    source = versions.get(version_id) if isinstance(versions, Mapping) else None
    if not isinstance(source, Mapping):
        raise SemanticMappingError("unknown governed source version")
    for field in ("resource_key", "source_id", "dataset_id"):
        if edge.get(field) != source.get(field):
            raise SemanticMappingError(f"incompatible {field} for mapping")
        if field in mapping and source.get(field) != mapping[field]:
            raise SemanticMappingError(f"incompatible {field} for mapping")
    if edge.get("source_vintage") != mapping.get("vintage") or source.get(
        "source_vintage"
    ) != mapping.get("vintage"):
        raise SemanticMappingError("wrong source vintage")
    if source.get("definition_version") != mapping.get("definition_version"):
        raise SemanticMappingError("wrong source definition version")
    if source.get("approved") is not True:
        raise SemanticMappingError("source version is not approved")
    if "product" in mapping and source.get("product") != mapping["product"]:
        raise SemanticMappingError("wrong source product")


def _validate_strata(
    record: Mapping[str, Any], mapping: Mapping[str, Any], edges: list[Mapping[str, Any]]
) -> None:
    strata = record.get("strata", {})
    if not isinstance(strata, Mapping):
        raise SemanticMappingError("invalid strata")
    if not set(mapping.get("required_strata", [])) <= set(strata):
        raise SemanticMappingError("missing required canonical strata")
    if mapping.get("required_proof") and not all(
        edge.get(mapping["required_proof"]) for edge in edges
    ):
        raise SemanticMappingError("missing exact-source normalization or eligibility proof")
    evidence = record.get("strata_evidence", {})
    if not isinstance(evidence, Mapping) or set(evidence) != set(strata):
        raise SemanticMappingError("strata need exact-source evidence")
    for field, canonical_id in strata.items():
        proof = evidence[field]
        if not isinstance(proof, Mapping):
            raise SemanticMappingError("invalid stratum proof")
        context = proof.get("source_context")
        if not isinstance(context, Mapping) or context.get("source_version") != mapping["vintage"]:
            raise SemanticMappingError("wrong stratum source version")
        product = context.get("dataset_id")
        if mapping["resource_key"] == "neon_tick_release_2026":
            if context.get("publisher") != "NSF NEON" or product not in {
                "DP1.10093.001",
                "DP1.10092.001",
            }:
                raise SemanticMappingError("wrong stratum source product")
        elif product not in {edge["dataset_id"] for edge in edges}:
            raise SemanticMappingError("wrong stratum source product")
        source_value = proof.get("source_value")
        if not isinstance(source_value, (str, int, float, bool)):
            raise SemanticMappingError("missing source-native stratum value")
        result = normalize_value(
            field=field,
            source_value=source_value,
            publisher=str(context.get("publisher")),
            dataset_id=str(product),
            source_version=mapping["vintage"],
        )
        if (
            result.status != "APPROVED"
            or result.canonical_id != canonical_id
            or result.mapping_rule_id != proof.get("mapping_rule_id")
            or result.registry_id != proof.get("registry_id")
            or result.registry_version != proof.get("registry_version")
        ):
            raise SemanticMappingError("unapproved or display-label canonical stratum")


def map_record(
    record: Mapping[str, Any],
    metadata: Mapping[str, Any],
    authority: Mapping[str, Any],
    mappings: Mapping[str, Mapping[str, Any]],
    *,
    fixture_mode: bool = False,
) -> dict[str, Any]:
    """Create a deterministic semantic assertion and complete trace.

    `record` is a selected existing canonical or derived safe record. Its edges
    must resolve against the supplied governed #193 authority snapshot. No
    value, denominator, county, time, or scientific ID is inferred here.
    """
    mapping_id = _required(record, "mapping_id")
    mapping = mappings.get(mapping_id)
    if mapping is None:
        raise SemanticMappingError("unknown source mapping")
    edges = _required(record, "edges")
    if (
        not isinstance(edges, list)
        or not edges
        or not all(isinstance(edge, Mapping) for edge in edges)
    ):
        raise SemanticMappingError("source lineage edges required")
    for edge in edges:
        _bind_source(edge, mapping, authority)
    validate_metadata(metadata)
    if metadata["steward_review"]["state"] != "REVIEWED" and not (
        fixture_mode and record.get("fixture") is True
    ):
        raise SemanticMappingError("unreviewed semantic metadata cannot map live records")
    measure = metadata["measure"]
    for actual, expected, name in (
        (measure["measure_id"], mapping["measure_id"], "measure"),
        (measure["origin"], mapping["origin"], "origin"),
        (measure["geography_grain"], mapping["grain"], "geography grain"),
        (measure["temporal_semantics"], mapping["time"], "temporal semantics"),
        (record.get("unit"), measure["unit"], "unit"),
        (record.get("denominator"), measure["denominator"], "denominator"),
    ):
        if actual != expected:
            raise SemanticMappingError(f"incompatible {name}")
    if record.get("indicator_id") != measure["indicator_id"]:
        raise SemanticMappingError("wrong indicator identity")
    _validate_strata(record, mapping, edges)
    fields = record.get("fields")
    if not isinstance(fields, Mapping) or mapping["field"] not in fields:
        raise SemanticMappingError("missing required canonical field")
    value = fields[mapping["field"]]
    if value != record.get("value"):
        raise SemanticMappingError("canonical field/value disagreement")
    if measure["denominator"] != "NONE" and record.get("value_state") in {"OBSERVED", "ZERO"}:
        denominator_value = record.get("denominator_value")
        if (
            not isinstance(denominator_value, (int, float))
            or isinstance(denominator_value, bool)
            or denominator_value <= 0
        ):
            raise SemanticMappingError("positive governed denominator value required")
    geography = _required(record, "geography")
    temporal = _required(record, "temporal")
    if not isinstance(geography, Mapping) or not isinstance(temporal, Mapping):
        raise SemanticMappingError("geography and time scopes required")
    if geography.get("grain") != mapping["grain"] or temporal.get("semantics") != mapping["time"]:
        raise SemanticMappingError("incompatible native geography or time")
    first = edges[0]
    if mapping["origin"] == "REPORTED":
        if len(edges) != 1 or record.get("result") is not None:
            raise SemanticMappingError("reported mapping requires one source record")
        provenance = {key: first.get(key) for key in _SOURCE_FIELDS}
        provenance["retrieved_at"] = _required(record, "retrieved_at")
    else:
        inputs = _required(record, "input_ids")
        if not isinstance(inputs, list) or not inputs or len(set(inputs)) != len(inputs):
            raise SemanticMappingError("derived inputs required and unique")
        provenance = {
            "dataset_id": _required(record, "output_dataset_id"),
            "transformation_version": _required(record, "transformation_version"),
            "input_ids": inputs,
            "evidence_basis": _required(record, "evidence_basis"),
            "lineage_sources": [
                {key: edge.get(key) for key in _SOURCE_FIELDS}
                | {"retrieved_at": _required(record, "retrieved_at")}
                for edge in edges
            ],
        }
        if not isinstance(record.get("result"), Mapping):
            raise SemanticMappingError("derived result identity and revision required")
    observation = {
        "contract_version": DOMAIN_VERSION,
        "measure_id": measure["measure_id"],
        "measure_version": measure["semantic_version"],
        "unit": measure["unit"],
        "denominator": measure["denominator"],
        "origin": mapping["origin"],
        "geography": dict(geography),
        "temporal": dict(temporal),
        "strata": dict(record.get("strata", {})),
        "provenance": provenance,
        "value": value,
        "value_state": _required(record, "value_state"),
        "quality_ref": record.get("quality_ref"),
        "eligibility_ref": record.get("eligibility_ref"),
        "limitations_ref": record.get("limitations_ref"),
    }
    observation["observation_key"] = observation_key(observation, measure)
    observation["revision_id"] = revision_id(observation)
    validate_domain([measure], [observation])
    transformation = _required(record, "transformation")
    if not isinstance(transformation, Mapping):
        raise SemanticMappingError("transformation identity required")
    lineage = {
        "contract_version": LINEAGE_VERSION,
        "visibility": "INTERNAL",
        "semantic_observation_id": observation["observation_key"],
        "semantic_revision_id": observation["revision_id"],
        "metadata_revision_id": metadata["revision_id"],
        "metadata": metadata,
        "observation": observation,
        "edges": edges,
        "input_ids": record.get("input_ids", []),
        "transformation": dict(transformation),
        "result": record.get("result"),
        "release": record.get("release"),
    }
    lineage["lineage_id"] = lineage_id(lineage)
    validate_lineage(lineage, authority)
    return {
        "mapping_contract_version": CONTRACT_VERSION,
        "mapping_id": mapping_id,
        "source_id": first["source_id"],
        "dataset_id": provenance["dataset_id"],
        "indicator_id": measure["indicator_id"],
        "measure_id": measure["measure_id"],
        "semantic_version": measure["semantic_version"],
        "metadata_id": metadata["metadata_id"],
        "metadata_revision_id": metadata["revision_id"],
        "lineage_id": lineage["lineage_id"],
        "observation": observation,
        "lineage": lineage,
    }


def map_records(
    records: Sequence[Mapping[str, Any]],
    metadata_by_mapping: Mapping[str, Mapping[str, Any]],
    authority: Mapping[str, Any],
    mappings: Mapping[str, Mapping[str, Any]],
    *,
    fixture_mode: bool = False,
) -> list[dict[str, Any]]:
    """Reject duplicate semantic assertions or conflicting immutable revisions."""
    output: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    revisions: set[str] = set()
    for record in records:
        identity = _required(record, "mapping_id")
        metadata = metadata_by_mapping.get(identity)
        if metadata is None:
            raise SemanticMappingError("missing mandatory metadata reference")
        mapped = map_record(record, metadata, authority, mappings, fixture_mode=fixture_mode)
        observation = mapped["observation"]
        key, revision = observation["observation_key"], observation["revision_id"]
        if key in seen or revision in revisions:
            raise SemanticMappingError("duplicate semantic observation or conflicting revision")
        seen[key] = revision
        revisions.add(revision)
        output.append(mapped)
    return output
