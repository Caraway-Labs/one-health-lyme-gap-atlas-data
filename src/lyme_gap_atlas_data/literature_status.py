"""Reconstruct bounded PubMed batch progress from existing Snowflake ledgers."""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect
from opentelemetry import trace

_TRACER = trace.get_tracer("one-health-lyme-gap-atlas-data.literature-status")

_BATCH_SQL = """
WITH batch AS (
  SELECT DISTINCT m.pmid FROM KNOWLEDGE_GRAPH.PAPER_QUERY_MATCHES m
  WHERE m.discovery_run_id = %s
), latest_attempt AS (
  SELECT a.pmid, a.extraction_attempt_id, a.status, a.error_class,
         a.attempt_number, c.details:run_id::STRING AS correlation_id,
         c.details:workflow_run_id::STRING AS workflow_run_id,
         c.details:environment::STRING AS environment,
         c.details:code_sha::STRING AS code_sha,
         c.details:image_sha::STRING AS image_sha
  FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS a
  JOIN batch b ON b.pmid = a.pmid
  LEFT JOIN KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS c
    ON c.extraction_attempt_id = a.extraction_attempt_id
   AND c.diagnostic_type = 'attempt_context'
  WHERE c.extraction_attempt_id IS NULL
     OR c.details:discovery_run_id::STRING = %s
  QUALIFY ROW_NUMBER() OVER (PARTITION BY a.pmid
    ORDER BY a.attempt_number DESC, a.extraction_attempt_id DESC) = 1
), latest_failure AS (
  SELECT d.extraction_attempt_id, d.details
  FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS d
  JOIN latest_attempt a ON a.extraction_attempt_id = d.extraction_attempt_id
  WHERE d.diagnostic_type = 'stage_failure'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY d.extraction_attempt_id
    ORDER BY d.diagnostic_id DESC) = 1
)
SELECT p.pmid, p.pmcid, p.state, p.final_review_decision_id,
       a.extraction_attempt_id, a.status, a.error_class, a.attempt_number,
       d.details:failure_category::STRING, d.details:retryable::BOOLEAN,
       d.details:next_action::STRING, d.details:stage::STRING,
       d.details:provider_rationale::STRING,
       a.correlation_id, a.workflow_run_id, a.environment, a.code_sha, a.image_sha,
       f.pmid IS NOT NULL, r.pmid IS NOT NULL, u.pmid IS NOT NULL
FROM batch b
JOIN KNOWLEDGE_GRAPH.PAPERS p ON p.pmid = b.pmid
LEFT JOIN latest_attempt a ON a.pmid = p.pmid
LEFT JOIN latest_failure d ON d.extraction_attempt_id = a.extraction_attempt_id
LEFT JOIN (SELECT DISTINCT pmid FROM KNOWLEDGE_GRAPH.PMC_FULL_TEXT_ARTIFACTS) f
  ON f.pmid = p.pmid
LEFT JOIN (SELECT DISTINCT pmid FROM KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS) r
  ON r.pmid = p.pmid
LEFT JOIN (SELECT DISTINCT pmid FROM KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS) u
  ON u.pmid = p.pmid
ORDER BY p.pmid
"""


def _paper_status(row: tuple[Any, ...]) -> dict[str, object]:
    (
        pmid,
        pmcid,
        state,
        review_id,
        attempt_id,
        attempt_status,
        error_class,
        attempt_number,
        category,
        retryable,
        action,
        failure_stage,
        provider_rationale,
        correlation_id,
        workflow_run_id,
        environment,
        code_sha,
        image_sha,
        acquired,
        published,
        admitted,
    ) = row
    if attempt_status == "failed" and not category:
        category, retryable, action = "legacy_unclassified", False, "inspect_attempt_ledger"
    stage = (
        "corpus_admit"
        if admitted
        else "graph_publish"
        if published
        else "extract"
        if attempt_id
        else "acquire"
        if review_id
        else "review_wait"
    )
    return {
        "pmid": str(pmid),
        "pmcid": str(pmcid) if pmcid else None,
        "state": str(state),
        "stage": stage,
        "reviewed": bool(review_id),
        "acquired": bool(acquired),
        "graph_published": bool(published),
        "corpus_admitted": bool(admitted),
        "extraction_attempt_id": str(attempt_id) if attempt_id else None,
        "attempt_number": int(attempt_number) if attempt_number is not None else None,
        "attempt_status": str(attempt_status) if attempt_status else None,
        "failure_stage": str(failure_stage) if failure_stage else None,
        "failure_category": str(category) if category else None,
        "provider_rationale": str(provider_rationale) if provider_rationale else None,
        "correlation_id": str(correlation_id) if correlation_id else None,
        "workflow_run_id": str(workflow_run_id) if workflow_run_id else None,
        "environment": str(environment) if environment else None,
        "code_sha": str(code_sha) if code_sha else None,
        "image_sha": str(image_sha) if image_sha else None,
        "error_class": str(error_class) if error_class else None,
        "retryable": bool(retryable) if category else None,
        "next_action": str(action) if action else None,
    }


def literature_status(discovery_run_id: str) -> dict[str, object]:
    """Use the authoritative discovery ID; never scan an unbounded paper queue."""
    try:
        run_id = str(uuid.UUID(discovery_run_id))
    except ValueError as error:
        raise ValueError("discovery_run_id must be a UUID") from error
    with _TRACER.start_as_current_span(
        "literature.reconcile", record_exception=False, set_status_on_exception=False
    ) as span:
        span.set_attribute("atlas.discovery_run_id", run_id)
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, result_count FROM KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS "
                "WHERE discovery_run_id = %s",
                (run_id,),
            )
            discovery = cursor.fetchone()
            if discovery is None:
                raise ValueError("discovery run was not found")
            with _TRACER.start_as_current_span(
                "literature.review_and_receipt_status",
                record_exception=False,
                set_status_on_exception=False,
            ) as lookup:
                lookup.set_attribute("atlas.discovery_run_id", run_id)
                cursor.execute(_BATCH_SQL, (run_id, run_id))
                rows = cursor.fetchall()
    papers = [_paper_status(tuple(row)) for row in rows]
    stage_counts = Counter(str(paper["stage"]) for paper in papers)
    failure_counts = Counter(
        str(paper["failure_category"]) for paper in papers if paper["failure_category"]
    )
    return {
        "discovery_run_id": run_id,
        "discovery_status": str(discovery[0]),
        "provider_result_count": int(discovery[1]),
        "discovered": len(papers),
        "stage_counts": dict(stage_counts),
        "failure_category_counts": dict(failure_counts),
        "papers": papers,
    }
