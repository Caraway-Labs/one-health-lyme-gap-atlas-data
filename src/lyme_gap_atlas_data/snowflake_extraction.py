"""Snowflake claim, budget, retry, and publication receipt ledgers for KG extraction."""

# ruff: noqa: E501

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from .graph_extraction import ApprovedPaper, ExtractionWorkStore
from .pmc_graph import AdmittedFullText
from .pubmed_pipeline import StoredArtifact


class SnowflakeExtractionBudget:
    def __init__(self, settings: SnowflakeSettings) -> None:
        self._settings = settings

    def reserve(self, request_id: str, route: str, estimated_cost_usd: float) -> bool:
        provider, model = route.split(":", maxsplit=1)
        with connect(self._settings) as connection, connection.cursor() as cursor:
            cursor.execute(
                "CALL GOVERNANCE.SP_RESERVE_KG_LLM_BUDGET(%s,%s,%s,%s,%s,%s,%s)",
                ("extraction", request_id, provider, model, estimated_cost_usd, 20, 300),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            payload = row[0] if isinstance(row[0], dict) else json.loads(str(row[0]))
            return bool(payload["allowed"])


class SnowflakeExtractionWorkStore(ExtractionWorkStore):
    def __init__(self, settings: SnowflakeSettings) -> None:
        self._settings = settings

    def claim(self) -> ApprovedPaper | None:
        with connect(self._settings) as connection:
            connection.autocommit(False)
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """SELECT p.pmid, p.pmcid, p.title, COALESCE(p.journal,''),
                                  COALESCE(TO_VARCHAR(p.publication_date),''), p.publication_types,
                                  p.language, p.state, ARRAY_AGG(m.query_match_id)
                           FROM KNOWLEDGE_GRAPH.PAPERS p
                           JOIN KNOWLEDGE_GRAPH.PAPER_QUERY_MATCHES m ON m.pmid=p.pmid
                           WHERE p.state IN ('approved','retry_pending') AND p.pmcid IS NOT NULL
                           GROUP BY p.pmid,p.pmcid,p.title,p.journal,p.publication_date,p.publication_types,p.language,p.state
                           ORDER BY p.publication_date NULLS LAST, p.pmid LIMIT 1"""
                    )
                    row = cursor.fetchone()
                    if row is None:
                        connection.commit()
                        return None
                    pmid = str(row[0])
                    cursor.execute(
                        """UPDATE KNOWLEDGE_GRAPH.PAPERS SET state='extracting', updated_at=%s
                        WHERE pmid=%s AND state IN ('approved','retry_pending')""",
                        (datetime.now(UTC), pmid),
                    )
                    if cursor.rowcount != 1:
                        connection.rollback()
                        return None
                    cursor.execute(
                        """INSERT INTO KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS
                        (paper_state_event_id,pmid,from_state,to_state,reason,correlation_id,actor)
                        VALUES (%s,%s,%s,'extracting','extraction_claim',%s,'pipeline')""",
                        (str(uuid.uuid4()), pmid, str(row[8]), str(uuid.uuid4())),
                    )
                connection.commit()
                return ApprovedPaper(
                    pmid=pmid,
                    pmcid=str(row[1]),
                    title=str(row[2]),
                    journal=str(row[3]),
                    publication_date=str(row[4]),
                    publication_types=tuple(row[5]),
                    language=str(row[6]),
                    query_match_ids=tuple(str(item) for item in row[8]),
                )
            except Exception:
                connection.rollback()
                raise

    def access_rejected(self, paper: ApprovedPaper, reason: str) -> None:
        self._transition(paper, "access_rejected", reason)

    def record_admission(
        self, paper: ApprovedPaper, full_text: AdmittedFullText, artifact: StoredArtifact
    ) -> None:
        with connect(self._settings) as connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO KNOWLEDGE_GRAPH.PMC_FULL_TEXT_ARTIFACTS
                (pmid,pmcid,artifact_id,object_key,license_url,jats_sha256,text_sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    paper.pmid,
                    paper.pmcid,
                    artifact.artifact_id,
                    artifact.object_key,
                    full_text.license_url,
                    full_text.jats_sha256,
                    full_text.text_sha256,
                ),
            )
            cursor.execute(
                """UPDATE KNOWLEDGE_GRAPH.PAPERS
                SET access_status='pmc_open_access', full_text_object_key=%s, content_sha256=%s,
                    updated_at=%s
                WHERE pmid=%s AND state='extracting'""",
                (artifact.object_key, full_text.text_sha256, datetime.now(UTC), paper.pmid),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("paper was not in extracting state")

    def attempt_started(
        self, paper: ApprovedPaper, route: str, estimated_tokens: int, request_sha256: str
    ) -> None:
        provider, model = route.split(":", maxsplit=1)
        with connect(self._settings) as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT COALESCE(MAX(attempt_number), 0) + 1
                FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS WHERE pmid=%s""",
                (paper.pmid,),
            )
            row = cursor.fetchone()
            attempt_number = int(row[0]) if row is not None else 1
            cursor.execute(
                """INSERT INTO KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS
                (extraction_attempt_id,pmid,attempt_number,provider_route,model_identifier,
                 estimated_input_tokens,request_sha256,status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'running')""",
                (
                    str(uuid.uuid4()),
                    paper.pmid,
                    attempt_number,
                    provider,
                    model,
                    estimated_tokens,
                    request_sha256,
                ),
            )

    def attempt_finished(self, paper: ApprovedPaper, status: str, error_class: str | None) -> None:
        if status not in {"completed", "failed"}:
            raise ValueError("unsupported extraction attempt status")
        with connect(self._settings) as connection, connection.cursor() as cursor:
            cursor.execute(
                """UPDATE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS
                SET status=%s, error_class=%s, finished_at=%s
                WHERE pmid=%s AND status='running'
                  AND attempt_number=(SELECT MAX(attempt_number) FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS WHERE pmid=%s)""",
                (status, error_class, datetime.now(UTC), paper.pmid, paper.pmid),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("no running extraction attempt exists")

    def retry(self, paper: ApprovedPaper, reason: str) -> None:
        self._transition(paper, "retry_pending", reason)

    def processed(self, paper: ApprovedPaper, receipt: dict[str, object]) -> None:
        required = {
            "neo4j_transaction_id",
            "node_count",
            "passage_count",
            "edge_count",
            "contribution_sha256",
        }
        if not required.issubset(receipt):
            raise ValueError("graph publisher receipt is incomplete")
        with connect(self._settings) as connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS
                (graph_receipt_id,pmid,contribution_sha256,neo4j_transaction_id,node_count,passage_count,edge_count)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    str(uuid.uuid4()),
                    paper.pmid,
                    receipt["contribution_sha256"],
                    receipt["neo4j_transaction_id"],
                    receipt["node_count"],
                    receipt["passage_count"],
                    receipt["edge_count"],
                ),
            )
        self._transition(paper, "processed", "graph_published")

    def _transition(self, paper: ApprovedPaper, target: str, reason: str) -> None:
        with connect(self._settings) as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE KNOWLEDGE_GRAPH.PAPERS SET state=%s, updated_at=%s WHERE pmid=%s AND state='extracting'",
                (target, datetime.now(UTC), paper.pmid),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("paper was not in extracting state")
            cursor.execute(
                """INSERT INTO KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS
                (paper_state_event_id,pmid,from_state,to_state,reason,correlation_id,actor)
                VALUES (%s,%s,'extracting',%s,%s,%s,'pipeline')""",
                (str(uuid.uuid4()), paper.pmid, target, reason[:500], str(uuid.uuid4())),
            )
