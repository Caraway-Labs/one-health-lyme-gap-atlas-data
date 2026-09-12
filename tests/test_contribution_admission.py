from __future__ import annotations

import pytest

from lyme_gap_atlas_data.artifacts import Artifact
from lyme_gap_atlas_data.contribution_admission import (
    ContributionAdmissionError,
    admit_graph_contribution,
    endpoint_matrix_matches_contract,
    endpoint_matrix_prompt,
)
from lyme_gap_atlas_data.extraction import ExtractionCoordinator
from lyme_gap_atlas_data.pmc_extraction_worker import (
    ApprovedPaper,
    build_extraction_request,
)
from lyme_gap_atlas_data.pmc_graph import AdmittedFullText


def _paper_payload() -> dict[str, object]:
    return {
        "id": "paper:123",
        "canonical_name": "Approved paper",
        "created_at": "2026-09-02T00:00:00Z",
        "source_configuration_version": "kg-v1.0.0",
        "pmid": "123",
        "pmcid": "PMC123",
        "title": "Approved paper",
        "journal": "Journal",
        "publication_date": "2026-01-01",
        "publication_types": ["Journal Article"],
        "language": "eng",
        "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/123/",
        "access_status": "open_access",
        "content_hash": "a" * 64,
        "full_text_object_key": "dev/pmc_full_text/123.bin",
        "query_match_ids": ["match-1"],
        "node_type": "Paper",
    }


def _passage_payload() -> dict[str, object]:
    return {
        "id": "passage:1",
        "canonical_name": "passage",
        "created_at": "2026-09-02T00:00:00Z",
        "source_configuration_version": "kg-v1.0.0",
        "node_type": "EvidencePassage",
        "paper_id": "paper:123",
        "excerpt": "Approved evidence.",
        "section_label": "Results",
        "character_start": 0,
        "character_end": 18,
        "excerpt_hash": "b" * 64,
        "extraction_summary": "Approved evidence summary.",
    }


def _node_payload(*, node_id: str, node_type: str, name: str) -> dict[str, object]:
    return {
        "id": node_id,
        "node_type": node_type,
        "canonical_name": name,
        "created_at": "2026-09-02T00:00:00Z",
        "source_configuration_version": "kg-v1.0.0",
    }


def _edge_payload(
    *,
    edge_id: str,
    relationship_type: str,
    source_node_id: str,
    source_node_type: str,
    target_node_id: str,
    target_node_type: str,
) -> dict[str, object]:
    return {
        "id": edge_id,
        "relationship_type": relationship_type,
        "source_node_id": source_node_id,
        "source_node_type": source_node_type,
        "target_node_id": target_node_id,
        "target_node_type": target_node_type,
        "paper_id": "paper:123",
        "evidence_passage_id": "passage:1",
        "assertion_basis": "explicit",
        "claim_text": "The paper reports evidence.",
        "polarity": "supports",
        "extraction_configuration_version": "kg-v1.0.0",
        "created_at": "2026-09-02T00:00:00Z",
    }


def test_endpoint_matrix_matches_kg_contract() -> None:
    assert endpoint_matrix_matches_contract() == []


def test_endpoint_matrix_is_embedded_in_extraction_prompt() -> None:
    paper = ApprovedPaper(
        pmid="123",
        pmcid="PMC123",
        title="Approved paper",
        journal="Journal",
        publication_date="2026-01-01",
        publication_types=("Journal Article",),
        language="eng",
        query_match_ids=("match-1",),
        state="approved",
    )
    admitted = AdmittedFullText(
        "PMC123",
        "https://creativecommons.org/licenses/by/4.0/",
        "Approved evidence.",
        "c" * 64,
        "d" * 64,
    )
    artifact = Artifact(
        sha256="e" * 64,
        byte_count=1,
        object_key="dev/pmc_full_text/123.bin",
    )
    request = build_extraction_request(paper, admitted, artifact)
    assert "TRANSMITS: TickVector -> Pathogen" in request
    assert endpoint_matrix_prompt() in request
    assert "claim_text" not in endpoint_matrix_prompt()


