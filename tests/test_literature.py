import logging
from datetime import UTC, datetime

import pytest

from lyme_gap_atlas_data.literature import (
    GROQ_MAX_INPUT_TOKENS,
    GROQ_TRANSPORT_SAFE_INPUT_TOKENS,
    EntrezHistoryClient,
    PaperState,
    build_pubmed_query,
    extraction_provider,
    require_transition,
)


def test_query_has_common_limits_and_family_terms() -> None:
    query = build_pubmed_query("vector_host_pathogen", now=datetime(2026, 8, 25, tzinfo=UTC))
    assert '"Lyme Disease"[MeSH Terms]' in query
    assert '"2007/01/01"[Date - Publication]' in query
    assert "English[Language]" in query
    assert "Editorial[Publication Type]" in query
    assert "Ixodes" in query


def test_state_machine_is_forward_only() -> None:
    require_transition(PaperState.DISCOVERED, PaperState.AWAITING_REVIEW)
    require_transition(PaperState.EXTRACTING, PaperState.PROCESSED)
    with pytest.raises(ValueError):
        require_transition(PaperState.PROCESSED, PaperState.EXTRACTING)


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (GROQ_MAX_INPUT_TOKENS, "groq:openai/gpt-oss-120b"),
        (GROQ_MAX_INPUT_TOKENS + 1, "openai:gpt-5.6-luna"),
    ],
)
def test_complete_request_routing(tokens: int, expected: str) -> None:
    assert extraction_provider(tokens) == expected


def test_groq_transport_ceiling_is_below_live_provider_rejections() -> None:
    """A 6,201-token PMC request received a pre-inference Groq HTTP 413."""
    assert GROQ_TRANSPORT_SAFE_INPUT_TOKENS < 6_201
    assert extraction_provider(6_201) == "openai:gpt-5.6-luna"


def test_entrez_client_suppresses_provider_request_urls() -> None:
    EntrezHistoryClient("steward@example.org")
    assert logging.getLogger("httpx").level == logging.WARNING
