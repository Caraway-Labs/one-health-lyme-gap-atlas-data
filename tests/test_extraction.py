from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

import pytest
from lyme_gap_atlas_kg import GraphContribution, PaperNode

from lyme_gap_atlas_data import extraction
from lyme_gap_atlas_data.extraction import ExtractionCoordinator, GroqStructuredExtractor
from lyme_gap_atlas_data.literature import GROQ_MAX_INPUT_TOKENS


class FakeExtractor:
    def __init__(self) -> None:
        self.called = False

    def extract(self, full_request: str, schema: dict[str, object]) -> dict[str, object]:
        self.called = True
        assert schema["additionalProperties"] is False
        return {"configuration_version": "kg-v1.0.0", "paper": {}}


class FakeBudget:
    def __init__(self, *, allow: bool = True) -> None:
        self.allow = allow
        self.finalizations: list[tuple[str, str, float | None]] = []

    def reserve(self, request_id: str, route: str, estimated_cost_usd: float) -> bool:
        return self.allow

    def finalize(self, request_id: str, status: str, actual_cost_usd: float | None = None) -> None:
        self.finalizations.append((request_id, status, actual_cost_usd))


class FakePublisher:
    def publish(self, contribution: Any) -> dict[str, object]:
        return {"published": True}


class FakeEmbedder:
    def embed(self, summaries: list[str], dimensions: int) -> list[list[float]]:
        return [[0.0] * dimensions for _ in summaries]


def test_large_complete_request_routes_to_luna_before_validation() -> None:
    groq, openai = FakeExtractor(), FakeExtractor()
    coordinator = ExtractionCoordinator(
        groq=groq,
        openai=openai,
        budget=FakeBudget(),
        publisher=FakePublisher(),
        embedder=FakeEmbedder(),
        token_estimator=lambda _: GROQ_MAX_INPUT_TOKENS + 1,
        cost_estimator=lambda _route, _tokens: 1.0,
    )
    with suppress(ValueError):
        coordinator.process("request", "complete request")
    assert openai.called
    assert not groq.called


def test_extract_failure_finalizes_budget_as_failed() -> None:
    class FailingExtractor:
        def extract(self, full_request: str, schema: dict[str, object]) -> dict[str, object]:
            raise RuntimeError("provider rejected")

    budget = FakeBudget()
    coordinator = ExtractionCoordinator(
        groq=FailingExtractor(),
        openai=FakeExtractor(),
        budget=budget,
        publisher=FakePublisher(),
        embedder=FakeEmbedder(),
        token_estimator=lambda _: 1,
        cost_estimator=lambda _route, _tokens: 0.25,
    )
    with pytest.raises(RuntimeError, match="provider rejected"):
        coordinator.build_contribution("request-1", "complete request")
    assert budget.finalizations == [("request-1", "failed", None)]


def test_successful_contribution_finalizes_budget_as_used() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    valid = GraphContribution(
        configuration_version="kg-v1.0.0",
        paper=PaperNode(
            id="paper:1",
            canonical_name="Approved paper",
            created_at=now,
            source_configuration_version="kg-v1.0.0",
            pmid="1",
            pmcid="PMC1",
            title="Approved paper",
            journal="Journal",
            publication_date="2026-01-01",
            publication_types=["Journal Article"],
            language="eng",
            pubmed_url="https://pubmed.ncbi.nlm.nih.gov/1/",
            access_status="open_access",
            content_hash="a" * 64,
            full_text_object_key="dev/pmc_full_text/1.bin",
            query_match_ids=["match-1"],
        ),
        passages=[],
        nodes=[],
        edges=[],
    )

    class ValidExtractor:
        def extract(self, full_request: str, schema: dict[str, object]) -> dict[str, object]:
            return valid.model_dump(mode="json")

    budget = FakeBudget()
    coordinator = ExtractionCoordinator(
        groq=ValidExtractor(),
        openai=FakeExtractor(),
        budget=budget,
        publisher=FakePublisher(),
        embedder=FakeEmbedder(),
        token_estimator=lambda _: 1,
        cost_estimator=lambda _route, _tokens: 0.25,
    )
    contribution = coordinator.build_contribution("request-2", "complete request")
    assert contribution.contribution.paper.pmid == "1"
    assert budget.finalizations == [("request-2", "used", 0.25)]


def test_reservation_refusal_does_not_finalize_budget() -> None:
    budget = FakeBudget(allow=False)
    coordinator = ExtractionCoordinator(
        groq=FakeExtractor(),
        openai=FakeExtractor(),
        budget=budget,
        publisher=FakePublisher(),
        embedder=FakeEmbedder(),
        token_estimator=lambda _: 1,
        cost_estimator=lambda _route, _tokens: 0.25,
    )
    with pytest.raises(RuntimeError, match="budget is unavailable"):
        coordinator.build_contribution("request-3", "complete request")
    assert budget.finalizations == []


def test_groq_strict_schema_requires_defaulted_properties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "{}"}}]}

    def post(*_args: object, **kwargs: object) -> Response:
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(extraction.httpx, "post", post)
    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "required_field": {"type": "string"},
            "defaulted_field": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["required_field"],
        "additionalProperties": False,
    }

    GroqStructuredExtractor("test-key").extract("request", schema)

    payload = captured["json"]
    assert isinstance(payload, dict)
    strict_schema = payload["response_format"]["json_schema"]["schema"]
    assert strict_schema["required"] == ["required_field", "defaulted_field"]
    assert schema["required"] == ["required_field"]


def test_strict_schema_omits_dynamic_identifier_maps_and_removes_defaults() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "external_ids": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "default": {},
            }
        },
        "additionalProperties": False,
    }

    strict_schema = extraction._strict_response_schema(schema)

    assert strict_schema["properties"] == {}
    assert strict_schema["required"] == []
    assert schema["properties"]["external_ids"]["additionalProperties"] == {"type": "string"}


def test_openai_responses_uses_the_closed_strict_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"output": [{"content": [{"type": "output_text", "text": "{}"}]}]}

    def post(*_args: object, **kwargs: object) -> Response:
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(extraction.httpx, "post", post)
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"optional_field": {"type": "string", "default": ""}},
        "additionalProperties": False,
    }
    extraction.OpenAIResponsesExtractor("test-key").extract("request", schema)

    payload = captured["json"]
    assert isinstance(payload, dict)
    strict_schema = payload["text"]["format"]["schema"]
    assert strict_schema["required"] == ["optional_field"]
    assert "default" not in strict_schema["properties"]["optional_field"]
