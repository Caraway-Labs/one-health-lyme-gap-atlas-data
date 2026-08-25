from datetime import UTC, datetime

import pytest

from lyme_gap_atlas_data.literature import (
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
    [(130_000, "groq:openai/gpt-oss-120b"), (130_001, "openai:gpt-5.6-luna")],
)
def test_complete_request_routing(tokens: int, expected: str) -> None:
    assert extraction_provider(tokens) == expected
