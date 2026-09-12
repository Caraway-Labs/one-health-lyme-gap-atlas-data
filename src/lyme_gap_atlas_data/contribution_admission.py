"""Partial-accept admission for kg-v1 GraphContribution payloads.

Illegal edges are dropped with redacted diagnostics. Valid edges, and the
passages/nodes they still cite, are retained. Publish requires at least one
kept edge when the model proposed any edges.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from lyme_gap_atlas_kg import (
    EvidencePassageNode,
    GraphContribution,
    GraphNode,
    NodeType,
    PaperNode,
    RelationshipType,
    SemanticEdge,
    relationship_allowed,
)
from pydantic import ValidationError

# Compact endpoint matrix kept in sync with lyme_gap_atlas_kg.contracts via tests.
_ENDPOINT_MATRIX_LINES: tuple[str, ...] = (
    "ASSOCIATED_WITH: any knowledge entity -> any knowledge entity (not Paper or EvidencePassage)",
    "CAUSES: Pathogen|Exposure|EnvironmentalFactor -> DiseaseCondition|Outcome",
    "TRANSMITS: TickVector -> Pathogen",
    "CARRIES: TickVector|Host -> Pathogen",
    "INFECTS: Pathogen -> Host|StudyPopulation",
    "RESERVOIR_FOR: Host -> Pathogen",
    "EXPOSES_TO: Exposure|EnvironmentalFactor|TickVector -> StudyPopulation|Host|DiseaseCondition",
    "PREVENTS: Intervention -> DiseaseCondition|Outcome",
    "TREATS: Intervention -> DiseaseCondition|Outcome",
    "DIAGNOSES: Diagnostic -> DiseaseCondition|Pathogen",
    "HAS_OUTCOME: DiseaseCondition|Exposure|Intervention -> Outcome",
    "OCCURS_IN: any knowledge entity except Place -> Place",
    "INFLUENCES: EnvironmentalFactor|Exposure -> any other knowledge entity "
    "(not EnvironmentalFactor or Exposure)",
    "EVALUATES: Intervention|Diagnostic|Exposure -> Outcome|DiseaseCondition",
)

_EXPLICIT_ONLY = ("CAUSES", "TREATS", "PREVENTS", "DIAGNOSES")
_INFERENCE_ALLOWED = ("ASSOCIATED_WITH", "OCCURS_IN", "INFLUENCES")


@dataclass(frozen=True)
class RedactedEdgeDiagnostic:
    """Ontology-safe edge drop record; never includes claim_text or excerpts."""

    diagnostic_type: str
    edge_index: int
    edge_id: str | None
    relationship_type: str | None
    source_node_type: str | None
    target_node_type: str | None
    assertion_basis: str | None
    reason: str

    def as_ledger_payload(self) -> dict[str, object | None]:
        return asdict(self)


@dataclass(frozen=True)
class AdmittedContribution:
    contribution: GraphContribution
    dropped_edges: tuple[RedactedEdgeDiagnostic, ...]

    @property
    def dropped_edge_count(self) -> int:
        return len(self.dropped_edges)


class ContributionAdmissionError(ValueError):
    """Raised when admission cannot produce a publishable contribution."""

    def __init__(self, message: str, diagnostics: tuple[RedactedEdgeDiagnostic, ...] = ()) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


def endpoint_matrix_prompt() -> str:
    """Return the relationship endpoint matrix for the extraction prompt."""
    explicit = ", ".join(_EXPLICIT_ONLY)
    inferred = ", ".join(_INFERENCE_ALLOWED)
    lines = [
        "Allowed relationship endpoints (kg-v1.0.0). Omit edges that violate this matrix:",
        *[f"- {line}" for line in _ENDPOINT_MATRIX_LINES],
        "Assertion rules:",
        f"- Explicit-only relationships (assertion_basis must be explicit): {explicit}",
        f"- Inference allowed only for: {inferred}",
    ]
    return "\n".join(lines)


def _redacted_validation_reason(error: ValidationError | ValueError) -> str:
    if isinstance(error, ValueError) and not isinstance(error, ValidationError):
        return str(error)[:200]
    parts: list[str] = []
    for item in error.errors():
        loc = ".".join(str(part) for part in item.get("loc", ()))
        msg = str(item.get("msg", "invalid"))
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts)[:500] if parts else "validation_error"


def _edge_identity_fields(raw_edge: object) -> dict[str, str | None]:
    if not isinstance(raw_edge, dict):
        return {
            "edge_id": None,
            "relationship_type": None,
            "source_node_type": None,
            "target_node_type": None,
            "assertion_basis": None,
        }
    return {
        "edge_id": str(raw_edge["id"]) if raw_edge.get("id") is not None else None,
        "relationship_type": (
            str(raw_edge["relationship_type"])
            if raw_edge.get("relationship_type") is not None
            else None
        ),
        "source_node_type": (
            str(raw_edge["source_node_type"])
            if raw_edge.get("source_node_type") is not None
            else None
        ),
        "target_node_type": (
            str(raw_edge["target_node_type"])
            if raw_edge.get("target_node_type") is not None
            else None
        ),
        "assertion_basis": (
            str(raw_edge["assertion_basis"])
            if raw_edge.get("assertion_basis") is not None
            else None
        ),
    }


def admit_graph_contribution(payload: dict[str, object]) -> AdmittedContribution:
    """Validate a contribution, dropping illegal edges instead of rejecting all."""
    raw_passages = payload.get("passages", [])
    raw_nodes = payload.get("nodes", [])
    if not isinstance(raw_passages, list) or not isinstance(raw_nodes, list):
        raise ContributionAdmissionError(
            "graph contribution passages and nodes must be lists",
            (
                RedactedEdgeDiagnostic(
                    diagnostic_type="contribution_validation_failure",
                    edge_index=-1,
                    edge_id=None,
                    relationship_type=None,
                    source_node_type=None,
                    target_node_type=None,
                    assertion_basis=None,
                    reason="passages/nodes: not a list",
                ),
            ),
        )
    try:
        paper = PaperNode.model_validate(payload.get("paper"))
        passages = [EvidencePassageNode.model_validate(item) for item in raw_passages]
        nodes = [GraphNode.model_validate(item) for item in raw_nodes]
    except ValidationError as error:
        raise ContributionAdmissionError(
            "graph contribution identity failed validation",
            (
                RedactedEdgeDiagnostic(
                    diagnostic_type="contribution_validation_failure",
                    edge_index=-1,
                    edge_id=None,
                    relationship_type=None,
                    source_node_type=None,
                    target_node_type=None,
                    assertion_basis=None,
                    reason=_redacted_validation_reason(error),
                ),
            ),
        ) from error

    raw_edges = payload.get("edges", [])
    if not isinstance(raw_edges, list):
        raise ContributionAdmissionError(
            "graph contribution edges must be a list",
            (
                RedactedEdgeDiagnostic(
                    diagnostic_type="contribution_validation_failure",
                    edge_index=-1,
                    edge_id=None,
                    relationship_type=None,
                    source_node_type=None,
                    target_node_type=None,
                    assertion_basis=None,
                    reason="edges: not a list",
                ),
            ),
        )

    kept_edges: list[SemanticEdge] = []
    dropped: list[RedactedEdgeDiagnostic] = []
    for index, raw_edge in enumerate(raw_edges):
        identity = _edge_identity_fields(raw_edge)
        try:
            kept_edges.append(SemanticEdge.model_validate(raw_edge))
        except (ValidationError, ValueError) as error:
            dropped.append(
                RedactedEdgeDiagnostic(
                    diagnostic_type="dropped_illegal_edge",
                    edge_index=index,
                    edge_id=identity["edge_id"],
                    relationship_type=identity["relationship_type"],
                    source_node_type=identity["source_node_type"],
                    target_node_type=identity["target_node_type"],
                    assertion_basis=identity["assertion_basis"],
                    reason=_redacted_validation_reason(error),
                )
            )

    if raw_edges and not kept_edges:
        raise ContributionAdmissionError(
            "no valid edges remain after dropping illegal edges",
            tuple(dropped),
        )

    if kept_edges:
        passage_ids = {edge.evidence_passage_id for edge in kept_edges}
        node_ids = {edge.source_node_id for edge in kept_edges} | {
            edge.target_node_id for edge in kept_edges
        }
        passages = [passage for passage in passages if passage.id in passage_ids]
        nodes = [node for node in nodes if node.id in node_ids]
        if not passages:
            raise ContributionAdmissionError(
                "no evidence passages remain for kept edges",
                tuple(dropped),
            )

    try:
        contribution = GraphContribution(
            configuration_version=payload.get("configuration_version"),  # type: ignore[arg-type]
            paper=paper,
            passages=passages,
            nodes=nodes,
            edges=kept_edges,
        )
    except ValidationError as error:
        raise ContributionAdmissionError(
            "admitted contribution failed final validation",
            tuple(dropped)
            + (
                RedactedEdgeDiagnostic(
                    diagnostic_type="contribution_validation_failure",
                    edge_index=-1,
                    edge_id=None,
                    relationship_type=None,
                    source_node_type=None,
                    target_node_type=None,
                    assertion_basis=None,
                    reason=_redacted_validation_reason(error),
                ),
            ),
        ) from error

    return AdmittedContribution(contribution=contribution, dropped_edges=tuple(dropped))


def endpoint_matrix_matches_contract() -> list[str]:
    """Return drift messages when the prompt matrix disagrees with relationship_allowed."""
    drift: list[str] = []
    knowledge_entities = set(NodeType) - {NodeType.PAPER, NodeType.EVIDENCE_PASSAGE}
    expected: dict[RelationshipType, set[tuple[NodeType, NodeType]]] = {
        relationship: {
            (source, target)
            for source in NodeType
            for target in NodeType
            if relationship_allowed(relationship, source, target)
        }
        for relationship in RelationshipType
    }
    summaries = {
        RelationshipType.ASSOCIATED_WITH: {
            (source, target) for source in knowledge_entities for target in knowledge_entities
        },
        RelationshipType.CAUSES: {
            (source, target)
            for source in (
                NodeType.PATHOGEN,
                NodeType.EXPOSURE,
                NodeType.ENVIRONMENTAL_FACTOR,
            )
            for target in (NodeType.DISEASE_CONDITION, NodeType.OUTCOME)
        },
        RelationshipType.TRANSMITS: {(NodeType.TICK_VECTOR, NodeType.PATHOGEN)},
        RelationshipType.CARRIES: {
            (NodeType.TICK_VECTOR, NodeType.PATHOGEN),
            (NodeType.HOST, NodeType.PATHOGEN),
        },
        RelationshipType.INFECTS: {
            (NodeType.PATHOGEN, NodeType.HOST),
            (NodeType.PATHOGEN, NodeType.STUDY_POPULATION),
        },
        RelationshipType.RESERVOIR_FOR: {(NodeType.HOST, NodeType.PATHOGEN)},
        RelationshipType.EXPOSES_TO: {
            (source, target)
            for source in (
                NodeType.EXPOSURE,
                NodeType.ENVIRONMENTAL_FACTOR,
                NodeType.TICK_VECTOR,
            )
            for target in (
                NodeType.STUDY_POPULATION,
                NodeType.HOST,
                NodeType.DISEASE_CONDITION,
            )
        },
        RelationshipType.PREVENTS: {
            (NodeType.INTERVENTION, NodeType.DISEASE_CONDITION),
            (NodeType.INTERVENTION, NodeType.OUTCOME),
        },
        RelationshipType.TREATS: {
            (NodeType.INTERVENTION, NodeType.DISEASE_CONDITION),
            (NodeType.INTERVENTION, NodeType.OUTCOME),
        },
        RelationshipType.DIAGNOSES: {
            (NodeType.DIAGNOSTIC, NodeType.DISEASE_CONDITION),
            (NodeType.DIAGNOSTIC, NodeType.PATHOGEN),
        },
        RelationshipType.HAS_OUTCOME: {
            (source, NodeType.OUTCOME)
            for source in (
                NodeType.DISEASE_CONDITION,
                NodeType.EXPOSURE,
                NodeType.INTERVENTION,
            )
        },
        RelationshipType.OCCURS_IN: {
            (source, NodeType.PLACE) for source in knowledge_entities - {NodeType.PLACE}
        },
        RelationshipType.INFLUENCES: {
            (source, target)
            for source in (NodeType.ENVIRONMENTAL_FACTOR, NodeType.EXPOSURE)
            for target in knowledge_entities - {NodeType.ENVIRONMENTAL_FACTOR, NodeType.EXPOSURE}
        },
        RelationshipType.EVALUATES: {
            (source, target)
            for source in (NodeType.INTERVENTION, NodeType.DIAGNOSTIC, NodeType.EXPOSURE)
            for target in (NodeType.OUTCOME, NodeType.DISEASE_CONDITION)
        },
    }
    for relationship, pairs in summaries.items():
        if pairs != expected[relationship]:
            drift.append(f"{relationship.value} prompt summary drifted from contract")
    if len(_ENDPOINT_MATRIX_LINES) != len(RelationshipType):
        drift.append("endpoint matrix line count does not match RelationshipType")
    return drift


def dropped_edge_summary(diagnostics: tuple[RedactedEdgeDiagnostic, ...]) -> dict[str, Any]:
    """Compact, log/OTEL-safe summary of dropped edges."""
    by_reason: dict[str, int] = {}
    by_relationship: dict[str, int] = {}
    for item in diagnostics:
        if item.diagnostic_type != "dropped_illegal_edge":
            continue
        by_reason[item.reason] = by_reason.get(item.reason, 0) + 1
        key = item.relationship_type or "unknown"
        by_relationship[key] = by_relationship.get(key, 0) + 1
    return {
        "dropped_edge_count": sum(
            1 for item in diagnostics if item.diagnostic_type == "dropped_illegal_edge"
        ),
        "dropped_by_reason": by_reason,
        "dropped_by_relationship_type": by_relationship,
        "edges": [item.as_ledger_payload() for item in diagnostics],
    }
