# ruff: noqa: E501  # SQL remains readable as a source-faithful ledger contract.
"""One-paper, steward-gated PMC extraction with immutable provenance."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
from lyme_gap_atlas_kg import GraphContribution
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect
from neo4j import GraphDatabase
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import ValidationError

from .artifacts import Artifact, create_artifact
from .contribution_admission import (
    AdmittedContribution,
    ContributionAdmissionError,
    RedactedEdgeDiagnostic,
    dropped_edge_summary,
    endpoint_matrix_prompt,
)
from .extraction import (
    BudgetUnavailable,
    ExtractionCoordinator,
    GroqStructuredExtractor,
    OpenAIEmbeddingClient,
    OpenAIResponsesExtractor,
)
from .extraction_group import ExtractionGroup, GroupGateBlocked
from .literature_preflight import literature_preflight
from .literature_tracing import trace_fields
from .pmc_graph import (
    AdmittedFullText,
    Neo4jPaperPublisher,
    admit_pmc_open_access,
)
from .pubmed_discovery import _spaces_client

_OAI_ENDPOINT = "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/"
_OAI_HEADERS = {"Accept-Encoding": "gzip, deflate"}
_LOGGER = logging.getLogger(__name__)
_TRACER = trace.get_tracer("one-health-lyme-gap-atlas-data.pmc-extraction")
_RUN_ID: ContextVar[str | None] = ContextVar("pmc_run_id", default=None)
_FAILURE_STAGE: ContextVar[str] = ContextVar("pmc_failure_stage", default="extract")


def _correlation_id() -> str:
    return _RUN_ID.get() or str(uuid.uuid4())


def _bounded_identity(value: str | None, kind: str) -> str:
    """Accept only deployment identifiers, never arbitrary environment content."""
    patterns = {
        "environment": r"dev|prod",
        "code_sha": r"[0-9a-f]{40}",
        "image_sha": r"sha256:[0-9a-f]{64}",
        "workflow_run_id": r"[0-9]{1,20}",
    }
    return value if value and re.fullmatch(patterns[kind], value) else "unknown"


def _failure_outcome(stage: str, error: Exception) -> tuple[str, bool, str]:
    """Classify a failure without serializing exception text or provider bodies."""
    if stage == "governance":
        return "terminal_governance", False, "return_to_steward_review"
    if stage == "claim" or stage == "persist":
        return "runtime_contract", False, "repair_runtime_schema_or_grant"
    if isinstance(error, BudgetUnavailable):
        return "budget_unavailable", False, "check_budget_reservation"
    if stage == "artifact_persist":
        return "artifact_transport", True, "check_artifact_store_then_retry"
    if stage == "acquire":
        if isinstance(error, (httpx.TransportError, httpx.HTTPStatusError)):
            return "artifact_transport", True, "retry_after_pmc_recovery"
        return "artifact_license_identity", False, "review_open_access_and_identity"
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status == 429 or status >= 500:
            return "provider_transient", True, "retry_after_provider_recovery"
        return "provider_rejected_pre_inference", False, "review_provider_contract"
    if isinstance(error, httpx.TransportError):
        return "provider_transport", True, "retry_after_provider_recovery"
    if stage == "validate":
        return "provenance_validation", False, "review_contribution_contract"
    if isinstance(error, (ContributionAdmissionError, ValidationError, json.JSONDecodeError)):
        return "response_contract_validation", False, "review_provider_schema_and_response"
    if stage == "graph_publish":
        return "graph_publication", True, "reconcile_graph_receipt_before_retry"
    return "model_execution", True, "inspect_model_execution_then_retry"


@contextmanager
def _stage(name: str, fields: dict[str, str]) -> Iterator[None]:
    with _TRACER.start_as_current_span(
        f"pmc_extraction.{name}", record_exception=False, set_status_on_exception=False
    ) as span:
        for key, value in fields.items():
            span.set_attribute(f"atlas.{key}", value)
        try:
            yield
        except Exception as error:
            category, retryable, action = _failure_outcome(name, error)
            span.set_attribute("atlas.outcome", "failed")
            span.set_attribute("atlas.failure_category", category)
            span.set_attribute("atlas.retryable", retryable)
            span.set_attribute("atlas.next_action", action)
            span.set_status(Status(StatusCode.ERROR, category))
            _LOGGER.error(
                "pmc.stage %s",
                json.dumps(
                    {
                        **fields,
                        "stage": name,
                        "outcome": "failed",
                        "failure_category": category,
                        "retryable": retryable,
                        "next_action": action,
                    },
                    sort_keys=True,
                ),
            )
            raise
        else:
            span.set_attribute("atlas.outcome", "completed")
            _LOGGER.info(
                "pmc.stage %s",
                json.dumps({**fields, "stage": name, "outcome": "completed"}, sort_keys=True),
            )


def _provider_rejected_before_inference(error: Exception) -> bool:
    """Identify a provider's client-side request rejection without retaining its body."""
    return isinstance(error, httpx.HTTPStatusError) and 400 <= error.response.status_code < 500


def _provider_rejection_rationale(error: httpx.HTTPStatusError) -> str:
    """Retain only bounded machine-readable HTTP diagnostics, never response text."""
    parts = [f"provider_http_{error.response.status_code}"]
    try:
        provider_error = error.response.json().get("error", {})
    except (ValueError, TypeError, AttributeError):
        provider_error = {}
    if isinstance(provider_error, dict):
        for field in ("type", "code", "param"):
            value = provider_error.get(field)
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value):
                parts.append(f"{field}_{value}")
    request_id = error.response.headers.get("x-request-id")
    if request_id and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id):
        parts.append(f"request_id_{request_id}")
    return ":".join(parts)


