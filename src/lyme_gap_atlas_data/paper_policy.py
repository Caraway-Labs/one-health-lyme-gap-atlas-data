"""Deterministic query-policy approval of discovered PubMed papers (ADR 0023)."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect
from opentelemetry import trace

from .settings import PipelineSettings

logger = logging.getLogger(__name__)
_TRACER = trace.get_tracer("one-health-lyme-gap-atlas-data.paper-policy")

POLICY_VERSION = "pubmed-query-policy-v1"
POLICY_ACTOR = "policy:pubmed-query-v1"
POLICY_MODE = "query_policy_v1"
_COUNT_KEYS = ("approved_count", "skipped_no_pmcid", "skipped_not_awaiting_review")

_RUN_STATUS_SQL = """SELECT status FROM KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS
WHERE discovery_run_id = %s"""
# Mirrors the eligibility predicate of GOVERNANCE.SP_RECORD_PAPER_POLICY_APPROVAL.
_DRY_RUN_SQL = """SELECT
  COALESCE(COUNT_IF(p.state = 'awaiting_review' AND p.pmcid IS NOT NULL), 0),
  COALESCE(COUNT_IF(p.state = 'awaiting_review' AND p.pmcid IS NULL), 0),
  COALESCE(COUNT_IF(p.state <> 'awaiting_review'), 0)
FROM KNOWLEDGE_GRAPH.PAPERS p
JOIN KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS d
  ON d.discovery_run_id = %s
 AND ARRAY_CONTAINS(TO_VARIANT(p.pmid), d.request_evidence:pmids)"""
_APPROVE_SQL = "CALL GOVERNANCE.SP_RECORD_PAPER_POLICY_APPROVAL(%s, %s, %s)"


def _require_policy_mode(settings: PipelineSettings) -> None:
    if settings.paper_approval_mode != POLICY_MODE:
        raise ValueError(f"PAPER_APPROVAL_MODE={POLICY_MODE} is required for policy approval")


def _run_id(discovery_run_id: str) -> str:
    try:
        return str(uuid.UUID(discovery_run_id))
    except ValueError as error:
        raise ValueError("discovery_run_id must be a UUID") from error


def _counts(values: tuple[Any, ...] | list[Any]) -> dict[str, int]:
    return {key: int(value) for key, value in zip(_COUNT_KEYS, values, strict=True)}


def preview_policy_approval(
    discovery_run_id: str, *, settings: PipelineSettings | None = None
) -> dict[str, object]:
    """Report what the policy would approve, without writing."""
    settings = settings or PipelineSettings()
    _require_policy_mode(settings)
    run_id = _run_id(discovery_run_id)
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        cursor.execute(_RUN_STATUS_SQL, (run_id,))
        run = cursor.fetchone()
        if run is None:
            raise ValueError("discovery run was not found")
        if run[0] != "COMPLETED":
            raise ValueError("discovery run is not COMPLETED")
        cursor.execute(_DRY_RUN_SQL, (run_id,))
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("policy preview returned no result")
    return {
        "discovery_run_id": run_id,
        "policy_version": POLICY_VERSION,
        "dry_run": True,
        **_counts(row),
    }


def approve_by_policy(
    discovery_run_id: str,
    *,
    settings: PipelineSettings | None = None,
    correlation_id: str | None = None,
) -> dict[str, object]:
    """Approve the run's PMCID-bearing, still-awaiting papers through the governed procedure."""
    settings = settings or PipelineSettings()
    _require_policy_mode(settings)
    run_id = _run_id(discovery_run_id)
    correlation = correlation_id or str(uuid.uuid4())
    with _TRACER.start_as_current_span(
        "literature.policy_approval", record_exception=False, set_status_on_exception=False
    ) as span:
        span.set_attribute("atlas.discovery_run_id", run_id)
        span.set_attribute("atlas.policy_version", POLICY_VERSION)
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            cursor.execute(_APPROVE_SQL, (run_id, POLICY_VERSION, correlation))
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError("policy approval returned no result")
        result = row[0]
        if isinstance(result, str):
            result = json.loads(result)
        if not isinstance(result, dict) or not set(_COUNT_KEYS).issubset(result):
            raise RuntimeError("policy approval returned an invalid result")
        counts = {key: int(result[key]) for key in _COUNT_KEYS}
        span.set_attribute("atlas.approved_count", counts["approved_count"])
    logger.info(
        "literature.policy_approval %s",
        json.dumps(
            {
                "discovery_run_id": run_id,
                "policy_version": POLICY_VERSION,
                "correlation_id": correlation,
                **counts,
            },
            sort_keys=True,
        ),
    )
    return {
        "discovery_run_id": run_id,
        "policy_version": POLICY_VERSION,
        "correlation_id": correlation,
        "batch_id": str(result["batch_id"]) if result.get("batch_id") else None,
        "dry_run": False,
        **counts,
    }
