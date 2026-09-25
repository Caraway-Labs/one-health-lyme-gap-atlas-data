"""Storage-neutral, fail-closed lineage relationships for Story #193.

The supplied authority snapshot is assembled by a caller from existing governed
ledgers. This module neither grants access to them nor persists another ledger.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from lyme_gap_atlas_data.semantic_domain import validate_observation
from lyme_gap_atlas_data.semantic_metadata import validate_metadata
from lyme_gap_atlas_data.surveillance_safe import has_sensitive_path

CONTRACT_VERSION = "atlas-semantic-lineage-v1"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_UNSAFE = re.compile(
    r"(?:[a-z][a-z0-9+.-]*://|[?&](?:token|signature|credential|password|secret)="
    r"|-----BEGIN (?:[A-Z ]+)?PRIVATE KEY-----|[A-Za-z]:\\|(?:^|\s)/(?:home|tmp|private|mnt)/)",
    re.IGNORECASE,
)
_UNSAFE_KEY = re.compile(
    r"(?:raw|path|url|secret|token|credential|password|private.key|payload|signed)",
    re.IGNORECASE,
)
_BASIS = {
    "infected-tick-metrics-v1": {
        "SYNTHETIC_FIXTURE",
        "CURRENT_CODE_CI_TESTED_SOURCE_REPLAY_LIMITED",
    },
    "surveillance-coverage-v1": {
        "SYNTHETIC_FIXTURE",
        "CURRENT_CODE_SOURCE_BACKED_REPLAY",
    },
    "surveillance-priority-v1": {
        "SYNTHETIC_FIXTURE",
        "CURRENT_CODE_SOURCE_BACKED_REPLAY",
    },
}


class SemanticLineageError(ValueError):
    """A lineage edge disagrees with its governed authority snapshot."""


def _required(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or not _REF.fullmatch(value):
        raise SemanticLineageError(f"invalid or missing {name}")
    return value


def _object(registry: Mapping[str, Any], kind: str, identity: str) -> Mapping[str, Any]:
    collection = registry.get(kind)
    item = collection.get(identity) if isinstance(collection, Mapping) else None
    if not isinstance(item, Mapping):
        raise SemanticLineageError(f"orphan {kind} reference: {identity}")
    return item


def _same(actual: object, expected: object, name: str) -> None:
    if actual != expected:
        raise SemanticLineageError(f"{name} mismatch")


def _safe(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or _UNSAFE_KEY.search(key) or _UNSAFE.search(key):
                raise SemanticLineageError("restricted consumer lineage key")
            _safe(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _safe(item)
    elif isinstance(value, str) and (_UNSAFE.search(value) or has_sensitive_path(value)):
        raise SemanticLineageError("restricted consumer lineage value")


def lineage_id(lineage: Mapping[str, Any]) -> str:
    """Content identity is invariant to ordering of distinct input edges."""
    content = deepcopy({key: value for key, value in lineage.items() if key != "lineage_id"})
    if isinstance(content.get("edges"), list):
        content["edges"] = sorted(content["edges"], key=lambda edge: edge["record_id"])
    if isinstance(content.get("input_ids"), list):
        content["input_ids"] = sorted(content["input_ids"])
    observation = content.get("observation")
    if isinstance(observation, dict) and observation.get("origin") == "DERIVED":
        provenance = observation.get("provenance")
        if isinstance(provenance, dict):
            if isinstance(provenance.get("input_ids"), list):
                provenance["input_ids"] = sorted(provenance["input_ids"])
            if isinstance(provenance.get("lineage_sources"), list):
                provenance["lineage_sources"] = sorted(
                    provenance["lineage_sources"],
                    key=lambda source: json.dumps(source, sort_keys=True),
                )
    digest = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return "lineage:v1:" + digest


def _validate_edge(edge: Mapping[str, Any], registry: Mapping[str, Any]) -> None:
    version_id = _required(edge.get("source_version_id"), "source version")
    source = _object(registry, "source_versions", version_id)
    for field in ("source_id", "dataset_id", "resource_key", "source_vintage", "publisher"):
        _same(edge.get(field), source.get(field), field)
    run_id = _required(edge.get("ingestion_run_id"), "ingestion run")
    run = _object(registry, "runs", run_id)
    _same(run.get("source_version_id"), version_id, "run/source version")
    _same(run.get("dataset_id"), source.get("dataset_id"), "run/dataset")
    artifact_id = _required(edge.get("artifact_id"), "artifact")
    artifact = _object(registry, "artifacts", artifact_id)
    _same(artifact.get("ingestion_run_id"), run_id, "artifact/run")
    _same(artifact.get("source_version_id"), version_id, "artifact/source version")
    artifact_hash = edge.get("artifact_sha256")
    if not isinstance(artifact_hash, str) or not _SHA.fullmatch(artifact_hash):
        raise SemanticLineageError("invalid artifact hash")
    _same(artifact_hash, artifact.get("sha256"), "artifact hash")
    record_id = _required(edge.get("record_id"), "record")
    record = _object(registry, "records", record_id)
    for field, expected in (
        ("artifact_id", artifact_id),
        ("ingestion_run_id", run_id),
        ("source_version_id", version_id),
        ("source_record_id", edge.get("source_record_id")),
        ("source_row_hash", edge.get("source_row_hash")),
        ("canonical_record_id", edge.get("canonical_record_id")),
        ("record_revision", edge.get("record_revision")),
    ):
        _same(record.get(field), expected, f"record/{field}")
    if not edge.get("source_record_id") and not edge.get("source_row_hash"):
        raise SemanticLineageError("source record reference required")
    if not edge.get("canonical_record_id") and edge.get("record_kind") != "SOURCE_ONLY":
        raise SemanticLineageError("canonical record reference required")
    _same(edge.get("record_kind"), record.get("record_kind"), "record kind")
    for name in ("normalization_ref", "eligibility_ref"):
        proof_id = edge.get(name)
        if proof_id is None:
            continue
        proof = _object(registry, "proofs", _required(proof_id, name))
        _same(proof.get("record_id"), record_id, f"{name}/record")
        _same(proof.get("source_version_id"), version_id, f"{name}/source version")
        if proof.get("kind") != name.removesuffix("_ref").upper():
            raise SemanticLineageError(f"invalid {name}")
        _required(proof.get("contract_version"), f"{name} contract version")
    if edge.get("record_kind") == "SOURCE_ONLY" and (
        edge.get("canonical_record_id") is not None or not edge.get("unresolved_reason")
    ):
        raise SemanticLineageError("source-only record cannot claim canonical identity")


def validate_lineage(lineage: Mapping[str, Any], registry: Mapping[str, Any]) -> None:
    """Validate a complete semantic trace against explicit authority records."""
    if lineage.get("contract_version") != CONTRACT_VERSION:
        raise SemanticLineageError("unsupported lineage contract version")
    observation = lineage.get("observation")
    metadata = lineage.get("metadata")
    if not isinstance(observation, Mapping) or not isinstance(metadata, Mapping):
        raise SemanticLineageError("observation and metadata required")
    validate_metadata(metadata)
    measure = metadata["measure"]
    validate_observation(observation, measure)
    _same(
        lineage.get("semantic_observation_id"),
        observation["observation_key"],
        "semantic observation",
    )
    _same(lineage.get("semantic_revision_id"), observation["revision_id"], "semantic revision")
    _same(lineage.get("metadata_revision_id"), metadata["revision_id"], "metadata revision")
    edges = lineage.get("edges")
    if not isinstance(edges, list) or not edges:
        raise SemanticLineageError("source edges required")
    record_ids: set[str] = set()
    for edge in edges:
        if not isinstance(edge, Mapping):
            raise SemanticLineageError("invalid source edge")
        _validate_edge(edge, registry)
        record_id = edge["record_id"]
        if record_id in record_ids:
            raise SemanticLineageError("duplicate ambiguous lineage edge")
        record_ids.add(record_id)
    provenance = observation["provenance"]
    if observation["origin"] == "REPORTED":
        if len(edges) != 1:
            raise SemanticLineageError("reported observation requires one record edge")
        edge = edges[0]
        for field in (
            "source_id",
            "dataset_id",
            "source_version_id",
            "source_vintage",
            "ingestion_run_id",
            "artifact_id",
        ):
            _same(provenance.get(field), edge.get(field), f"observation/{field}")
        if provenance.get("source_record_id"):
            _same(
                provenance["source_record_id"],
                edge.get("source_record_id"),
                "observation/source record",
            )
        elif provenance.get("source_row_hash"):
            _same(
                provenance["source_row_hash"],
                edge.get("source_row_hash"),
                "observation/source hash",
            )
    else:
        inputs = lineage.get("input_ids")
        if not isinstance(inputs, list) or not inputs or len(set(inputs)) != len(inputs):
            raise SemanticLineageError("derived inputs required and unique")
        _same(set(inputs), set(provenance["input_ids"]), "derived input set")
        input_registry = registry.get("inputs")
        if not isinstance(input_registry, Mapping):
            raise SemanticLineageError("input authority required")
        for input_id in inputs:
            source_record = input_registry.get(input_id)
            if source_record not in record_ids:
                raise SemanticLineageError("orphan derived input")
        if len({input_registry[input_id] for input_id in inputs}) != len(inputs):
            raise SemanticLineageError("duplicate derived source record")
        for source in provenance["lineage_sources"]:
            if not any(
                all(
                    source.get(field) == edge.get(field)
                    for field in (
                        "source_id",
                        "dataset_id",
                        "source_version_id",
                        "source_vintage",
                        "ingestion_run_id",
                        "artifact_id",
                        "source_record_id",
                        "source_row_hash",
                    )
                )
                for edge in edges
            ):
                raise SemanticLineageError("derived source lineage mismatch")
    method = lineage.get("transformation")
    if not isinstance(method, Mapping):
        raise SemanticLineageError("transformation required")
    _required(method.get("id"), "transformation ID")
    _required(method.get("version"), "transformation version")
    _same(method.get("methodology_version"), measure["methodology_version"], "methodology version")
    if observation["origin"] == "DERIVED":
        _same(
            method["version"],
            provenance["transformation_version"],
            "derived transformation version",
        )
        basis = provenance["evidence_basis"]
        if basis not in _BASIS.get(measure["methodology_version"], set()):
            raise SemanticLineageError("invalid evidence-basis combination")
        _same(
            basis,
            metadata["quality_evidence"]["evidence_basis"]["value"],
            "metadata evidence basis",
        )
        result = lineage.get("result")
        if not isinstance(result, Mapping):
            raise SemanticLineageError("derived result revision required")
        result_id = _required(result.get("result_id"), "derived result ID")
        result_revision = _required(result.get("revision_id"), "derived result revision")
        authoritative = _object(registry, "results", result_revision)
        for field, value in (
            ("result_id", result_id),
            ("semantic_revision_id", observation["revision_id"]),
            ("evidence_basis", basis),
            ("transformation_version", method["version"]),
        ):
            _same(authoritative.get(field), value, f"result/{field}")
        _same(set(authoritative.get("input_ids", [])), set(lineage["input_ids"]), "result inputs")
    elif lineage.get("result") is not None or lineage.get("input_ids"):
        raise SemanticLineageError("reported observation cannot claim derived result")
    first = edges[0]
    meta_prov = metadata["provenance"]
    for field in ("source_id", "dataset_id", "source_version_id", "source_vintage", "publisher"):
        _same(meta_prov[field]["value"], first[field], f"metadata/{field}")
    _same(meta_prov["method_version"]["value"], method["methodology_version"], "metadata method")
    release = lineage.get("release")
    if release is not None:
        if (
            not isinstance(release, Mapping)
            or observation["geography"]["grain"] == "SOURCE_ONLY_COUNTY"
        ):
            raise SemanticLineageError("invalid release inclusion")
        release_id = _required(release.get("release_id"), "release ID")
        membership = _object(registry, "releases", release_id)
        _same(release.get("bundle_sha256"), membership.get("bundle_sha256"), "release bundle")
        if observation["revision_id"] not in membership.get("semantic_revision_ids", []):
            raise SemanticLineageError("ambiguous cross-release reference")
        if release.get("observation_id") not in membership.get("observation_ids", []):
            raise SemanticLineageError("orphan release observation")
    if lineage.get("visibility") not in {"INTERNAL", "CONSUMER_SAFE"}:
        raise SemanticLineageError("invalid lineage visibility")
    if lineage.get("visibility") == "CONSUMER_SAFE":
        consumer_safe_lineage(lineage)
    if lineage.get("lineage_id") != lineage_id(lineage):
        raise SemanticLineageError("lineage identity mismatch")


def consumer_safe_lineage(lineage: Mapping[str, Any]) -> dict[str, Any]:
    """Return only reviewed lineage attributes; validate every emitted value."""
    metadata = lineage["metadata"]
    observation = lineage["observation"]
    result = lineage.get("result")
    safe = {
        "lineage_id": lineage.get("lineage_id"),
        "semantic_observation_id": lineage["semantic_observation_id"],
        "semantic_revision_id": lineage["semantic_revision_id"],
        "measure_id": observation["measure_id"],
        "measure_version": observation["measure_version"],
        "metadata_revision_id": lineage["metadata_revision_id"],
        "publisher": metadata["provenance"]["publisher"]["value"],
        "dataset_id": metadata["provenance"]["dataset_id"]["value"],
        "source_version_id": metadata["provenance"]["source_version_id"]["value"],
        "source_vintage": metadata["provenance"]["source_vintage"]["value"],
        "methodology_version": lineage["transformation"]["methodology_version"],
        "transformation_version": lineage["transformation"]["version"],
        "limitations": metadata["limitations"],
        "evidence_basis": observation["provenance"].get("evidence_basis"),
        "representativeness": observation["geography"].get("representativeness"),
        "record_refs": [edge["record_id"] for edge in lineage["edges"]],
        "result_id": result.get("result_id") if isinstance(result, Mapping) else None,
        "result_revision_id": result.get("revision_id") if isinstance(result, Mapping) else None,
        "release_id": lineage["release"]["release_id"] if lineage.get("release") else None,
    }
    _safe(safe)
    return safe


def validate_lineages(lineages: Sequence[Mapping[str, Any]], registry: Mapping[str, Any]) -> None:
    """Reject duplicate immutable IDs or changed content under an existing ID."""
    seen: set[str] = set()
    for lineage in lineages:
        validate_lineage(lineage, registry)
        identity = lineage["lineage_id"]
        if identity in seen:
            raise SemanticLineageError("duplicate immutable lineage identity")
        seen.add(identity)
