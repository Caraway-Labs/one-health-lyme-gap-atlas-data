"""Reconstruct bounded PubMed batch progress from existing Snowflake ledgers."""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from collections.abc import Sequence
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect
from opentelemetry import trace

_TRACER = trace.get_tracer("one-health-lyme-gap-atlas-data.literature-status")


def reconcile_inventory(
    expected_pmids: Sequence[str],
    papers: Sequence[dict[str, object]],
) -> dict[str, object]:
    """Reconcile exact membership and exclusive observed status; never attest canary READY."""
    if (
        isinstance(expected_pmids, str)
        or len(expected_pmids) > 400
        or len(set(expected_pmids)) != len(expected_pmids)
        or any(
            not isinstance(pmid, str) or not re.fullmatch(r"[1-9][0-9]{0,8}", pmid)
            for pmid in expected_pmids
        )
    ):
        raise ValueError(
            "authoritative inventory must contain unique canonical PMIDs within the discovery bound"
        )
    expected = set(expected_pmids)
    observed: dict[str, list[dict[str, object]]] = {}
    for paper in papers:
        pmid = paper.get("pmid")
        if not isinstance(pmid, str) or not re.fullmatch(r"[1-9][0-9]{0,8}", pmid):
            raise ValueError("observed inventory contains an invalid PMID")
        observed.setdefault(pmid, []).append(paper)
    missing = sorted(expected - observed.keys())
    unexpected = sorted(observed.keys() - expected)
    duplicate = sorted(
        pmid
        for pmid, rows in observed.items()
        if len(rows) != 1
        or any(paper.get("ledger_paper_records") not in (None, 1) for paper in rows)
    )
    memberships: dict[str, list[str]] = {}
    for pmid in sorted(expected):
        rows = observed.get(pmid, [])
        if not rows:
            status = "missing_ledger"
        elif pmid in duplicate:
            status = "ambiguous_ledger"
        else:
            paper = rows[0]
            state = paper.get("state")
            acquired, published, admitted = (
                bool(paper.get(key)) for key in ("acquired", "graph_published", "corpus_admitted")
            )
            if (
                admitted
                and not published
                or published
                and not acquired
                or state == "processed"
                and not published
            ):
                status = "inconsistent_stage_flags"
            elif state in {"rejected", "access_rejected", "ineligible"}:
                status = "excluded"
            elif state == "retry_exhausted":
                status = "retry_exhausted"
            elif state == "retry_pending":
                status = "retry_pending"
            elif state == "extracting":
                status = "extracting"
            elif published:
                status = (
                    "published_with_corpus_rows" if admitted else "published_without_corpus_rows"
                )
            elif state in {"discovered", "awaiting_review", "deferred"} or not paper.get(
                "reviewed"
            ):
                status = "review_wait"
            elif state in {"approved", "ready_for_extraction"}:
                status = (
                    "acquired_waiting_extraction" if acquired else "approved_waiting_acquisition"
                )
            else:
                status = "unknown_state"
        memberships.setdefault(status, []).append(pmid)
    unresolved = any(key in memberships for key in ("inconsistent_stage_flags", "unknown_state"))
    return {
        "scope": "exact_inventory_and_observed_stage_flags",
        "status": "MISMATCHED" if missing or unexpected or duplicate or unresolved else "MATCHED",
        "expected_count": len(expected),
        "observed_count": len(observed),
        "missing_pmids": missing,
        "unexpected_pmids": unexpected,
        "duplicate_pmids": duplicate,
        "status_counts": {key: len(values) for key, values in memberships.items()},
        "status_pmids": memberships,
        "counted_inventory": sum(len(values) for values in memberships.values()),
        "receipt_lineage": "NOT_CHECKED",
        "serving_visibility": "NOT_CHECKED",
        "ledger_cardinality": "CHECKED"
        if all(paper.get("ledger_paper_records") is not None for paper in papers)
        else "NOT_ATTRIBUTED",
    }


