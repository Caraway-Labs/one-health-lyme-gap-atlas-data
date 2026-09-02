# ruff: noqa: E501  # SQL remains readable as a source-faithful ledger contract.
"""One-paper, steward-gated PMC extraction with immutable provenance."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
from lyme_gap_atlas_kg import GraphContribution
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect
from neo4j import GraphDatabase

from .artifacts import Artifact, create_artifact
from .extraction import (
    ExtractionCoordinator,
    GroqStructuredExtractor,
    OpenAIEmbeddingClient,
    OpenAIResponsesExtractor,
)
from .pmc_graph import (
    AdmittedFullText,
    Neo4jPaperPublisher,
    admit_pmc_open_access,
)
from .pmc_graph import (
    GraphContribution as Neo4jGraphContribution,
)
from .pubmed_discovery import _spaces_client

_OA_ENDPOINT = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"


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

    def build_contribution(self, request_id: str, full_request: str) -> GraphContribution: ...


class JatsFetcher(Protocol):
    def fetch_jats(self, pmcid: str) -> bytes: ...


class PMCOpenAccessClient:
    """Fetch an OA package only after the ledger has granted a paper claim."""

    def fetch_jats(self, pmcid: str) -> bytes:
        if not pmcid.startswith("PMC"):
            raise ValueError("PMC identifier is required")
        manifest = httpx.get(_OA_ENDPOINT, params={"id": pmcid}, timeout=30)
        manifest.raise_for_status()
        root = ET.fromstring(manifest.content)
        links = [node.attrib.get("href", "") for node in root.findall(".//link")]
        package_url = next((link for link in links if link.endswith(".tar.gz")), "")
        if package_url.startswith("ftp://ftp.ncbi.nlm.nih.gov/"):
            package_url = "https://" + package_url.removeprefix("ftp://")
        if not package_url.startswith("https://"):
            raise ValueError("PMC Open Access package is unavailable")
        package = httpx.get(package_url, timeout=120)
        package.raise_for_status()
        with tarfile.open(fileobj=io.BytesIO(package.content), mode="r:gz") as archive:
            member = next(
                (item for item in archive.getmembers() if item.name.endswith(".nxml")), None
            )
            if member is None:
                raise ValueError("PMC Open Access package has no JATS XML")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("PMC JATS XML cannot be read")
            return source.read()


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
        "supported by the full text.\nIdentity:\n"
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
    if (
        published.pmid != paper.pmid
        or published.pmcid != paper.pmcid
        or published.content_hash != admitted.text_sha256
        or published.full_text_object_key != artifact.object_key
        or sorted(published.query_match_ids) != sorted(paper.query_match_ids)
    ):
        raise ValueError("model contribution does not match the claimed paper identity")
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
        paper = self._ledger.claim_one(self._lease_seconds)
        if paper is None:
            return {"status": "NO_APPROVED_PAPER"}
        if (
            paper.state not in {"approved", "retry_pending"}
            or not paper.pmcid
            or not paper.query_match_ids
        ):
            raise ValueError("only an approved, provenance-complete paper may be extracted")
        attempt_id: str | None = None
        try:
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
            self._artifact_store.put_object(
                Bucket=self._artifact_bucket,
                Key=artifact.object_key,
                Body=jats,
                ContentType="application/xml",
            )
            artifact_id = self._ledger.record_artifact(paper, artifact, admitted)
            request = build_extraction_request(paper, admitted, artifact)
            request_sha = hashlib.sha256(request.encode()).hexdigest()
            attempt_id = self._ledger.record_attempt(
                paper,
                request_sha,
                self._coordinator.route_for_request(request),
                self._coordinator.estimate_input_tokens(request),
                self._lease_seconds,
            )
            contribution = self._coordinator.build_contribution(attempt_id, request)
            validate_contribution_identity(contribution, paper, admitted, artifact)
            receipt = self._publisher.publish(
                Neo4jGraphContribution(
                    paper=contribution.paper,
                    nodes=contribution.nodes,
                    passages=contribution.passages,
                    edges=contribution.edges,
                )
            )
            contribution_sha = contribution_sha256(contribution)
            self._ledger.record_receipt(paper, attempt_id, artifact_id, contribution_sha, receipt)
            self._ledger.finish(paper, attempt_id)
            return {
                "status": "COMPLETED",
                "pmid": paper.pmid,
                "artifact_sha256": artifact.sha256,
                "contribution_sha256": contribution_sha,
                "neo4j_transaction_id": receipt["neo4j_transaction_id"],
                "passage_count": receipt["passage_count"],
            }
        except Exception as error:
            self._ledger.fail(paper, attempt_id, error)
            raise


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

    def claim_one(self, lease_seconds: int) -> ApprovedPaper | None:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            connection.autocommit(False)
            cursor.execute(
                """SELECT p.pmid, p.pmcid, p.title, COALESCE(p.journal, ''),
                          TO_VARCHAR(p.publication_date), p.publication_types, p.language,
                          ARRAY_AGG(m.query_match_id) WITHIN GROUP (ORDER BY m.query_match_id), p.state
                   FROM KNOWLEDGE_GRAPH.PAPERS p
                   JOIN KNOWLEDGE_GRAPH.PAPER_QUERY_MATCHES m ON m.pmid = p.pmid
                   WHERE p.state IN ('approved', 'retry_pending') AND p.pmcid IS NOT NULL
                     AND NOT EXISTS (SELECT 1 FROM KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS r
                                     WHERE r.pmid = p.pmid)
                     AND (SELECT COUNT(*) FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS a
                          WHERE a.pmid = p.pmid) < 3
                   GROUP BY p.pmid, p.pmcid, p.title, p.journal, p.publication_date,
                            p.publication_types, p.language, p.state
                   ORDER BY p.pmid LIMIT 1"""
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
                (str(uuid.uuid4()), paper.pmid, paper.state, str(uuid.uuid4())),
            )
            connection.commit()
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
        attempt_id = str(uuid.uuid4())
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
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
            connection.commit()
        return attempt_id

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
                (str(uuid.uuid4()), paper.pmid, str(uuid.uuid4())),
            )
            connection.commit()

    def fail(self, paper: ApprovedPaper, attempt_id: str | None, error: Exception) -> None:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS WHERE pmid = %s",
                (paper.pmid,),
            )
            count_row = cursor.fetchone()
            if count_row is None:
                raise RuntimeError("extraction-attempt count is unavailable")
            exhausted = int(count_row[0]) >= 3
            target = "retry_exhausted" if exhausted else "retry_pending"
            if attempt_id is not None:
                cursor.execute(
                    """UPDATE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS
                       SET status = 'failed', error_class = %s, finished_at = CURRENT_TIMESTAMP()
                       WHERE extraction_attempt_id = %s""",
                    (type(error).__name__, attempt_id),
                )
            cursor.execute(
                "UPDATE KNOWLEDGE_GRAPH.PAPERS SET state = %s, updated_at = CURRENT_TIMESTAMP() WHERE pmid = %s",
                (target, paper.pmid),
            )
            cursor.execute(
                """INSERT INTO KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS
                   (paper_state_event_id, pmid, from_state, to_state, reason, correlation_id, actor)
                   VALUES (%s, %s, 'extracting', %s, %s, %s, CURRENT_USER())""",
                (str(uuid.uuid4()), paper.pmid, target, type(error).__name__, str(uuid.uuid4())),
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


class _UnusedCoordinatorPublisher:
    """The worker publishes only after its own identity validation."""

    def publish(self, contribution: GraphContribution) -> dict[str, object]:
        raise RuntimeError("PMC extraction must publish through the guarded worker")


def run_pmc_extraction(*, estimated_cost_usd: float, settings: Any) -> dict[str, object]:
    """Construct the guarded runtime only after a CLI operator gives an explicit cost bound."""
    if not 0 < estimated_cost_usd <= 20:
        raise ValueError(
            "estimated_cost_usd must be greater than zero and no more than the daily budget"
        )
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
            ledger=SnowflakePMCExtractionLedger(bucket=settings.spaces_bucket),
            fetcher=PMCOpenAccessClient(),
            artifact_store=_spaces_client(settings),
            coordinator=coordinator,
            publisher=Neo4jPaperPublisher(driver),
            environment=settings.topx_env,
            artifact_bucket=settings.spaces_bucket,
            artifact_prefix=settings.spaces_prefix,
        )
        return worker.run()
