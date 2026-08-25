from contextlib import suppress
from typing import Any

from lyme_gap_atlas_data.extraction import ExtractionCoordinator


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
