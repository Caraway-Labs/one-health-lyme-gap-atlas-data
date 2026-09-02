from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from lyme_gap_atlas_kg import (
    AssertionBasis,
    EvidencePassageNode,
    GraphContribution,
    GraphNode,
    NodeType,
    PaperNode,
    Polarity,
    RelationshipType,
    SemanticEdge,
)

from lyme_gap_atlas_data.pmc_extraction_worker import ApprovedPaper, PMCExtractionWorker

JATS = b"""<article xml:lang="en" xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta>
<article-id pub-id-type="pmc">PMC123</article-id><permissions><license xlink:href="https://creativecommons.org/licenses/by/4.0/"/>
</permissions></article-meta></front>
<body><sec><title>Results</title><p>Approved evidence.</p></sec></body></article>"""
NON_OA_JATS = JATS.replace(
    b"creativecommons.org/licenses/by/4.0", b"example.org/all-rights-reserved"
)


def approved_paper(*, state: str = "approved") -> ApprovedPaper:
    return ApprovedPaper(
        pmid="123",
        pmcid="PMC123",
        title="Approved paper",
        journal="Journal",
        publication_date="2026-01-01",
        publication_types=("Journal Article",),
        language="eng",
        query_match_ids=("match-1",),
        state=state,
    )


class Ledger:
    def __init__(self, paper: ApprovedPaper | None) -> None:
        self.paper = paper
        self.events: list[str] = []

    def claim_one(self, lease_seconds: int) -> ApprovedPaper | None:
        self.events.append(f"claim:{lease_seconds}")
        return self.paper

    def record_artifact(self, paper: ApprovedPaper, artifact: object, admitted: object) -> str:
        self.events.append("artifact")
        return "artifact-1"

    def record_attempt(
        self,
        paper: ApprovedPaper,
        request_sha256: str,
        route: str,
        estimated_input_tokens: int,
        lease_seconds: int,
    ) -> str:
        self.events.append("attempt")
        return "attempt-1"

    def record_receipt(
        self,
        paper: ApprovedPaper,
        attempt_id: str,
        artifact_id: str,
        contribution_sha256: str,
        receipt: dict[str, Any],
    ) -> None:
        self.events.append("receipt")

    def finish(self, paper: ApprovedPaper, attempt_id: str) -> None:
        self.events.append("finish")

    def fail(self, paper: ApprovedPaper, attempt_id: str | None, error: Exception) -> None:
        self.events.append(f"fail:{type(error).__name__}")


class Fetcher:
    def __init__(self, payload: bytes = JATS) -> None:
        self.payload = payload
        self.called = False

    def fetch_jats(self, pmcid: str) -> bytes:
        self.called = True
        assert pmcid == "PMC123"
        return self.payload


class Store:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def put_object(self, **kwargs: object) -> None:
        self.events.append("store")
        assert kwargs["Bucket"] == "private-dev"
        assert kwargs["ContentType"] == "application/xml"


def contribution(*, pmcid: str = "PMC123", with_citation: bool = True) -> GraphContribution:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    paper_id = "paper:123"
    passage = EvidencePassageNode(
        id="passage:1",
        canonical_name="passage",
        created_at=now,
        source_configuration_version="kg-v1.0.0",
        paper_id=paper_id,
        excerpt="Approved evidence.",
        section_label="Results",
        character_start=0,
        character_end=18,
        excerpt_hash="a" * 64,
        extraction_summary="Approved evidence summary.",
    )
    node = GraphNode(
        id="condition:1",
        node_type=NodeType.DISEASE_CONDITION,
        canonical_name="Lyme disease",
        created_at=now,
        source_configuration_version="kg-v1.0.0",
    )
    edge = SemanticEdge(
        id="edge:1",
        relationship_type=RelationshipType.ASSOCIATED_WITH,
        source_node_id=node.id,
        source_node_type=node.node_type,
        target_node_id=node.id,
        target_node_type=node.node_type,
        paper_id=paper_id,
        evidence_passage_id=passage.id,
        assertion_basis=AssertionBasis.EXPLICIT,
        claim_text="The paper reports evidence.",
        polarity=Polarity.SUPPORTS,
        extraction_configuration_version="kg-v1.0.0",
        created_at=now,
    )
    return GraphContribution(
        configuration_version="kg-v1.0.0",
        paper=PaperNode(
            id=paper_id,
            canonical_name="Approved paper",
            created_at=now,
            source_configuration_version="kg-v1.0.0",
            pmid="123",
            pmcid=pmcid,
            title="Approved paper",
            journal="Journal",
            publication_date="2026-01-01",
            publication_types=["Journal Article"],
            language="eng",
            pubmed_url="https://pubmed.ncbi.nlm.nih.gov/123/",
            access_status="open_access",
            content_hash="e" * 64,
            full_text_object_key="dev/pmc_full_text/123/placeholder.bin",
            query_match_ids=["match-1"],
        ),
        passages=[passage] if with_citation else [],
        nodes=[node],
        edges=[edge] if with_citation else [],
    )