def test_partial_accept_keeps_valid_edges_and_drops_illegal_endpoints() -> None:
    pathogen = _node_payload(node_id="pathogen:1", node_type="Pathogen", name="Bb")
    tick = _node_payload(node_id="tick:1", node_type="TickVector", name="Ixodes")
    condition = _node_payload(
        node_id="condition:1", node_type="DiseaseCondition", name="Lyme disease"
    )
    payload = {
        "configuration_version": "kg-v1.0.0",
        "paper": _paper_payload(),
        "passages": [_passage_payload()],
        "nodes": [pathogen, tick, condition],
        "edges": [
            _edge_payload(
                edge_id="edge:good",
                relationship_type="TRANSMITS",
                source_node_id="tick:1",
                source_node_type="TickVector",
                target_node_id="pathogen:1",
                target_node_type="Pathogen",
            ),
            _edge_payload(
                edge_id="edge:bad",
                relationship_type="TRANSMITS",
                source_node_id="pathogen:1",
                source_node_type="Pathogen",
                target_node_id="tick:1",
                target_node_type="TickVector",
            ),
            _edge_payload(
                edge_id="edge:also-bad",
                relationship_type="TRANSMITS",
                source_node_id="condition:1",
                source_node_type="DiseaseCondition",
                target_node_id="pathogen:1",
                target_node_type="Pathogen",
            ),
        ],
    }
    admitted = admit_graph_contribution(payload)
    assert len(admitted.contribution.edges) == 1
    assert admitted.contribution.edges[0].id == "edge:good"
    assert {node.id for node in admitted.contribution.nodes} == {"pathogen:1", "tick:1"}
    assert len(admitted.dropped_edges) == 2
    assert all(item.diagnostic_type == "dropped_illegal_edge" for item in admitted.dropped_edges)
    assert all("claim_text" not in item.as_ledger_payload() for item in admitted.dropped_edges)
    assert "relationship endpoints are not allowed" in admitted.dropped_edges[0].reason


def test_all_illegal_edges_fail_closed_with_diagnostics() -> None:
    payload = {
        "configuration_version": "kg-v1.0.0",
        "paper": _paper_payload(),
        "passages": [_passage_payload()],
        "nodes": [
            _node_payload(node_id="pathogen:1", node_type="Pathogen", name="Bb"),
            _node_payload(node_id="tick:1", node_type="TickVector", name="Ixodes"),
        ],
        "edges": [
            _edge_payload(
                edge_id="edge:bad",
                relationship_type="TRANSMITS",
                source_node_id="pathogen:1",
                source_node_type="Pathogen",
                target_node_id="tick:1",
                target_node_type="TickVector",
            )
        ],
    }
    with pytest.raises(ContributionAdmissionError, match="no valid edges remain") as raised:
        admit_graph_contribution(payload)
    assert len(raised.value.diagnostics) == 1
    assert raised.value.diagnostics[0].relationship_type == "TRANSMITS"
    assert raised.value.diagnostics[0].source_node_type == "Pathogen"
    assert raised.value.diagnostics[0].target_node_type == "TickVector"


def test_coordinator_partial_accept_finalizes_budget_as_used() -> None:
    class Budget:
        def __init__(self) -> None:
            self.finalizations: list[tuple[str, str, float | None]] = []

        def reserve(self, request_id: str, route: str, estimated_cost_usd: float) -> bool:
            return True

        def finalize(
            self, request_id: str, status: str, actual_cost_usd: float | None = None
        ) -> None:
            self.finalizations.append((request_id, status, actual_cost_usd))

    class Extractor:
        def extract(self, full_request: str, schema: dict[str, object]) -> dict[str, object]:
            return {
                "configuration_version": "kg-v1.0.0",
                "paper": _paper_payload(),
                "passages": [_passage_payload()],
                "nodes": [
                    _node_payload(node_id="pathogen:1", node_type="Pathogen", name="Bb"),
                    _node_payload(node_id="tick:1", node_type="TickVector", name="Ixodes"),
                ],
                "edges": [
                    _edge_payload(
                        edge_id="edge:good",
                        relationship_type="TRANSMITS",
                        source_node_id="tick:1",
                        source_node_type="TickVector",
                        target_node_id="pathogen:1",
                        target_node_type="Pathogen",
                    ),
                    _edge_payload(
                        edge_id="edge:bad",
                        relationship_type="TRANSMITS",
                        source_node_id="pathogen:1",
                        source_node_type="Pathogen",
                        target_node_id="tick:1",
                        target_node_type="TickVector",
                    ),
                ],
            }

    class Publisher:
        def publish(self, contribution: object) -> dict[str, object]:
            return {"published": True}

    class Embedder:
        def embed(self, summaries: list[str], dimensions: int) -> list[list[float]]:
            return [[0.0] * dimensions for _ in summaries]

    budget = Budget()
    coordinator = ExtractionCoordinator(
        groq=Extractor(),
        openai=Extractor(),
        budget=budget,
        publisher=Publisher(),
        embedder=Embedder(),
        token_estimator=lambda _: 1,
        cost_estimator=lambda _route, _tokens: 0.25,
    )
    admitted = coordinator.build_contribution("request-partial", "complete request")
    assert len(admitted.contribution.edges) == 1
    assert admitted.dropped_edge_count == 1
    assert budget.finalizations == [("request-partial", "used", 0.25)]
