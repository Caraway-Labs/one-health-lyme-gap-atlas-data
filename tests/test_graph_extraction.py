from __future__ import annotations

# ruff: noqa: E501
import json

import pytest
from lyme_gap_atlas_kg import GraphContribution, deterministic_id

from lyme_gap_atlas_data.graph_extraction import (
    ApprovedPaper,
    ApprovedPaperExtractionWorker,
    extraction_request,
    validate_contribution,
)
from lyme_gap_atlas_data.pmc_graph import AdmittedFullText
from lyme_gap_atlas_data.pubmed_pipeline import StoredArtifact


def _paper() -> ApprovedPaper:
    return ApprovedPaper(
        pmid="123",
        pmcid="PMC123",
        title="Paper",
        journal="Journal",
        publication_date="2025-01-01",
        publication_types=("Journal Article",),
        language="eng",
        query_match_ids=("match-1",),
    )


def _full_text() -> AdmittedFullText:
    return AdmittedFullText(
        "PMC123", "https://creativecommons.org/licenses/by/4.0/", "text", "a" * 64, "b" * 64
    )


def _contribution(*, pmid: str = "123") -> GraphContribution:
    paper_id = deterministic_id("paper", pmid)
    return GraphContribution.model_validate(
        {
            "configuration_version": "kg-v1.0.0",
            "paper": {
                "id": paper_id,
                "canonical_name": "Paper",
                "pmid": pmid,
                "pmcid": "PMC123",
                "title": "Paper",
                "journal": "Journal",
                "publication_date": "2025-01-01",
                "publication_types": ["Journal Article"],
                "language": "eng",
                "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/123/",
                "access_status": "pmc_open_access",
                "content_hash": "b" * 64,
                "full_text_object_key": "private/key",
                "query_match_ids": ["match-1"],
                "created_at": "2026-08-27T00:00:00Z",
                "source_configuration_version": "kg-v1.0.0",
            },
            "passages": [],
            "nodes": [],
            "edges": [],
        }
    )


def test_extraction_request_contains_only_reviewed_metadata_and_permitted_text() -> None:
    request = json.loads(extraction_request(_paper(), _full_text(), "private/pmc.xml"))
    assert request["paper"]["pmid"] == "123"
    assert request["paper"]["content_hash"] == "b" * 64
    assert request["full_text"] == "text"


def test_contribution_validation_rejects_a_model_switching_papers() -> None:
    validator = validate_contribution(_paper(), _full_text(), "private/key")
    validator(_contribution())
    with pytest.raises(ValueError, match="does not match"):
        validator(_contribution(pmid="124"))


class _Store:
    def __init__(self) -> None:
        self.events: list[str] = []

    def claim(self) -> ApprovedPaper:
        return _paper()

    def access_rejected(self, paper: ApprovedPaper, reason: str) -> None:
        self.events.append("rejected")

    def record_admission(
        self, paper: ApprovedPaper, full_text: AdmittedFullText, artifact: StoredArtifact
    ) -> None:
        assert artifact.object_key == "private/PMC123.xml"
        self.events.append("admitted")

    def attempt_started(
        self, paper: ApprovedPaper, route: str, estimated_tokens: int, request_sha256: str
    ) -> None:
        self.events.append("attempt-started")

    def attempt_finished(self, paper: ApprovedPaper, status: str, error_class: str | None) -> None:
        self.events.append(f"attempt-{status}")

    def processed(self, paper: ApprovedPaper, receipt: dict[str, object]) -> None:
        self.events.append("processed")

    def retry(self, paper: ApprovedPaper, reason: str) -> None:
        self.events.append("retry")


class _Artifacts:
    def put(self, **kwargs: object) -> StoredArtifact:
        assert kwargs["payload"]
        return StoredArtifact(
            "artifact", "s3://private/PMC123.xml", "private/PMC123.xml", "a" * 64, 12
        )


class _Coordinator:
    def process(
        self, request_id: str, request: str, validator: object, attempt_started: object
    ) -> dict[str, object]:
        assert json.loads(request)["paper"]["full_text_object_key"] == "private/PMC123.xml"
        attempt_started("groq:openai/gpt-oss-120b", 5, "r" * 64)  # type: ignore[operator]
        return {
            "neo4j_transaction_id": "tx",
            "node_count": 1,
            "passage_count": 0,
            "edge_count": 0,
            "contribution_sha256": "c" * 64,
        }


def test_worker_records_admitted_artifact_before_model_processing() -> None:
    jats = b"""<article xml:lang="en" xmlns:xlink="http://www.w3.org/1999/xlink">
      <front><article-meta><article-id pub-id-type="pmc">PMC123</article-id>
      <permissions><license xlink:href="https://creativecommons.org/licenses/by/4.0/" /></permissions></article-meta></front>
      <body><p>Permitted evidence.</p></body></article>"""
    store = _Store()
    worker = ApprovedPaperExtractionWorker(store, lambda _: jats, _Artifacts(), _Coordinator())  # type: ignore[arg-type]
    assert worker.run_once()["status"] == "PROCESSED"
    assert store.events == ["admitted", "attempt-started", "attempt-completed", "processed"]
