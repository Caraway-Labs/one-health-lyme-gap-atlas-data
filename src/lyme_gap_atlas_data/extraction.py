"""Budgeted, finite-contract extraction coordinator."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol

import httpx
from lyme_gap_atlas_kg import GraphContribution

from .literature import extraction_provider


class ContractExtractor(Protocol):
    def extract(self, full_request: str, schema: dict[str, object]) -> dict[str, object]: ...


class ExtractionBudget(Protocol):
    def reserve(self, request_id: str, route: str, estimated_cost_usd: float) -> bool: ...


class ContributionPublisher(Protocol):
    def publish(self, contribution: GraphContribution) -> dict[str, object]: ...


class PassageEmbedder(Protocol):
    def embed(self, summaries: list[str], dimensions: int) -> list[list[float]]: ...


class GroqStructuredExtractor:
    def __init__(self, api_key: str) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def extract(self, full_request: str, schema: dict[str, object]) -> dict[str, object]:
        response = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=self._headers,
            json={
                "model": "openai/gpt-oss-120b",
                "messages": [{"role": "user", "content": full_request}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "graph_contribution",
                        "strict": True,
                        "schema": schema,
                    },
                },
            },
            timeout=120,
        )
        response.raise_for_status()
        return dict(json.loads(response.json()["choices"][0]["message"]["content"]))


class OpenAIResponsesExtractor:
    def __init__(self, api_key: str) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def extract(self, full_request: str, schema: dict[str, object]) -> dict[str, object]:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers=self._headers,
            json={
                "model": "gpt-5.6-luna",
                "store": False,
                "reasoning": {"effort": "low"},
                "input": full_request,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "graph_contribution",
                        "strict": True,
                        "schema": schema,
                    }
                },
            },
            timeout=180,
        )
        response.raise_for_status()
        payload = response.json()
        text = next(
            content["text"]
            for output in payload["output"]
            for content in output.get("content", [])
            if content.get("type") == "output_text"
        )
        return dict(json.loads(text))


class OpenAIEmbeddingClient:
    def __init__(self, api_key: str) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def embed(self, summaries: list[str], dimensions: int) -> list[list[float]]:
        response = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers=self._headers,
            json={
                "model": "text-embedding-3-small",
                "input": summaries,
                "dimensions": dimensions,
            },
            timeout=120,
        )
        response.raise_for_status()
        return [item["embedding"] for item in response.json()["data"]]


class ExtractionCoordinator:
    """Route a complete request, validate it, then atomically publish it."""

    def __init__(
        self,
        *,
        groq: ContractExtractor,
        openai: ContractExtractor,
        budget: ExtractionBudget,
        publisher: ContributionPublisher,
        embedder: PassageEmbedder,
        token_estimator: Callable[[str], int],
        cost_estimator: Callable[[str, int], float],
    ) -> None:
        self._providers = {
            "groq:openai/gpt-oss-120b": groq,
            "openai:gpt-5.6-luna": openai,
        }
        self._budget = budget
        self._publisher = publisher
        self._embedder = embedder
        self._tokens = token_estimator
        self._cost = cost_estimator

    def process(self, request_id: str, full_request: str) -> dict[str, object]:
        """Build a validated contribution then publish it atomically."""
        contribution = self.build_contribution(request_id, full_request)
        return self._publisher.publish(contribution)

    def route_for_request(self, full_request: str) -> str:
        """Expose the deterministic model route for durable attempt provenance."""
        return extraction_provider(self.estimate_input_tokens(full_request))

    def estimate_input_tokens(self, full_request: str) -> int:
        """Expose the deterministic input estimate used by the budget reservation."""
        return self._tokens(full_request)

    def build_contribution(self, request_id: str, full_request: str) -> GraphContribution:
        """Reserve budget and return a validated, embedded contribution without publishing it."""
        tokens = self.estimate_input_tokens(full_request)
        route = self.route_for_request(full_request)
        if not self._budget.reserve(request_id, route, self._cost(route, tokens)):
            raise RuntimeError("extraction budget is unavailable")
        # The validated Pydantic schema is passed directly to the provider. The
        # provider adapter must request strict structured output and returns no
        # retained raw response beyond this in-memory object.
        schema = GraphContribution.model_json_schema()
        contribution = GraphContribution.model_validate(
            self._providers[route].extract(full_request, schema)
        )
        if contribution.passages:
            embeddings = self._embedder.embed(
                [passage.extraction_summary for passage in contribution.passages], 1_024
            )
            if len(embeddings) != len(contribution.passages) or any(
                len(embedding) != 1_024 for embedding in embeddings
            ):
                raise ValueError("embedding response does not match the 1,024-dimension contract")
            contribution = contribution.model_copy(
                update={
                    "passages": [
                        passage.model_copy(update={"embedding": embedding})
                        for passage, embedding in zip(
                            contribution.passages, embeddings, strict=True
                        )
                    ]
                }
            )
        return contribution
