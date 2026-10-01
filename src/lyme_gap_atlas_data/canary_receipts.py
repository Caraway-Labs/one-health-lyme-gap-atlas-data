"""Read authoritative same-group canary lineage; never authorize continuation."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any, Protocol

from .extraction_group import ExtractionGroup, GroupGateBlocked


class ReceiptCursor(Protocol):
    def execute(self, sql: str, params: tuple[object, ...]) -> Any: ...

    def fetchall(self) -> list[tuple[Any, ...]]: ...


_ATTEMPT_COLUMNS = (
    "context_attempt_id",
    "context_pmid",
    "attempt_id",
    "pmid",
    "status",
    "method_version",
    "started_at",
    "finished_at",
    "details",
    "paper_state",
    "review_decision_id",
    "paper_pmcid",
    "authoritative_discovery_run_id",
)
_GRAPH_COLUMNS = (
    "receipt_id",
    "pmid",
    "attempt_id",
    "artifact_id",
    "contribution_sha256",
    "published_at",
    "node_count",
    "passage_count",
    "transaction_id",
    "artifact_pmid",
    "fulltext_artifact_id",
    "pmcid",
    "object_key",
    "license_url",
    "jats_sha256",
    "text_sha256",
    "admitted_at",
)
_EXTERNAL_BLOCKERS = (
    "fresh_completed_corpus_admission_not_verified",
    "actual_serving_query_visibility_not_verified",
    "full_pre_topology_readiness_not_verified",
    "group_continuation_not_implemented",
)


def _require(condition: bool, capability: str) -> None:
    if not condition:
        raise GroupGateBlocked(capability)


def _one(rows: list[tuple[Any, ...]], columns: tuple[str, ...], capability: str) -> dict[str, Any]:
    _require(len(rows) == 1, capability)
    _require(len(rows[0]) == len(columns), "supported_canary_receipt_projection")
    return dict(zip(columns, rows[0], strict=True))


def _time(value: object) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        _require(parsed.utcoffset() is not None, "aware_canary_receipt_timestamps")
        return parsed
    except (ValueError, TypeError):
        raise GroupGateBlocked("aware_canary_receipt_timestamps") from None


def _uuid(value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise GroupGateBlocked("valid_canary_receipt_identifiers") from None


def _hash(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _report(capabilities: tuple[str, ...], *, receipts_ready: bool = False) -> dict[str, Any]:
    return {
        "status": "BLOCKED",
        "scope": "same_group_attempt_graph_artifact_receipts",
        "receipt_readiness": "READY" if receipts_ready else "BLOCKED",
        "corpus_admission": "NOT_CHECKED",
        "serving_visibility": "NOT_CHECKED",
        "full_pre_topology_readiness": "NOT_CHECKED",
        "blockers": [GroupGateBlocked(capability).report for capability in capabilities],
    }


def inspect_group_canary_receipts(group: ExtractionGroup, cursor: ReceiptCursor) -> dict[str, Any]:
    """SELECT-only receipt seam. Even complete lineage leaves continuation BLOCKED.

    Use an existing authorized connection/cursor. Caller success assertions,
    provider probes and production connection construction are not accepted.
    """
    try:
        cursor.execute(
            """SELECT d.extraction_attempt_id, d.pmid, a.extraction_attempt_id, a.pmid,
                      a.status, a.method_version, a.started_at, a.finished_at, d.details,
                      p.state, p.final_review_decision_id, p.pmcid, discovery.discovery_run_id
               FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS d
               LEFT JOIN KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS a
                 ON a.extraction_attempt_id = d.extraction_attempt_id AND a.pmid = d.pmid
               LEFT JOIN KNOWLEDGE_GRAPH.PAPERS p ON p.pmid = a.pmid
               LEFT JOIN KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS discovery
                 ON discovery.discovery_run_id = %s
                AND ARRAY_CONTAINS(TO_VARIANT(a.pmid), discovery.request_evidence:pmids)
               WHERE d.diagnostic_type = 'attempt_context'
                 AND d.details:extraction_group:group_id::STRING = %s""",
            (group.discovery_run_id, group.group_id),
        )
        attempt = _one(
            cursor.fetchall(), _ATTEMPT_COLUMNS, "one_authoritative_group_canary_attempt"
        )
        details = attempt["details"]
        if isinstance(details, str):
            details = json.loads(details)
        _require(isinstance(details, dict), "matching_authoritative_group_context")
        context = details.get("extraction_group")
        _require(isinstance(context, dict), "matching_authoritative_group_context")
        _require(
            type(context.get("group_contract_version")) is int
            and {key: value for key, value in context.items() if key != "readiness_completed_at"}
            == group.context()
            and details.get("discovery_run_id") == group.discovery_run_id
            and details.get("image_sha") == group.image_digest
            and attempt["method_version"] == group.configuration_version,
            "matching_authoritative_group_context",
        )
        attempt_id = _uuid(attempt["attempt_id"])
        _require(
            attempt["context_attempt_id"] == attempt["attempt_id"]
            and attempt["context_pmid"] == attempt["pmid"]
            and attempt["pmid"] in group.pmids
            and attempt["status"] == "completed"
            and attempt["authoritative_discovery_run_id"] == group.discovery_run_id
            and attempt["paper_state"] == "processed"
            and bool(attempt["review_decision_id"]),
            "completed_approved_same_group_canary_attempt",
        )
        ready = _time(context.get("readiness_completed_at"))
        started = _time(attempt["started_at"])
        finished = _time(attempt["finished_at"])
        _require(ready <= started < finished, "canary_completed_after_group_readiness")
        cursor.execute(
            """SELECT r.graph_receipt_id, r.pmid, r.extraction_attempt_id, r.artifact_id,
                      r.contribution_sha256, r.published_at, r.node_count, r.passage_count,
                      r.neo4j_transaction_id, f.pmid, f.artifact_id, f.pmcid, f.object_key,
                      f.license_url, f.jats_sha256, f.text_sha256, f.admitted_at
               FROM KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS r
               LEFT JOIN KNOWLEDGE_GRAPH.PMC_FULL_TEXT_ARTIFACTS f
                 ON f.artifact_id = r.artifact_id AND f.pmid = r.pmid
               WHERE r.extraction_attempt_id = %s""",
            (attempt_id,),
        )
        graph = _one(cursor.fetchall(), _GRAPH_COLUMNS, "one_exact_canary_graph_artifact_receipt")
        receipt_id, artifact_id = _uuid(graph["receipt_id"]), _uuid(graph["artifact_id"])
        _require(
            graph["attempt_id"] == attempt["attempt_id"]
            and graph["pmid"] == attempt["pmid"] == graph["artifact_pmid"]
            and graph["artifact_id"] == graph["fulltext_artifact_id"]
            and graph["pmcid"] == attempt["paper_pmcid"]
            and bool(graph["pmcid"])
            and bool(graph["object_key"])
            and bool(graph["license_url"])
            and bool(graph["transaction_id"])
            and all(
                _hash(graph[key]) for key in ("jats_sha256", "text_sha256", "contribution_sha256")
            )
            and graph["node_count"] > 0
            and graph["passage_count"] > 0,
            "exact_canary_attempt_graph_artifact_lineage",
        )
        _require(
            ready <= _time(graph["admitted_at"]) <= started
            and started <= _time(graph["published_at"]) <= finished,
            "fresh_canary_artifact_and_graph_chronology",
        )
        report = _report(_EXTERNAL_BLOCKERS, receipts_ready=True)
        report["receipt_identity"] = {
            "extraction_attempt_id": attempt_id,
            "graph_receipt_id": receipt_id,
            "artifact_id": artifact_id,
            "pmid": attempt["pmid"],
        }
        return report
    except GroupGateBlocked as error:
        return _report((error.capability, *_EXTERNAL_BLOCKERS))
    except Exception:
        # An inaccessible/malformed authoritative projection cannot become success.
        return _report(("authoritative_canary_receipt_read_failed", *_EXTERNAL_BLOCKERS))