_BATCH_SQL = """
WITH batch AS (
  SELECT DISTINCT m.pmid FROM KNOWLEDGE_GRAPH.PAPER_QUERY_MATCHES m
  WHERE m.discovery_run_id = %s
  UNION
  SELECT p.pmid FROM KNOWLEDGE_GRAPH.PAPERS p
  JOIN KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS d
    ON d.discovery_run_id = %s
   AND ARRAY_CONTAINS(TO_VARIANT(p.pmid), d.request_evidence:pmids)
), paper_cardinality AS (
  SELECT p.pmid, COUNT(*) AS records
  FROM KNOWLEDGE_GRAPH.PAPERS p JOIN batch b ON b.pmid = p.pmid
  GROUP BY p.pmid
), latest_attempt AS (
  SELECT a.pmid, a.extraction_attempt_id, a.status, a.error_class,
         a.attempt_number, COALESCE(a.finished_at, a.started_at) AS evidence_at,
         c.details:run_id::STRING AS correlation_id,
         c.details:workflow_run_id::STRING AS workflow_run_id,
         c.details:environment::STRING AS environment,
         c.details:code_sha::STRING AS code_sha,
         c.details:image_sha::STRING AS image_sha,
         c.details:trace_id::STRING AS trace_id
  FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS a
  JOIN batch b ON b.pmid = a.pmid
  LEFT JOIN KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS c
    ON c.extraction_attempt_id = a.extraction_attempt_id
   AND c.diagnostic_type = 'attempt_context'
  WHERE c.extraction_attempt_id IS NULL
     OR c.details:discovery_run_id::STRING = %s
), latest_failure AS (
  SELECT d.extraction_attempt_id, d.details
  FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS d
  JOIN latest_attempt a ON a.extraction_attempt_id = d.extraction_attempt_id
  WHERE d.diagnostic_type = 'stage_failure'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY d.extraction_attempt_id
    ORDER BY d.diagnostic_id DESC) = 1
), latest_paper_failure AS (
  SELECT e.pmid, e.reason, e.correlation_id, e.occurred_at
  FROM KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS e
  JOIN batch b ON b.pmid = e.pmid
  WHERE e.reason LIKE 'stage_failure:%'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY e.pmid
    ORDER BY e.occurred_at DESC, e.paper_state_event_id DESC) = 1
)
SELECT p.pmid, p.pmcid, p.state, p.final_review_decision_id,
       a.extraction_attempt_id, a.status, a.error_class, a.attempt_number,
       COALESCE(d.details:failure_category::STRING,
         IFF(a.extraction_attempt_id IS NULL AND p.state IN ('retry_pending','retry_exhausted'),
             SPLIT_PART(e.reason, ':', 3), NULL)),
       COALESCE(d.details:retryable::BOOLEAN,
         IFF(a.extraction_attempt_id IS NULL AND p.state IN ('retry_pending','retry_exhausted'),
             SPLIT_PART(e.reason, ':', 4) = 'true', NULL)),
       COALESCE(d.details:next_action::STRING,
         IFF(a.extraction_attempt_id IS NULL AND p.state IN ('retry_pending','retry_exhausted'),
             SPLIT_PART(e.reason, ':', 5), NULL)),
       COALESCE(d.details:stage::STRING,
         IFF(a.extraction_attempt_id IS NULL AND p.state IN ('retry_pending','retry_exhausted'),
             SPLIT_PART(e.reason, ':', 2), NULL)),
       d.details:provider_rationale::STRING,
       COALESCE(a.correlation_id,e.correlation_id), a.workflow_run_id,
       a.environment, a.code_sha, a.image_sha,
       f.pmid IS NOT NULL, r.pmid IS NOT NULL, u.pmid IS NOT NULL,
       e.reason, e.correlation_id, e.occurred_at, a.evidence_at, a.trace_id, pc.records
FROM batch b
JOIN KNOWLEDGE_GRAPH.PAPERS p ON p.pmid = b.pmid
JOIN paper_cardinality pc ON pc.pmid = p.pmid
LEFT JOIN latest_attempt a ON a.pmid = p.pmid
LEFT JOIN latest_failure d ON d.extraction_attempt_id = a.extraction_attempt_id
LEFT JOIN latest_paper_failure e ON e.pmid = p.pmid
LEFT JOIN (SELECT DISTINCT pmid FROM KNOWLEDGE_GRAPH.PMC_FULL_TEXT_ARTIFACTS) f
  ON f.pmid = p.pmid
LEFT JOIN (SELECT DISTINCT pmid FROM KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS) r
  ON r.pmid = p.pmid
LEFT JOIN (SELECT DISTINCT pmid FROM KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_UNITS) u
  ON u.pmid = p.pmid
ORDER BY p.pmid, a.attempt_number DESC NULLS LAST, a.extraction_attempt_id DESC
"""