@dataclass(frozen=True)
class ApprovedPaper:
    """The minimum, citation-only identity required before PMC access."""

    pmid: str
    pmcid: str
    title: str
    journal: str
    publication_date: str
    publication_types: tuple[str, ...]
    language: str
    query_match_ids: tuple[str, ...]
    state: str


class PMCArtifactStore(Protocol):
    def put_object(self, **kwargs: object) -> Any: ...


class PMCExtractionLedger(Protocol):
    def claim_one(self, lease_seconds: int) -> ApprovedPaper | None: ...

    def record_artifact(
        self, paper: ApprovedPaper, artifact: Artifact, admitted: AdmittedFullText
    ) -> str: ...

    def record_attempt(
        self,
        paper: ApprovedPaper,
        request_sha256: str,
        route: str,
        estimated_input_tokens: int,
        lease_seconds: int,
    ) -> str: ...

    def record_diagnostics(
        self,
        paper: ApprovedPaper,
        attempt_id: str,
        diagnostics: Sequence[RedactedEdgeDiagnostic],
        *,
        published: bool = False,
    ) -> None: ...

    def record_receipt(
        self,
        paper: ApprovedPaper,
        attempt_id: str,
        artifact_id: str,
        contribution_sha256: str,
        receipt: dict[str, Any],
    ) -> None: ...

    def finish(self, paper: ApprovedPaper, attempt_id: str) -> None: ...

    def fail(self, paper: ApprovedPaper, attempt_id: str | None, error: Exception) -> None: ...


class ContributionBuilder(Protocol):
    def route_for_request(self, full_request: str) -> str: ...

    def estimate_input_tokens(self, full_request: str) -> int: ...

    def build_contribution(
        self,
        request_id: str,
        full_request: str,
        expected_query_match_ids: tuple[str, ...] | None = None,
    ) -> AdmittedContribution: ...


class JatsFetcher(Protocol):
    def fetch_jats(self, pmcid: str) -> bytes: ...