class Coordinator:
    def __init__(self, graph: GraphContribution | Exception) -> None:
        self.graph = graph
        self.called = False

    def build_contribution(self, request_id: str, full_request: str) -> GraphContribution:
        self.called = True
        if isinstance(self.graph, Exception):
            raise self.graph
        graph = self.graph.model_copy(deep=True)
        paper = graph.paper.model_copy(
            update={
                "content_hash": __import__("hashlib")
                .sha256(b"Results Approved evidence.")
                .hexdigest(),
                "full_text_object_key": full_request.split('"full_text_object_key": "')[1].split(
                    '"'
                )[0],
            }
        )
        return graph.model_copy(update={"paper": paper})

    def route_for_request(self, full_request: str) -> str:
        return "groq:openai/gpt-oss-120b"

    def estimate_input_tokens(self, full_request: str) -> int:
        return len(full_request) // 4


class Publisher:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.called = False

    def publish(self, graph: GraphContribution) -> dict[str, Any]:
        self.called = True
        self.events.append("publish")
        return {"neo4j_transaction_id": "tx-1", "passage_count": len(graph.passages)}


def worker(
    ledger: Ledger, fetcher: Fetcher, coordinator: Coordinator, publisher: Publisher
) -> PMCExtractionWorker:
    return PMCExtractionWorker(
        ledger=ledger,
        fetcher=fetcher,
        artifact_store=Store(ledger.events),
        coordinator=coordinator,
        publisher=publisher,  # type: ignore[arg-type]
        environment="dev",
        artifact_bucket="private-dev",
        artifact_prefix="dev",
    )


def test_no_approved_paper_does_not_fetch_or_publish() -> None:
    ledger, fetcher = Ledger(None), Fetcher()
    publisher = Publisher(ledger.events)
    result = worker(ledger, fetcher, Coordinator(contribution()), publisher).run()
    assert result == {"status": "NO_APPROVED_PAPER"}
    assert not fetcher.called and not publisher.called


def test_unapproved_paper_is_rejected_before_pmc_access() -> None:
    ledger, fetcher = Ledger(approved_paper(state="awaiting_review")), Fetcher()
    with pytest.raises(ValueError, match="approved"):
        worker(ledger, fetcher, Coordinator(contribution()), Publisher(ledger.events)).run()
    assert not fetcher.called


def test_open_access_failure_never_calls_model_or_publisher() -> None:
    ledger, fetcher = Ledger(approved_paper()), Fetcher(NON_OA_JATS)
    coordinator, publisher = Coordinator(contribution()), Publisher(ledger.events)
    with pytest.raises(ValueError, match="license"):
        worker(ledger, fetcher, coordinator, publisher).run()
    assert not coordinator.called and not publisher.called
    assert ledger.events[-1] == "fail:ValueError"


def test_paper_switching_model_output_is_rejected_before_publication() -> None:
    ledger, fetcher = Ledger(approved_paper()), Fetcher()
    publisher = Publisher(ledger.events)
    with pytest.raises(ValueError, match="identity"):
        worker(ledger, fetcher, Coordinator(contribution(pmcid="PMC999")), publisher).run()
    assert not publisher.called


def test_missing_passage_citation_is_rejected_before_publication() -> None:
    ledger, fetcher = Ledger(approved_paper()), Fetcher()
    publisher = Publisher(ledger.events)
    with pytest.raises(ValueError, match="cited passage"):
        worker(ledger, fetcher, Coordinator(contribution(with_citation=False)), publisher).run()
    assert not publisher.called


def test_exhausted_budget_is_recorded_without_publication() -> None:
    ledger, fetcher = Ledger(approved_paper()), Fetcher()
    publisher = Publisher(ledger.events)
    with pytest.raises(RuntimeError, match="budget"):
        worker(
            ledger,
            fetcher,
            Coordinator(RuntimeError("extraction budget is unavailable")),
            publisher,
        ).run()
    assert not publisher.called
    assert ledger.events[-1] == "fail:RuntimeError"
