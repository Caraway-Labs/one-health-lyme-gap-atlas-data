"""Approved-paper extraction orchestration at the human-review boundary."""

# ruff: noqa: E501

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from lyme_gap_atlas_kg import GraphContribution, deterministic_id

from .extraction import ExtractionCoordinator
from .pmc_graph import AdmittedFullText, admit_pmc_open_access
from .pubmed_pipeline import ArtifactStore, StoredArtifact


@dataclass(frozen=True)
class ApprovedPaper:
    pmid: str
    pmcid: str
    title: str
    journal: str
    publication_date: str
    publication_types: tuple[str, ...]
    language: str
    query_match_ids: tuple[str, ...]


class ExtractionWorkStore(Protocol):
    def claim(self) -> ApprovedPaper | None: ...

    def access_rejected(self, paper: ApprovedPaper, reason: str) -> None: ...

    def record_admission(
        self, paper: ApprovedPaper, full_text: AdmittedFullText, artifact: StoredArtifact
    ) -> None: ...

    def attempt_started(
        self, paper: ApprovedPaper, route: str, estimated_tokens: int, request_sha256: str
    ) -> None: ...

    def attempt_finished(
        self, paper: ApprovedPaper, status: str, error_class: str | None
    ) -> None: ...

    def processed(self, paper: ApprovedPaper, receipt: dict[str, object]) -> None: ...

    def retry(self, paper: ApprovedPaper, reason: str) -> None: ...


def extraction_request(
    paper: ApprovedPaper, full_text: AdmittedFullText, full_text_object_key: str
) -> str:
    """Build the only model input: reviewed metadata plus permitted PMC text."""
    return json.dumps(
        {
            "task": "Extract only passage-backed graph facts using the supplied schema.",
            "paper": {
                "id": deterministic_id("paper", paper.pmid),
                "pmid": paper.pmid,
                "pmcid": paper.pmcid,
                "title": paper.title,
                "journal": paper.journal,
                "publication_date": paper.publication_date,
                "publication_types": paper.publication_types,
                "language": paper.language,
                "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{paper.pmid}/",
                "access_status": "pmc_open_access",
                "content_hash": full_text.text_sha256,
                "full_text_object_key": full_text_object_key,
                "query_match_ids": paper.query_match_ids,
            },
            "full_text": full_text.normalized_text,
        },
        separators=(",", ":"),
    )


def validate_contribution(
    paper: ApprovedPaper, full_text: AdmittedFullText, full_text_object_key: str
) -> Callable[[GraphContribution], None]:
    expected_id = deterministic_id("paper", paper.pmid)

    def validate(contribution: GraphContribution) -> None:
        candidate = contribution.paper
        if (
            candidate.id != expected_id
            or candidate.pmid != paper.pmid
            or candidate.pmcid != paper.pmcid
            or candidate.content_hash != full_text.text_sha256
            or candidate.full_text_object_key != full_text_object_key
            or candidate.access_status != "pmc_open_access"
        ):
            raise ValueError("extraction contribution does not match the approved PMC paper")
        if any(passage.paper_id != expected_id for passage in contribution.passages):
            raise ValueError("extraction passage is linked to the wrong paper")

    return validate


class ApprovedPaperExtractionWorker:
    """Claim one approved paper; never bypass review or publish unverified text."""

    def __init__(
        self,
        store: ExtractionWorkStore,
        fetch_jats: Callable[[str], bytes],
        artifacts: ArtifactStore,
        coordinator: ExtractionCoordinator,
    ) -> None:
        self._store = store
        self._fetch_jats = fetch_jats
        self._artifacts = artifacts
        self._coordinator = coordinator

    def run_once(self) -> dict[str, object]:
        paper = self._store.claim()
        if paper is None:
            return {"status": "IDLE"}
        try:
            jats = self._fetch_jats(paper.pmcid)
            admitted = admit_pmc_open_access(jats)
            artifact = self._artifacts.put(
                resource_key=f"pmc:{paper.pmcid}",
                run_id=str(uuid.uuid4()),
                payload=jats,
                media_type="application/xml",
            )
            self._store.record_admission(paper, admitted, artifact)
        except ValueError as exc:
            self._store.access_rejected(paper, type(exc).__name__)
            return {"pmid": paper.pmid, "status": "ACCESS_REJECTED"}
        except Exception as exc:
            self._store.retry(paper, type(exc).__name__)
            raise
        attempt_is_running = False

        def record_attempt(route: str, tokens: int, request_sha256: str) -> None:
            nonlocal attempt_is_running
            self._store.attempt_started(paper, route, tokens, request_sha256)
            attempt_is_running = True

        try:
            receipt = self._coordinator.process(
                str(uuid.uuid4()),
                extraction_request(paper, admitted, artifact.object_key),
                validate_contribution(paper, admitted, artifact.object_key),
                record_attempt,
            )
            if not attempt_is_running:
                raise RuntimeError("extraction coordinator did not record an attempt")
            self._store.attempt_finished(paper, "completed", None)
            self._store.processed(paper, receipt)
            return {"pmid": paper.pmid, "status": "PROCESSED", **receipt}
        except Exception as exc:
            if attempt_is_running:
                self._store.attempt_finished(paper, "failed", type(exc).__name__)
            self._store.retry(paper, type(exc).__name__)
            raise