def _paper_status(row: tuple[Any, ...], *, include_latest_event: bool = False) -> dict[str, object]:
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
    ) = row[:21]
    trace_id = str(row[25]) if len(row) > 25 and row[25] else None
    if trace_id and (not re.fullmatch(r"[0-9a-f]{32}", trace_id) or int(trace_id, 16) == 0):
        trace_id = None
    if include_latest_event and len(row) >= 25:
        event_reason, event_run_id, event_at, attempt_at = row[21:25]
        if (
            state in {"retry_pending", "retry_exhausted"}
            and event_reason
            and event_at is not None
            and (attempt_at is None or event_at > attempt_at)
            and (not attempt_id or event_run_id != correlation_id)
        ):
            _, failure_stage, category, retry_text, action = str(event_reason).split(":", 4)
            retryable = retry_text == "true"
            correlation_id = event_run_id
            # The latest failed run did not create this historical attempt.
            provider_rationale = error_class = workflow_run_id = None
            environment = code_sha = image_sha = None
            trace_id = None
    if attempt_status == "failed" and not category:
        category, retryable, action = "legacy_unclassified", False, "inspect_attempt_ledger"
    if not action:
        if state in {"rejected", "ineligible", "access_rejected"}:
            action = "return_to_steward_review"
        elif published and not admitted:
            action = "run_or_inspect_corpus_rebuild"
        elif not review_id:
            action = "await_steward_review"
        elif not attempt_id:
            action = "run_pmc_extraction"
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
        "trace_id": trace_id,
        "workflow_run_id": str(workflow_run_id) if workflow_run_id else None,
        "environment": str(environment) if environment else None,
        "code_sha": str(code_sha) if code_sha else None,
        "image_sha": str(image_sha) if image_sha else None,
        "error_class": str(error_class) if error_class else None,
        "retryable": bool(retryable) if category else None,
        "next_action": str(action) if action else None,
        "ledger_paper_records": int(row[26]) if len(row) > 26 and row[26] is not None else None,
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
                "SELECT status, result_count, request_evidence:pmids "
                "FROM KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS "
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
                cursor.execute(_BATCH_SQL, (run_id, run_id, run_id))
                rows = cursor.fetchall()
                cursor.execute(
                    "SELECT build_id, status, redacted_error FROM "
                    "KNOWLEDGE_GRAPH.RETRIEVAL_CORPUS_BUILDS WHERE discovery_run_id = %s "
                    "ORDER BY started_at, build_id LIMIT 400",
                    (run_id,),
                )
                corpus_builds = [
                    {
                        "build_id": str(row[0]),
                        "correlation_id": str(row[0]),
                        "status": str(row[1]),
                        "failure_category": "corpus_admission_rebuild"
                        if row[1] == "failed"
                        else None,
                        "retryable": True if row[1] == "failed" else None,
                        "next_action": "inspect_corpus_build_and_retry"
                        if row[1] == "failed"
                        else None,
                    }
                    for row in cursor.fetchall()
                ]
    history_rows = [_paper_status(tuple(row)) for row in rows]
    current_rows = [_paper_status(tuple(row), include_latest_event=True) for row in rows]
    papers = list({str(paper["pmid"]): paper for paper in reversed(current_rows)}.values())
    papers.sort(key=lambda paper: str(paper["pmid"]))
    attempt_history = [
        {
            key: paper[key]
            for key in (
                "pmid",
                "extraction_attempt_id",
                "attempt_number",
                "attempt_status",
                "failure_stage",
                "failure_category",
                "retryable",
                "next_action",
                "provider_rationale",
                "correlation_id",
                "trace_id",
            )
        }
        for paper in history_rows
        if paper["extraction_attempt_id"]
    ]
    stage_counts = Counter(str(paper["stage"]) for paper in papers)
    failure_counts = Counter(
        str(paper["failure_category"]) for paper in history_rows if paper["failure_category"]
    )
    historical_runs = {paper["correlation_id"] for paper in history_rows}
    failure_counts.update(
        str(paper["failure_category"])
        for paper in papers
        if paper["failure_category"] and paper["correlation_id"] not in historical_runs
    )
    stage_totals = {
        "discovery": {
            "entered": len(papers),
            "succeeded": len(papers),
            "failed": 0 if str(discovery[0]) == "COMPLETED" else 1,
        },
        "review": {
            "entered": len(papers),
            "succeeded": sum(bool(paper["reviewed"]) for paper in papers),
            "failed": 0,
        },
        "acquisition": {
            "entered": sum(bool(paper["reviewed"]) for paper in papers),
            "succeeded": sum(bool(paper["acquired"]) for paper in papers),
            "failed": sum(paper["failure_stage"] == "acquire" for paper in papers),
        },
        "extraction": {
            "entered": len(attempt_history),
            "succeeded": sum(paper["attempt_status"] == "completed" for paper in attempt_history),
            "failed": sum(paper["attempt_status"] == "failed" for paper in attempt_history),
        },
        "graph_publication": {
            "entered": sum(
                paper["attempt_status"] == "completed" or paper["failure_stage"] == "graph_publish"
                for paper in papers
            ),
            "succeeded": sum(bool(paper["graph_published"]) for paper in papers),
            "failed": sum(paper["failure_stage"] == "graph_publish" for paper in papers),
        },
        "corpus_admission": {
            "entered": sum(bool(paper["graph_published"]) for paper in papers),
            "succeeded": sum(bool(paper["corpus_admitted"]) for paper in papers),
            "failed": sum(build["status"] == "failed" for build in corpus_builds),
            "failure_unit": "linked_build",
        },
    }
    inventory: dict[str, object] = {
        "status": "NOT_ATTRIBUTED",
        "scope": "exact_inventory_and_observed_stage_flags",
    }
    authoritative_pmids = discovery[2] if len(discovery) > 2 else None
    if authoritative_pmids is not None:
        try:
            if isinstance(authoritative_pmids, str):
                authoritative_pmids = json.loads(authoritative_pmids)
            if not isinstance(authoritative_pmids, list):
                raise ValueError
            inventory = reconcile_inventory(authoritative_pmids, papers)
        except (ValueError, TypeError):
            inventory = {
                "status": "INVALID_AUTHORITATIVE_INVENTORY",
                "scope": "exact_inventory_and_observed_stage_flags",
            }
    return {
        "discovery_run_id": run_id,
        "discovery_status": str(discovery[0]),
        "provider_result_count": int(discovery[1]) if discovery[1] is not None else None,
        "discovered": len(papers),
        "stage_counts": dict(stage_counts),
        "stage_totals": stage_totals,
        "failure_category_counts": dict(failure_counts),
        "attempt_history": attempt_history,
        "corpus_builds": corpus_builds,
        "historical_unlinked_corpus_builds": "not_attributed",
        "papers": papers,
        "inventory_reconciliation": inventory,
    }