class PMCOpenAccessClient:
    """Fetch reusable JATS only after the ledger has granted a paper claim."""

    def fetch_jats(self, pmcid: str) -> bytes:
        if not pmcid.startswith("PMC"):
            raise ValueError("PMC identifier is required")
        numeric_pmcid = pmcid.removeprefix("PMC")
        if not numeric_pmcid.isdecimal():
            raise ValueError("PMC identifier is malformed")
        response = httpx.get(
            _OAI_ENDPOINT,
            params={
                "verb": "GetRecord",
                "identifier": f"oai:pubmedcentral.nih.gov:{numeric_pmcid}",
                "metadataPrefix": "pmc",
            },
            headers=_OAI_HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        error = next((node for node in root.iter() if _local_name(node.tag) == "error"), None)
        if error is not None:
            raise ValueError(
                "PMC OAI full text is unavailable"
                + (f": {error.attrib.get('code')}" if error.attrib.get("code") else "")
            )
        article = next((node for node in root.iter() if _local_name(node.tag) == "article"), None)
        if article is None:
            raise ValueError("PMC OAI response has no reusable JATS XML")
        return bytes(ET.tostring(article, encoding="utf-8"))


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def build_extraction_request(
    paper: ApprovedPaper, admitted: AdmittedFullText, artifact: Artifact
) -> str:
    """Build an in-memory, identity-bound request; callers must never log it."""
    identity = {
        "pmid": paper.pmid,
        "pmcid": paper.pmcid,
        "title": paper.title,
        "journal": paper.journal,
        "publication_date": paper.publication_date,
        "publication_types": list(paper.publication_types),
        "language": paper.language,
        "content_hash": admitted.text_sha256,
        "full_text_object_key": artifact.object_key,
        "query_match_ids": list(paper.query_match_ids),
    }
    return (
        "Return only a strict kg-v1.0.0 GraphContribution. The contribution paper must "
        "exactly match this identity, every substantive edge must cite one supplied evidence "
        "passage, and unsupported assertions must be omitted. Do not include any facts not "
        "supported by the full text.\n"
        "Copy query_match_ids from Identity into contribution.paper.query_match_ids "
        "exactly as supplied. They are provenance IDs, not facts to infer from the article.\n"
        "Copy content_hash and full_text_object_key from Identity into the corresponding "
        "contribution.paper fields byte-for-byte. Do not calculate a new hash, hash the "
        "article, shorten the supplied hash, or generate a different object key.\n"
        + endpoint_matrix_prompt()
        + "\nIdentity:\n"
        + json.dumps(identity, sort_keys=True)
        + "\nApproved PMC Open Access full text:\n"
        + admitted.normalized_text
    )


def contribution_sha256(contribution: GraphContribution) -> str:
    return hashlib.sha256(
        json.dumps(
            contribution.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def validate_contribution_identity(
    contribution: GraphContribution,
    paper: ApprovedPaper,
    admitted: AdmittedFullText,
    artifact: Artifact,
) -> None:
    """Reject paper switching, absent passage citations, and incomplete provenance."""
    published = contribution.paper
    mismatches: list[str] = []
    if published.pmid != paper.pmid:
        mismatches.append("pmid")
    if published.pmcid != paper.pmcid:
        mismatches.append("pmcid")
    if published.content_hash != admitted.text_sha256:
        mismatches.append("content_hash")
    if published.full_text_object_key != artifact.object_key:
        mismatches.append("full_text_object_key")
    if sorted(published.query_match_ids) != sorted(paper.query_match_ids):
        mismatches.append("query_match_ids")
    if mismatches:
        raise ContributionIdentityError(
            "model contribution does not match the claimed paper identity",
            tuple(mismatches),
        )
    passage_ids = {passage.id for passage in contribution.passages}
    if not passage_ids or any(
        passage.paper_id != published.id for passage in contribution.passages
    ):
        raise ValueError("every contribution requires a cited passage from the claimed paper")
    if any(
        edge.paper_id != published.id or edge.evidence_passage_id not in passage_ids
        for edge in contribution.edges
    ):
        raise ValueError("every graph edge requires a claimed-paper evidence passage")


class ContributionIdentityError(ValueError):
    """Raised when the model contribution identity fields do not match the claim."""

    def __init__(self, message: str, mismatched_fields: tuple[str, ...]) -> None:
        super().__init__(message)
        self.mismatched_fields = mismatched_fields
        self.diagnostics = (
            RedactedEdgeDiagnostic(
                diagnostic_type="identity_mismatch",
                edge_index=-1,
                edge_id=None,
                relationship_type=None,
                source_node_type=None,
                target_node_type=None,
                assertion_basis=None,
                reason="mismatched_fields=" + ",".join(mismatched_fields),
            ),
        )


class PMCExtractionWorker:
    """Execute at most one approved Open Access extraction; no paper means no network access."""

    def __init__(
        self,
        *,
        ledger: PMCExtractionLedger,
        fetcher: JatsFetcher,
        artifact_store: PMCArtifactStore,
        coordinator: ContributionBuilder,
        publisher: Neo4jPaperPublisher,
        environment: str,
        artifact_bucket: str,
        artifact_prefix: str,
        lease_seconds: int = 900,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if lease_seconds < 60 or lease_seconds > 1_800:
            raise ValueError("lease_seconds must be between 60 and 1800")
        self._ledger = ledger
        self._fetcher = fetcher
        self._artifact_store = artifact_store
        self._coordinator = coordinator
        self._publisher = publisher
        self._environment = environment
        self._artifact_bucket = artifact_bucket
        self._artifact_prefix = artifact_prefix.strip("/")
        self._lease_seconds = lease_seconds
        self._now = now

    def run(self) -> dict[str, object]:
        run_id = str(uuid.uuid4())
        token = _RUN_ID.set(run_id)
        fields = {
            **trace_fields(),
            "run_id": run_id,
            "environment": _bounded_identity(self._environment, "environment"),
            "code_sha": _bounded_identity(
                os.getenv("GITHUB_SHA") or os.getenv("SOURCE_COMMIT"), "code_sha"
            ),
            "image_sha": _bounded_identity(os.getenv("IMAGE_DIGEST"), "image_sha"),
            "workflow_run_id": _bounded_identity(os.getenv("GITHUB_RUN_ID"), "workflow_run_id"),
        }
        discovery_run_id = os.getenv("ATLAS_DISCOVERY_RUN_ID")
        if discovery_run_id:
            fields["discovery_run_id"] = str(uuid.UUID(discovery_run_id))
        try:
            with _stage("claim", fields):
                paper = self._ledger.claim_one(self._lease_seconds)
        finally:
            _RUN_ID.reset(token)
        if paper is None:
            return {"status": "NO_APPROVED_PAPER", "run_id": run_id}
        if (
            paper.state not in {"approved", "retry_pending"}
            or not paper.pmcid
            or not paper.query_match_ids
        ):
            _LOGGER.error(
                "pmc.stage %s",
                json.dumps(
                    {
                        **fields,
                        "pmid": paper.pmid,
                        "stage": "governance",
                        "outcome": "failed",
                        "failure_category": "terminal_governance",
                        "retryable": False,
                        "next_action": "return_to_steward_review",
                    },
                    sort_keys=True,
                ),
            )
            raise ValueError("only an approved, provenance-complete paper may be extracted")
        attempt_id: str | None = None
        built: AdmittedContribution | None = None
        with _TRACER.start_as_current_span(
            "pmc_extraction.run", record_exception=False, set_status_on_exception=False
        ) as span:
            token = _RUN_ID.set(run_id)
            for key, value in fields.items():
                span.set_attribute(f"atlas.{key}", value)
            span.set_attribute("atlas.pmc.pmid", paper.pmid)
            span.set_attribute("atlas.pmc.pmcid", paper.pmcid)
            stage = "acquire"
            try:
                with _stage(stage, {**fields, "pmid": paper.pmid, "pmcid": paper.pmcid}):
                    jats = self._fetcher.fetch_jats(paper.pmcid)
                    admitted = admit_pmc_open_access(jats)
                if admitted.pmcid != paper.pmcid:
                    raise ValueError("PMC JATS identity does not match the claimed paper")
                artifact = create_artifact(
                    payload=jats,
                    environment=self._environment,
                    resource_key=f"{self._artifact_prefix}/pmc_full_text",
                    run_id=paper.pmid,
                )
                stage = "artifact_persist"
                with _stage(stage, {**fields, "pmid": paper.pmid}):
                    self._artifact_store.put_object(
                        Bucket=self._artifact_bucket,
                        Key=artifact.object_key,
                        Body=jats,
                        ContentType="application/xml",
                    )
                stage = "persist"
                with _stage(stage, {**fields, "pmid": paper.pmid}):
                    artifact_id = self._ledger.record_artifact(paper, artifact, admitted)
                request = build_extraction_request(paper, admitted, artifact)
                request_sha = hashlib.sha256(request.encode()).hexdigest()
                stage = "persist"
                with _stage(stage, {**fields, "pmid": paper.pmid}):
                    attempt_id = self._ledger.record_attempt(
                        paper,
                        request_sha,
                        self._coordinator.route_for_request(request),
                        self._coordinator.estimate_input_tokens(request),
                        self._lease_seconds,
                    )
                span.set_attribute("atlas.pmc.extraction_attempt_id", attempt_id)
                stage = "extract"
                with _stage(
                    stage, {**fields, "pmid": paper.pmid, "extraction_attempt_id": attempt_id}
                ):
                    built = self._coordinator.build_contribution(
                        attempt_id, request, paper.query_match_ids
                    )
                contribution = built.contribution
                stage = "validate"
                with _stage(
                    stage, {**fields, "pmid": paper.pmid, "extraction_attempt_id": attempt_id}
                ):
                    validate_contribution_identity(contribution, paper, admitted, artifact)
                stage = "graph_publish"
                with _stage(
                    stage, {**fields, "pmid": paper.pmid, "extraction_attempt_id": attempt_id}
                ):
                    receipt = self._publisher.publish(contribution)
                contribution_sha = contribution_sha256(contribution)
                stage = "persist"
                with _stage(
                    stage, {**fields, "pmid": paper.pmid, "extraction_attempt_id": attempt_id}
                ):
                    self._ledger.record_receipt(
                        paper, attempt_id, artifact_id, contribution_sha, receipt
                    )
                    self._ledger.finish(paper, attempt_id)
                self._emit_admission_diagnostics(
                    paper, attempt_id, built.dropped_edges, span, published=True
                )
                edge_count = receipt["edge_count"]
                passage_count = receipt["passage_count"]
                if not isinstance(edge_count, int) or not isinstance(passage_count, int):
                    raise RuntimeError("graph publication receipt counts are malformed")
                span.set_attribute("atlas.pmc.edge_count", edge_count)
                span.set_attribute("atlas.pmc.passage_count", passage_count)
                span.set_attribute("atlas.pmc.dropped_edge_count", built.dropped_edge_count)
                return {
                    "status": "COMPLETED",
                    "run_id": run_id,
                    "pmid": paper.pmid,
                    "artifact_sha256": artifact.sha256,
                    "contribution_sha256": contribution_sha,
                    "neo4j_transaction_id": receipt["neo4j_transaction_id"],
                    "passage_count": passage_count,
                    "dropped_edge_count": built.dropped_edge_count,
                }
            except Exception as error:
                category, retryable, action = _failure_outcome(stage, error)
                event = {
                    **fields,
                    "pmid": paper.pmid,
                    "pmcid": paper.pmcid,
                    "extraction_attempt_id": attempt_id,
                    "stage": stage,
                    "outcome": "failed",
                    "failure_category": category,
                    "retryable": retryable,
                    "next_action": action,
                }
                if isinstance(error, httpx.HTTPStatusError):
                    event["provider_rationale"] = _provider_rejection_rationale(error)
                _LOGGER.error("pmc.stage %s", json.dumps(event, sort_keys=True))
                span.set_attribute("atlas.failure_category", category)
                span.set_attribute("atlas.retryable", retryable)
                span.set_attribute("atlas.next_action", action)
                diagnostics: Sequence[RedactedEdgeDiagnostic] = ()
                if isinstance(error, (ContributionAdmissionError, ContributionIdentityError)):
                    diagnostics = error.diagnostics
                elif built is not None:
                    diagnostics = built.dropped_edges
                if attempt_id is not None and diagnostics:
                    self._emit_admission_diagnostics(
                        paper, attempt_id, diagnostics, span, published=False
                    )
                span.set_attribute("error.type", type(error).__name__)
                span.set_status(Status(StatusCode.ERROR, _failure_outcome(stage, error)[0]))
                stage_token = _FAILURE_STAGE.set(stage)
                try:
                    self._ledger.fail(paper, attempt_id, error)
                finally:
                    _FAILURE_STAGE.reset(stage_token)
                raise
            finally:
                _RUN_ID.reset(token)

    def _emit_admission_diagnostics(
        self,
        paper: ApprovedPaper,
        attempt_id: str,
        diagnostics: Sequence[RedactedEdgeDiagnostic],
        span: Any,
        *,
        published: bool,
    ) -> None:
        if not diagnostics:
            return
        summary = dropped_edge_summary(tuple(diagnostics))
        self._ledger.record_diagnostics(paper, attempt_id, diagnostics, published=published)
        _LOGGER.info(
            "pmc.extraction.admission_diagnostics pmid=%s attempt_id=%s published=%s "
            "dropped_edge_count=%s dropped_by_reason=%s dropped_by_relationship_type=%s edges=%s",
            paper.pmid,
            attempt_id,
            published,
            summary["dropped_edge_count"],
            json.dumps(summary["dropped_by_reason"], sort_keys=True),
            json.dumps(summary["dropped_by_relationship_type"], sort_keys=True),
            json.dumps(summary["edges"], sort_keys=True),
        )
        span.set_attribute("atlas.pmc.dropped_edge_count", int(summary["dropped_edge_count"]))
        span.set_attribute("atlas.pmc.partial_accept_published", published)
        span.set_attribute(
            "atlas.pmc.dropped_by_reason",
            json.dumps(summary["dropped_by_reason"], sort_keys=True),
        )
        span.set_attribute(
            "atlas.pmc.dropped_by_relationship_type",
            json.dumps(summary["dropped_by_relationship_type"], sort_keys=True),
        )
        span.set_attribute(
            "atlas.pmc.admission_diagnostics",
            json.dumps(summary["edges"], sort_keys=True)[:4_000],
        )


@dataclass
class InMemoryLease:
    """Small deterministic lease helper used by the Snowflake adapter and tests."""

    claimed_at: datetime
    lease_seconds: int

    @property
    def expires_at(self) -> datetime:
        return self.claimed_at + timedelta(seconds=self.lease_seconds)


class SnowflakePMCExtractionLedger:
    """The runtime's narrowly scoped, redacted Snowflake extraction ledger adapter."""

    def __init__(self, *, bucket: str, configuration_version: str = "kg-v1.0.0") -> None:
        self._bucket = bucket
        self._configuration_version = configuration_version
        batch_id = os.getenv("ATLAS_DISCOVERY_RUN_ID")
        manifest = os.getenv("ATLAS_EXTRACTION_GROUP_MANIFEST")
        try:
            self._discovery_run_id = str(uuid.UUID(batch_id)) if batch_id else None
        except ValueError:
            if manifest is not None:
                raise GroupGateBlocked("matching_group_runtime_identity") from None
            raise
        self._group = (
            ExtractionGroup.parse(
                manifest,
                discovery_run_id=self._discovery_run_id,
                image_digest=os.getenv("IMAGE_DIGEST"),
                configuration_version=configuration_version,
            )
            if manifest is not None
            else None
        )
        self._group_readiness_at: str | None = None
        self._group_claimed_pmid: str | None = None

    def _validate_group(self, cursor: Any) -> None:
        if self._group is None:
            return
        cursor.execute(
            """SELECT p.pmid, p.state, p.final_review_decision_id
               FROM KNOWLEDGE_GRAPH.PAPERS p
               WHERE ARRAY_CONTAINS(TO_VARIANT(p.pmid), PARSE_JSON(%s))
                 AND EXISTS (SELECT 1 FROM KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS d
                             WHERE d.discovery_run_id = %s
                               AND ARRAY_CONTAINS(TO_VARIANT(p.pmid), d.request_evidence:pmids))""",
            (json.dumps(self._group.pmids), self._group.discovery_run_id),
        )
        rows = cursor.fetchall()
        if (
            len(rows) != len(self._group.pmids)
            or {str(row[0]) for row in rows} != set(self._group.pmids)
            or any(row[1] not in ("approved", "retry_pending") or not row[2] for row in rows)
        ):
            raise GroupGateBlocked("exact_steward_approved_discovery_inventory")
        cursor.execute(
            """SELECT COUNT(*) FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS
               WHERE diagnostic_type = 'attempt_context'
                 AND details:extraction_group:group_id::STRING = %s""",
            (self._group.group_id,),
        )
        prior = cursor.fetchone()
        if prior is None or prior[0] != 0:
            raise GroupGateBlocked("group_canary_already_attempted_or_unverifiable")

    def validate_group_before_providers(self) -> None:
        """Read authoritative approval/scope/context; never reserve or claim here."""
        if self._group is None:
            return
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            self._validate_group(cursor)
        self._group_readiness_at = datetime.now(UTC).isoformat()

    def claim_one(self, lease_seconds: int) -> ApprovedPaper | None:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            connection.autocommit(False)
            try:
                self._validate_group(cursor)
                if self._group is not None and self._group_readiness_at is None:
                    raise GroupGateBlocked("successful_group_readiness_before_claim")
            except GroupGateBlocked:
                connection.rollback()
                raise
            cursor.execute(
                """SELECT p.pmid, p.pmcid, p.title, COALESCE(p.journal, ''),
                          TO_VARCHAR(p.publication_date), p.publication_types, p.language,
                          ARRAY_AGG(m.query_match_id) WITHIN GROUP (ORDER BY m.query_match_id), p.state
                   FROM KNOWLEDGE_GRAPH.PAPERS p
                   JOIN KNOWLEDGE_GRAPH.PAPER_QUERY_MATCHES m ON m.pmid = p.pmid
                   WHERE p.state IN ('approved', 'retry_pending') AND p.pmcid IS NOT NULL
                     AND (%s IS NULL OR EXISTS (
                       SELECT 1 FROM KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS d
                       WHERE d.discovery_run_id = %s
                         AND ARRAY_CONTAINS(TO_VARIANT(p.pmid), d.request_evidence:pmids)))
                     AND (%s IS NULL OR ARRAY_CONTAINS(TO_VARIANT(p.pmid), PARSE_JSON(%s)))
                     AND NOT EXISTS (SELECT 1 FROM KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS r
                                     WHERE r.pmid = p.pmid)
                     AND (SELECT COUNT(*) FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS a
                          WHERE a.pmid = p.pmid
                            AND a.status = 'failed'
                            AND NOT EXISTS (
                              SELECT 1
                              FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS c
                              WHERE c.extraction_attempt_id = a.extraction_attempt_id
                                AND c.classification IN (
                                  'provider_rejected_pre_inference',
                                  'contract_remediation_reopen'
                                )
                            )) < 3
                   GROUP BY p.pmid, p.pmcid, p.title, p.journal, p.publication_date,
                            p.publication_types, p.language, p.state
                   ORDER BY CASE WHEN p.state = 'retry_pending' THEN 0 ELSE 1 END, p.pmid
                   LIMIT 1""",
                (
                    self._discovery_run_id,
                    self._discovery_run_id,
                    json.dumps(self._group.pmids) if self._group else None,
                    json.dumps(self._group.pmids) if self._group else None,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                connection.rollback()
                return None
            paper = ApprovedPaper(
                pmid=str(row[0]),
                pmcid=str(row[1]),
                title=str(row[2]),
                journal=str(row[3]),
                publication_date=str(row[4]),
                publication_types=tuple(row[5]),
                language=str(row[6]),
                query_match_ids=tuple(row[7]),
                state=str(row[8]),
            )
            if self._group is not None and paper.pmid not in self._group.pmids:
                connection.rollback()
                raise GroupGateBlocked("claimed_paper_in_exact_group_inventory")
            cursor.execute(
                """UPDATE KNOWLEDGE_GRAPH.PAPERS SET state = 'extracting', updated_at = CURRENT_TIMESTAMP()
                   WHERE pmid = %s AND state IN ('approved', 'retry_pending')""",
                (paper.pmid,),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return None
            cursor.execute(
                """INSERT INTO KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS
                   (paper_state_event_id, pmid, from_state, to_state, reason, correlation_id, actor)
                   VALUES (%s, %s, %s, 'extracting', 'pmc_extraction_claim', %s, CURRENT_USER())""",
                (str(uuid.uuid4()), paper.pmid, paper.state, _correlation_id()),
            )
            connection.commit()
            if self._group is not None:
                self._group_claimed_pmid = paper.pmid
            return paper

    def record_artifact(
        self, paper: ApprovedPaper, artifact: Artifact, admitted: AdmittedFullText
    ) -> str:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            artifact_id = str(uuid.uuid4())
            cursor.execute(
                """INSERT INTO GOVERNANCE.RAW_ARTIFACTS
                   (artifact_id, ingestion_run_id, artifact_uri, artifact_type, media_type, byte_count,
                    sha256, created_at)
                   VALUES (%s, %s, %s, 'PMC_JATS_XML', 'application/xml', %s, %s, CURRENT_TIMESTAMP())""",
                (
                    artifact_id,
                    f"pmc:{paper.pmid}",
                    f"s3://{self._bucket}/{artifact.object_key}",
                    artifact.byte_count,
                    artifact.sha256,
                ),
            )
            cursor.execute(
                """MERGE INTO KNOWLEDGE_GRAPH.PMC_FULL_TEXT_ARTIFACTS target USING
                   (SELECT %s pmid, %s pmcid, %s artifact_id, %s object_key, %s license_url,
                           %s jats_sha256, %s text_sha256) source
                   ON target.pmid = source.pmid
                   WHEN NOT MATCHED THEN INSERT (pmid, pmcid, artifact_id, object_key, license_url,
                     jats_sha256, text_sha256) VALUES (source.pmid, source.pmcid, source.artifact_id,
                     source.object_key, source.license_url, source.jats_sha256, source.text_sha256)""",
                (
                    paper.pmid,
                    paper.pmcid,
                    artifact_id,
                    artifact.object_key,
                    admitted.license_url,
                    admitted.jats_sha256,
                    admitted.text_sha256,
                ),
            )
            cursor.execute(
                "SELECT artifact_id FROM KNOWLEDGE_GRAPH.PMC_FULL_TEXT_ARTIFACTS WHERE pmid = %s",
                (paper.pmid,),
            )
            artifact_row = cursor.fetchone()
            if artifact_row is None:
                raise RuntimeError("PMC artifact ledger row was not persisted")
            connection.commit()
            return str(artifact_row[0])

    def record_attempt(
        self,
        paper: ApprovedPaper,
        request_sha256: str,
        route: str,
        estimated_input_tokens: int,
        lease_seconds: int,
    ) -> str:
        if self._group is not None and (
            self._group_readiness_at is None or self._group_claimed_pmid != paper.pmid
        ):
            raise GroupGateBlocked("validated_group_claim_before_attempt")
        attempt_id = str(uuid.uuid4())
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            connection.autocommit(False)
            try:
                self._insert_attempt_and_context(
                    connection,
                    cursor,
                    paper,
                    attempt_id,
                    request_sha256,
                    route,
                    estimated_input_tokens,
                    lease_seconds,
                )
            except Exception:
                connection.rollback()
                raise
        return attempt_id

    def _insert_attempt_and_context(
        self,
        connection: Any,
        cursor: Any,
        paper: ApprovedPaper,
        attempt_id: str,
        request_sha256: str,
        route: str,
        estimated_input_tokens: int,
        lease_seconds: int,
    ) -> None:
        cursor.execute(
            """INSERT INTO KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS
                   (extraction_attempt_id, pmid, attempt_number, provider_route, model_identifier,
                    estimated_input_tokens, request_sha256, status, lease_expires_at, method_version)
                   SELECT %s, %s, COALESCE(MAX(attempt_number), 0) + 1, %s, %s, %s, %s,
                          'reserved', DATEADD(second, %s, CURRENT_TIMESTAMP()), %s
                   FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS WHERE pmid = %s""",
            (
                attempt_id,
                paper.pmid,
                route,
                route,
                estimated_input_tokens,
                request_sha256,
                lease_seconds,
                self._configuration_version,
                paper.pmid,
            ),
        )
        context: dict[str, Any] = {
            **trace_fields(),
            "run_id": _correlation_id(),
            "discovery_run_id": self._discovery_run_id,
            "environment": _bounded_identity(os.getenv("TOPX_ENV"), "environment"),
            "code_sha": _bounded_identity(
                os.getenv("SOURCE_COMMIT") or os.getenv("GITHUB_SHA"), "code_sha"
            ),
            "image_sha": _bounded_identity(os.getenv("IMAGE_DIGEST"), "image_sha"),
            "workflow_run_id": _bounded_identity(os.getenv("GITHUB_RUN_ID"), "workflow_run_id"),
        }
        if self._group is not None:
            context["extraction_group"] = {
                **self._group.context(),
                "readiness_completed_at": self._group_readiness_at,
            }
        cursor.execute(
            """INSERT INTO KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS
                   (diagnostic_id, extraction_attempt_id, pmid, diagnostic_type, details)
                   SELECT %s, %s, %s, 'attempt_context', PARSE_JSON(%s)""",
            (str(uuid.uuid4()), attempt_id, paper.pmid, json.dumps(context, sort_keys=True)),
        )
        connection.commit()

    def record_diagnostics(
        self,
        paper: ApprovedPaper,
        attempt_id: str,
        diagnostics: Sequence[RedactedEdgeDiagnostic],
        *,
        published: bool = False,
    ) -> None:
        if not diagnostics:
            return
        summary = dropped_edge_summary(tuple(diagnostics))
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            for item in diagnostics:
                cursor.execute(
                    """INSERT INTO KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS
                       (diagnostic_id, extraction_attempt_id, pmid, diagnostic_type, details)
                       SELECT %s, %s, %s, %s, PARSE_JSON(%s)""",
                    (
                        str(uuid.uuid4()),
                        attempt_id,
                        paper.pmid,
                        item.diagnostic_type,
                        json.dumps(item.as_ledger_payload(), sort_keys=True),
                    ),
                )
            if published and any(
                item.diagnostic_type == "dropped_illegal_edge" for item in diagnostics
            ):
                cursor.execute(
                    """INSERT INTO KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS
                       (diagnostic_id, extraction_attempt_id, pmid, diagnostic_type, details)
                       SELECT %s, %s, %s, 'partial_accept_summary', PARSE_JSON(%s)""",
                    (
                        str(uuid.uuid4()),
                        attempt_id,
                        paper.pmid,
                        json.dumps(
                            {
                                "dropped_edge_count": summary["dropped_edge_count"],
                                "dropped_by_reason": summary["dropped_by_reason"],
                                "dropped_by_relationship_type": summary[
                                    "dropped_by_relationship_type"
                                ],
                                "kept_after_partial_accept": True,
                            },
                            sort_keys=True,
                        ),
                    ),
                )
            connection.commit()

    def record_receipt(
        self,
        paper: ApprovedPaper,
        attempt_id: str,
        artifact_id: str,
        contribution_sha256: str,
        receipt: dict[str, Any],
    ) -> None:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS
                   (graph_receipt_id, pmid, contribution_sha256, neo4j_transaction_id, node_count,
                    passage_count, edge_count, extraction_attempt_id, artifact_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    str(uuid.uuid4()),
                    paper.pmid,
                    contribution_sha256,
                    receipt["neo4j_transaction_id"],
                    receipt["node_count"],
                    receipt["passage_count"],
                    receipt["edge_count"],
                    attempt_id,
                    artifact_id,
                ),
            )
            connection.commit()

    def finish(self, paper: ApprovedPaper, attempt_id: str) -> None:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS SET status = 'completed', finished_at = CURRENT_TIMESTAMP() WHERE extraction_attempt_id = %s",
                (attempt_id,),
            )
            cursor.execute(
                "UPDATE KNOWLEDGE_GRAPH.PAPERS SET state = 'processed', updated_at = CURRENT_TIMESTAMP() WHERE pmid = %s AND state = 'extracting'",
                (paper.pmid,),
            )
            cursor.execute(
                """INSERT INTO KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS
                   (paper_state_event_id, pmid, from_state, to_state, reason, correlation_id, actor)
                   VALUES (%s, %s, 'extracting', 'processed', 'graph_publication_receipt', %s, CURRENT_USER())""",
                (str(uuid.uuid4()), paper.pmid, _correlation_id()),
            )
            connection.commit()

    def fail(self, paper: ApprovedPaper, attempt_id: str | None, error: Exception) -> None:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            category, retryable, action = _failure_outcome(_FAILURE_STAGE.get(), error)
            provider_rejected = attempt_id is not None and _provider_rejected_before_inference(
                error
            )
            if attempt_id is not None:
                cursor.execute(
                    """UPDATE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS
                       SET status = 'failed', error_class = %s, finished_at = CURRENT_TIMESTAMP()
                       WHERE extraction_attempt_id = %s""",
                    (type(error).__name__, attempt_id),
                )
                details: dict[str, object] = {
                    **trace_fields(),
                    "run_id": _correlation_id(),
                    "stage": _FAILURE_STAGE.get(),
                    "failure_category": category,
                    "retryable": retryable,
                    "next_action": action,
                }
                if isinstance(error, httpx.HTTPStatusError):
                    details["provider_rationale"] = _provider_rejection_rationale(error)
                cursor.execute(
                    """INSERT INTO KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS
                       (diagnostic_id, extraction_attempt_id, pmid, diagnostic_type, details)
                       SELECT %s, %s, %s, 'stage_failure', PARSE_JSON(%s)""",
                    (
                        str(uuid.uuid4()),
                        attempt_id,
                        paper.pmid,
                        json.dumps(details, sort_keys=True),
                    ),
                )
            if provider_rejected and isinstance(error, httpx.HTTPStatusError):
                cursor.execute(
                    """INSERT INTO KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS
                       (classification_id, extraction_attempt_id, pmid, classification, rationale, correlation_id)
                       VALUES (%s, %s, %s, 'provider_rejected_pre_inference', %s, %s)""",
                    (
                        str(uuid.uuid4()),
                        attempt_id,
                        paper.pmid,
                        _provider_rejection_rationale(error),
                        _correlation_id(),
                    ),
                )
            cursor.execute(
                """SELECT COUNT(*) FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS a
                   WHERE a.pmid = %s AND a.status = 'failed' AND NOT EXISTS (
                     SELECT 1 FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS c
                     WHERE c.extraction_attempt_id = a.extraction_attempt_id
                       AND c.classification IN (
                         'provider_rejected_pre_inference',
                         'contract_remediation_reopen'
                       ))""",
                (paper.pmid,),
            )
            count_row = cursor.fetchone()
            if count_row is None:
                raise RuntimeError("extraction-attempt count is unavailable")
            exhausted = int(count_row[0]) >= 3
            target = "retry_exhausted" if exhausted else "retry_pending"
            cursor.execute(
                "UPDATE KNOWLEDGE_GRAPH.PAPERS SET state = %s, updated_at = CURRENT_TIMESTAMP() WHERE pmid = %s",
                (target, paper.pmid),
            )
            cursor.execute(
                """INSERT INTO KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS
                   (paper_state_event_id, pmid, from_state, to_state, reason, correlation_id, actor)
                   VALUES (%s, %s, 'extracting', %s, %s, %s, CURRENT_USER())""",
                (
                    str(uuid.uuid4()),
                    paper.pmid,
                    target,
                    f"stage_failure:{_FAILURE_STAGE.get()}:{category}:{str(retryable).lower()}:{action}",
                    _correlation_id(),
                ),
            )
            connection.commit()


class SnowflakeExtractionBudget:
    """Reserve explicit, operator-supplied maximum cost through the owner-rights budget procedure."""

    def __init__(self, daily_limit_usd: float = 20.0, monthly_limit_usd: float = 300.0) -> None:
        self._daily_limit_usd = daily_limit_usd
        self._monthly_limit_usd = monthly_limit_usd

    def reserve(self, request_id: str, route: str, estimated_cost_usd: float) -> bool:
        provider, model_identifier = route.split(":", maxsplit=1)
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            cursor.execute(
                """CALL GOVERNANCE.SP_RESERVE_KG_LLM_BUDGET(
                   'pmc_extraction', %s, %s, %s, %s, %s, %s)""",
                (
                    request_id,
                    provider,
                    model_identifier,
                    estimated_cost_usd,
                    self._daily_limit_usd,
                    self._monthly_limit_usd,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("budget reservation returned no result")
            result = row[0]
            if isinstance(result, str):
                result = json.loads(result)
            if not isinstance(result, dict) or "allowed" not in result:
                raise RuntimeError("budget reservation returned an invalid result")
            return bool(result["allowed"])

    def finalize(self, request_id: str, status: str, actual_cost_usd: float | None = None) -> None:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            cursor.execute(
                "CALL GOVERNANCE.SP_FINALIZE_KG_LLM_BUDGET(%s,%s,%s,%s)",
                ("pmc_extraction", request_id, status, actual_cost_usd),
            )


class _UnusedCoordinatorPublisher:
    """The worker publishes only after its own identity validation."""

    def publish(self, contribution: GraphContribution) -> dict[str, object]:
        raise RuntimeError("PMC extraction must publish through the guarded worker")


def run_pmc_extraction(*, estimated_cost_usd: float, settings: Any) -> dict[str, object]:
    """Construct the guarded runtime only after a CLI operator gives an explicit cost bound."""
    if not 0.20 <= estimated_cost_usd <= 20:
        raise ValueError(
            "estimated_cost_usd must be at least the $0.20 per-call bound and no more than the daily budget"
        )
    readiness = literature_preflight(settings, operation="extract")
    _LOGGER.info("literature.preflight %s", json.dumps(readiness, sort_keys=True))
    if readiness["status"] != "READY":
        raise RuntimeError("literature preflight blocked extraction before paper claim")
    ledger = SnowflakePMCExtractionLedger(bucket=settings.spaces_bucket)
    ledger.validate_group_before_providers()
    required = {
        "GROQ_API_KEY": settings.groq_api_key,
        "OPENAI_API_KEY": settings.openai_api_key,
        "NEO4J_URI": settings.neo4j_uri,
        "NEO4J_RUNTIME_PASSWORD": settings.neo4j_runtime_password,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError("PMC extraction runtime is not configured: " + ", ".join(missing))
    groq_key = settings.groq_api_key.get_secret_value()
    openai_key = settings.openai_api_key.get_secret_value()
    neo4j_password = settings.neo4j_runtime_password.get_secret_value()
    with GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_runtime_user, neo4j_password)
    ) as driver:
        coordinator = ExtractionCoordinator(
            groq=GroqStructuredExtractor(groq_key),
            openai=OpenAIResponsesExtractor(openai_key),
            budget=SnowflakeExtractionBudget(),
            publisher=_UnusedCoordinatorPublisher(),
            embedder=OpenAIEmbeddingClient(openai_key),
            token_estimator=lambda text: max(1, len(text) // 4),
            cost_estimator=lambda _route, _tokens: estimated_cost_usd,
        )
        worker = PMCExtractionWorker(
            ledger=ledger,
            fetcher=PMCOpenAccessClient(),
            artifact_store=_spaces_client(settings),
            coordinator=coordinator,
            publisher=Neo4jPaperPublisher(driver),
            environment=settings.topx_env,
            artifact_bucket=settings.spaces_bucket,
            artifact_prefix=settings.spaces_prefix,
        )
        return worker.run()
