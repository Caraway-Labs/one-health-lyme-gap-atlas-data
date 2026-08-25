"""Governed PubMed/PMC discovery and extraction invariants."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx
from lyme_gap_atlas_kg import CONFIGURATION_VERSION, SemanticEdge, asset_path

COMMON_LYME_CLAUSE = (
    '("Lyme Disease"[MeSH Terms] OR "Lyme disease"[Title/Abstract] '
    'OR "Lyme borreliosis"[Title/Abstract])'
)
EXCLUSIONS = (
    "NOT (Editorial[Publication Type] OR News[Publication Type] "
    "OR Comment[Publication Type] OR Corrected and Republished Article[Publication Type])"
)
_CONFIG = json.loads(asset_path("config", "kg-v1.0.0.json").read_text(encoding="utf-8"))
ALLOWED_PUBLICATION_TYPES = tuple(_CONFIG["corpus"]["allowed_publication_types"])
FAMILY_TERMS: dict[str, str] = {
    family: "(" + " OR ".join(f'"{term}"' for term in terms) + ")"
    for family, terms in _CONFIG["corpus"]["query_families"].items()
}


class PaperState(StrEnum):
    DISCOVERED = "discovered"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    ACCESS_REJECTED = "access_rejected"
    READY_FOR_EXTRACTION = "ready_for_extraction"
    EXTRACTING = "extracting"
    RETRY_PENDING = "retry_pending"
    RETRY_EXHAUSTED = "retry_exhausted"
    PROCESSED = "processed"


LEGAL_TRANSITIONS: dict[PaperState, frozenset[PaperState]] = {
    PaperState.DISCOVERED: frozenset({PaperState.AWAITING_REVIEW, PaperState.APPROVED}),
    PaperState.AWAITING_REVIEW: frozenset(
        {PaperState.APPROVED, PaperState.REJECTED, PaperState.DEFERRED}
    ),
    PaperState.DEFERRED: frozenset({PaperState.APPROVED, PaperState.REJECTED, PaperState.DEFERRED}),
    PaperState.APPROVED: frozenset({PaperState.ACCESS_REJECTED, PaperState.READY_FOR_EXTRACTION}),
    PaperState.READY_FOR_EXTRACTION: frozenset({PaperState.EXTRACTING}),
    PaperState.EXTRACTING: frozenset(
        {PaperState.PROCESSED, PaperState.RETRY_PENDING, PaperState.RETRY_EXHAUSTED}
    ),
    PaperState.RETRY_PENDING: frozenset({PaperState.EXTRACTING, PaperState.RETRY_EXHAUSTED}),
    PaperState.REJECTED: frozenset(),
    PaperState.ACCESS_REJECTED: frozenset(),
    PaperState.RETRY_EXHAUSTED: frozenset(),
    PaperState.PROCESSED: frozenset(),
}


def require_transition(current: PaperState, target: PaperState) -> None:
    if target not in LEGAL_TRANSITIONS[current]:
        raise ValueError(f"illegal paper transition: {current} -> {target}")


def build_pubmed_query(family: str, *, now: datetime | None = None) -> str:
    if family not in FAMILY_TERMS:
        raise ValueError("unknown PubMed family")
    current_year = (now or datetime.now(UTC)).year
    first_year = current_year - 19
    types = " OR ".join(f'"{item}"[Publication Type]' for item in ALLOWED_PUBLICATION_TYPES)
    return (
        f"{COMMON_LYME_CLAUSE} AND {FAMILY_TERMS[family]} "
        f'AND English[Language] AND ("{first_year}/01/01"[Date - Publication] : '
        f'"{current_year}/12/31"[Date - Publication]) AND ({types}) {EXCLUSIONS}'
    )


@dataclass(frozen=True)
class HistoryCursor:
    family: str
    webenv: str
    query_key: str
    count: int
    retstart: int
    batch_size: int = 200


class EntrezHistoryClient:
    """Bounded E-utilities client; cursor persistence is owned by Snowflake."""

    def __init__(self, email: str, api_key: str | None = None) -> None:
        if not email:
            raise ValueError("NCBI email is required")
        self._params = {"tool": "one_health_lyme_gap_atlas", "email": email}
        if api_key:
            self._params["api_key"] = api_key
        self.requests_per_second = 8.0 if api_key else 2.5

    def start(self, family: str) -> HistoryCursor:
        response = httpx.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={
                **self._params,
                "db": "pubmed",
                "term": build_pubmed_query(family),
                "usehistory": "y",
                "retmode": "json",
                "retmax": 0,
                "sort": "pub date",
            },
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()["esearchresult"]
        return HistoryCursor(family, result["webenv"], result["querykey"], int(result["count"]), 0)

    def fetch(self, cursor: HistoryCursor) -> bytes:
        response = httpx.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={
                **self._params,
                "db": "pubmed",
                "WebEnv": cursor.webenv,
                "query_key": cursor.query_key,
                "retstart": cursor.retstart,
                "retmax": cursor.batch_size,
                "retmode": "xml",
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.content


def extraction_provider(estimated_tokens: int) -> str:
    if estimated_tokens <= 0:
        raise ValueError("estimated_tokens must be positive")
    return "groq:openai/gpt-oss-120b" if estimated_tokens <= 130_000 else "openai:gpt-5.6-luna"


def validate_extraction(edges: Iterable[dict[str, Any]]) -> list[SemanticEdge]:
    """Validate finite ontology and support before any graph transaction."""
    validated = [SemanticEdge.model_validate(edge) for edge in edges]
    if any(not edge.paper_id or not edge.evidence_passage_id for edge in validated):
        raise ValueError("every edge requires paper and passage support")
    return validated


def contribution_checksum(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def configuration_version() -> str:
    return CONFIGURATION_VERSION
