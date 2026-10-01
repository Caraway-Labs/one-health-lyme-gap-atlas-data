"""Budgeted, finite-contract extraction coordinator."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx
from lyme_gap_atlas_kg import GraphContribution
from opentelemetry import trace

from .contribution_admission import AdmittedContribution, admit_graph_contribution
from .literature import extraction_provider

_TRACER = trace.get_tracer("one-health-lyme-gap-atlas-data.extraction")
_LOGGER = logging.getLogger(__name__)


class BudgetUnavailable(RuntimeError):
    """A governed budget reservation declined the attempted provider call."""


def _post_provider(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int,
    provider: str,
    model: str,
) -> httpx.Response:
    """Emit bounded metadata only; never serialize request or response content."""
    request_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    schema = (
        payload.get("text", {}).get("format", {}).get("schema")
        if provider == "openai"
        else (payload.get("response_format", {}).get("json_schema", {}).get("schema"))
    )
    schema_hash = (
        hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
        if schema
        else "none"
    )
    started = time.monotonic()
    status: int | None = None
    safe_request_id = ""
    response_bytes: int | None = None
    service_tier = payload.get("service_tier")
    with _TRACER.start_as_current_span(
        "literature.provider_http", record_exception=False, set_status_on_exception=False
    ) as span:
        span.set_attribute("atlas.provider", provider)
        span.set_attribute("atlas.model", model)
        span.set_attribute("atlas.request_bytes", request_bytes)
        span.set_attribute("atlas.schema_sha256", schema_hash)
        if isinstance(service_tier, str):
            span.set_attribute("atlas.service_tier", service_tier)
        try:
            response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
            status = getattr(response, "status_code", None)
            response_headers = getattr(response, "headers", {})
            request_id = response_headers.get("x-request-id", "")
            safe_request_id = request_id if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id) else ""
            content = getattr(response, "content", None)
            response_bytes = len(content) if isinstance(content, bytes) else None
            if status is not None:
                span.set_attribute("http.response.status_code", status)
            if response_bytes is not None:
                span.set_attribute("atlas.response_bytes", response_bytes)
            if safe_request_id:
                span.set_attribute("atlas.provider_request_id", safe_request_id)
            response.raise_for_status()
            outcome = "completed"
            return response
        except Exception:
            outcome = "failed"
            raise
        finally:
            latency_ms = int((time.monotonic() - started) * 1000)
            span.set_attribute("atlas.latency_ms", latency_ms)
            span.set_attribute("atlas.outcome", outcome)
            _LOGGER.info(
                "literature.provider_http %s",
                json.dumps(
                    {
                        "provider": provider,
                        "model": model,
                        "request_bytes": request_bytes,
                        "schema_sha256": schema_hash,
                        "latency_ms": latency_ms,
                        "response_bytes": response_bytes,
                        "http_status": status,
                        "provider_request_id": safe_request_id or None,
                        "service_tier": service_tier if isinstance(service_tier, str) else None,
                        "outcome": outcome,
                    },
                    sort_keys=True,
                ),
            )


class ContractExtractor(Protocol):
    def extract(self, full_request: str, schema: dict[str, object]) -> dict[str, object]: ...


class ExtractionBudget(Protocol):
    def reserve(self, request_id: str, route: str, estimated_cost_usd: float) -> bool: ...

    def finalize(
        self, request_id: str, status: str, actual_cost_usd: float | None = None
    ) -> None: ...


class ContributionPublisher(Protocol):
    def publish(self, contribution: GraphContribution) -> dict[str, object]: ...


class PassageEmbedder(Protocol):
    def embed(self, summaries: list[str], dimensions: int) -> list[list[float]]: ...


def _strict_response_schema(schema: dict[str, object]) -> dict[str, object]:
    """Adapt the validated contract to the providers' closed strict-schema subset.

    This affects only the provider transport schema.  The returned payload is
    still validated against the unmodified :class:`GraphContribution` schema.
    """
    normalized = copy.deepcopy(schema)

    def normalize_node(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                # Arbitrary identifier maps cannot be represented by the
                # providers' closed strict-schema subset.  They are optional
                # metadata in the canonical model, so omit them only from the
                # transport schema; Pydantic restores their empty defaults
                # when validating the response.
                properties.pop("external_ids", None)
                node["required"] = list(properties)
                node["additionalProperties"] = False
            # Pydantic emits open-ended maps for optional identifier metadata.
            # Groq strict mode permits only closed objects; an empty identifier
            # map remains valid and the canonical identity is separately
            # enforced by the guarded worker.
            elif "additionalProperties" in node:
                node["additionalProperties"] = False
            node.pop("default", None)
            for value in node.values():
                normalize_node(value)
        elif isinstance(node, list):
            for item in node:
                normalize_node(item)

    normalize_node(normalized)
    return normalized


class GroqStructuredExtractor:
    def __init__(self, api_key: str) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def extract(self, full_request: str, schema: dict[str, object]) -> dict[str, object]:
        response = _post_provider(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=self._headers,
            payload={
                "model": "openai/gpt-oss-120b",
                "messages": [{"role": "user", "content": full_request}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "graph_contribution",
                        "strict": True,
                        "schema": _strict_response_schema(schema),
                    },
                },
            },
            timeout=120,
            provider="groq",
            model="openai/gpt-oss-120b",
        )
        return dict(json.loads(response.json()["choices"][0]["message"]["content"]))


class OpenAIResponsesExtractor:
    def __init__(self, api_key: str) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def extract(self, full_request: str, schema: dict[str, object]) -> dict[str, object]:
        provider_schema: dict[str, Any] = copy.deepcopy(schema)
        query_ids = (
            provider_schema.get("$defs", {})
            .get("PaperNode", {})
            .get("properties", {})
            .get("query_match_ids")
        )
        if isinstance(query_ids, dict):
            # Keep OpenAI's previously accepted transport schema. The worker
            # still rejects any returned provenance IDs that differ from the
            # approved paper; Groq retains its provider-specific enum.
            query_ids.pop("enum", None)
        payload = {
            "model": "gpt-5.6-luna",
            "service_tier": "default",
            "store": False,
            "reasoning": {"effort": "low"},
            "max_output_tokens": 32_768,
            "input": full_request,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "graph_contribution",
                    "strict": True,
                    "schema": _strict_response_schema(provider_schema),
                }
            },
        }
        # UTF-8 bytes conservatively bound input tokens, including the schema.
        # Reject before the provider call if a paper exceeds the $0.20 bound.
        if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 200_000:
            raise ValueError("OpenAI extraction request exceeds the budgeted input bound")
        response = _post_provider(
            "https://api.openai.com/v1/responses",
            headers=self._headers,
            payload=payload,
            timeout=180,
            provider="openai",
            model="gpt-5.6-luna",
        )
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
        response = _post_provider(
            "https://api.openai.com/v1/embeddings",
            headers=self._headers,
            payload={
                "model": "text-embedding-3-small",
                "input": summaries,
                "dimensions": dimensions,
            },
            timeout=120,
            provider="openai",
            model="text-embedding-3-small",
        )
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
        admitted = self.build_contribution(request_id, full_request)
        return self._publisher.publish(admitted.contribution)

    def route_for_request(self, full_request: str) -> str:
        """Expose the deterministic model route for durable attempt provenance."""
        return extraction_provider(self.estimate_input_tokens(full_request))

    def estimate_input_tokens(self, full_request: str) -> int:
        """Expose the deterministic input estimate used by the budget reservation."""
        return self._tokens(full_request)

    def build_contribution(
        self,
        request_id: str,
        full_request: str,
        expected_query_match_ids: tuple[str, ...] | None = None,
    ) -> AdmittedContribution:
        """Reserve budget and return a partially admitted, embedded contribution."""
        tokens = self.estimate_input_tokens(full_request)
        route = self.route_for_request(full_request)
        estimated_cost = self._cost(route, tokens)
        if not self._budget.reserve(request_id, route, estimated_cost):
            raise BudgetUnavailable("extraction budget is unavailable")
        try:
            # The validated Pydantic schema is passed directly to the provider. The
            # provider adapter must request strict structured output and returns no
            # retained raw response beyond this in-memory object.
            schema = GraphContribution.model_json_schema()
            if expected_query_match_ids is not None:
                # These are catalog provenance identifiers, not model-inferred
                # facts. Constrain the complete array and still validate the
                # returned paper identity before graph publication.
                paper_schema = schema["$defs"]["PaperNode"]["properties"]
                paper_schema["query_match_ids"]["enum"] = [list(expected_query_match_ids)]
            with _TRACER.start_as_current_span(
                "pmc_extraction.provider_request",
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                span.set_attribute("atlas.provider_route", route)
                span.set_attribute("atlas.extraction_attempt_id", request_id)
                span.set_attribute("atlas.estimated_input_tokens", tokens)
                raw = self._providers[route].extract(full_request, schema)
            with _TRACER.start_as_current_span(
                "pmc_extraction.parse_validate",
                record_exception=False,
                set_status_on_exception=False,
            ):
                admitted = admit_graph_contribution(raw)
            contribution = admitted.contribution
            if contribution.passages:
                embeddings = self._embedder.embed(
                    [passage.extraction_summary for passage in contribution.passages], 1_024
                )
                if len(embeddings) != len(contribution.passages) or any(
                    len(embedding) != 1_024 for embedding in embeddings
                ):
                    raise ValueError(
                        "embedding response does not match the 1,024-dimension contract"
                    )
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
                admitted = AdmittedContribution(
                    contribution=contribution, dropped_edges=admitted.dropped_edges
                )
        except Exception:
            self._budget.finalize(request_id, "failed")
            raise
        # Provider charges are not measured by this adapter. The reservation
        # remains the conservative spend bound; never call it an actual cost.
        self._budget.finalize(request_id, "used")
        return admitted

    def publish_contribution(self, contribution: GraphContribution) -> dict[str, object]:
        """Publish a contribution that a workflow has validated against its admission record."""
        return self._publisher.publish(contribution)

    def process_validated(
        self,
        request_id: str,
        full_request: str,
        validate: Callable[[GraphContribution], None],
        attempt_started: Callable[[str, int, str], None],
    ) -> dict[str, object]:
        """Record attempt provenance, validate admission identity, then publish atomically."""
        route = self.route_for_request(full_request)
        attempt_started(route, self.estimate_input_tokens(full_request), request_id)
        admitted = self.build_contribution(request_id, full_request)
        validate(admitted.contribution)
        return self.publish_contribution(admitted.contribution)
