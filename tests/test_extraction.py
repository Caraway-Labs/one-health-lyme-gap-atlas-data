from contextlib import suppress
from typing import Any

import pytest

from lyme_gap_atlas_data import extraction
from lyme_gap_atlas_data.extraction import ExtractionCoordinator, GroqStructuredExtractor


class FakeExtractor:
    def __init__(self) -> None:
        self.called = False

    def extract(self, full_request: str, schema: dict[str, object]) -> dict[str, object]:
        self.called = True
        assert schema["additionalProperties"] is False
        return {"configuration_version": "kg-v1.0.0", "paper": {}}


class FakeBudget:
    def reserve(self, request_id: str, route: str, estimated_cost_usd: float) -> bool:
        return True


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
        token_estimator=lambda _: 130_001,
        cost_estimator=lambda _route, _tokens: 1.0,
    )
    with suppress(ValueError):
        coordinator.process("request", "complete request")
    assert openai.called
    assert not groq.called


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


def test_groq_strict_schema_closes_dynamic_maps_and_removes_defaults() -> None:
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

    strict_schema = extraction._groq_strict_schema(schema)

    external_ids = strict_schema["properties"]["external_ids"]
    assert strict_schema["required"] == ["external_ids"]
    assert external_ids["additionalProperties"] is False
    assert "default" not in external_ids
    assert schema["properties"]["external_ids"]["additionalProperties"] == {"type": "string"}
