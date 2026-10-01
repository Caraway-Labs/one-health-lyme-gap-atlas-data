from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from lyme_gap_atlas_data.canary_receipts import (
    _ATTEMPT_COLUMNS,
    _GRAPH_COLUMNS,
    inspect_group_canary_receipts,
)
from lyme_gap_atlas_data.extraction_group import ExtractionGroup

GROUP = ExtractionGroup(
    "22345678-1234-4234-8234-123456789abc",
    "12345678-1234-4234-8234-123456789abc",
    tuple(str(1000 + index) for index in range(10)),
    "sha256:" + "a" * 64,
    "kg-v1.0.0",
)
ATTEMPT_ID = "32345678-1234-4234-8234-123456789abc"
RECEIPT_ID = "42345678-1234-4234-8234-123456789abc"
ARTIFACT_ID = "52345678-1234-4234-8234-123456789abc"


def attempt() -> dict[str, Any]:
    return {
        "context_attempt_id": ATTEMPT_ID,
        "context_pmid": "1000",
        "attempt_id": ATTEMPT_ID,
        "pmid": "1000",
        "status": "completed",
        "method_version": "kg-v1.0.0",
        "started_at": "2026-10-01T10:02:00+00:00",
        "finished_at": "2026-10-01T10:04:00+00:00",
        "details": {
            "discovery_run_id": GROUP.discovery_run_id,
            "image_sha": GROUP.image_digest,
            "trace_id": "b" * 32,
            "extraction_group": {
                **GROUP.context(),
                "readiness_completed_at": "2026-10-01T10:00:00+00:00",
            },
        },
        "paper_state": "processed",
        "review_decision_id": "steward-decision",
        "paper_pmcid": "PMC123",
        "authoritative_discovery_run_id": GROUP.discovery_run_id,
    }


def graph() -> dict[str, Any]:
    return {
        "receipt_id": RECEIPT_ID,
        "pmid": "1000",
        "attempt_id": ATTEMPT_ID,
        "artifact_id": ARTIFACT_ID,
        "contribution_sha256": "c" * 64,
        "published_at": "2026-10-01T10:03:00+00:00",
        "node_count": 3,
        "passage_count": 2,
        "transaction_id": "neo4j-transaction",
        "artifact_pmid": "1000",
        "fulltext_artifact_id": ARTIFACT_ID,
        "pmcid": "PMC123",
        "object_key": "private-object-sentinel",
        "license_url": "private-license-sentinel",
        "jats_sha256": "d" * 64,
        "text_sha256": "e" * 64,
        "admitted_at": "2026-10-01T10:01:00+00:00",
    }


class Cursor:
    def __init__(self) -> None:
        self.attempts = [attempt()]
        self.graphs = [graph()]
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.fail_on_query: int | None = None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executed.append((sql, params))
        if len(self.executed) == self.fail_on_query:
            raise RuntimeError("private-error-sentinel")

    def fetchall(self) -> list[tuple[Any, ...]]:
        rows, columns = (
            (self.attempts, _ATTEMPT_COLUMNS)
            if len(self.executed) == 1
            else (self.graphs, _GRAPH_COLUMNS)
        )
        return [tuple(row[key] for key in columns) for row in rows]


def inspect(cursor: Cursor) -> dict[str, Any]:
    result = inspect_group_canary_receipts(GROUP, cursor)
    # The whole gate never opens, even when this receipt subset passes.
    assert result["status"] == "BLOCKED"
    assert result["corpus_admission"] == "NOT_CHECKED"
    assert result["serving_visibility"] == "NOT_CHECKED"
    assert result["full_pre_topology_readiness"] == "NOT_CHECKED"
    assert all(sql.lstrip().startswith("SELECT") for sql, _params in cursor.executed)
    serialized = json.dumps(result)
    assert "private-object-sentinel" not in serialized
    assert "private-license-sentinel" not in serialized
    assert "private-error-sentinel" not in serialized
    return result


def test_complete_authoritative_receipts_are_ready_only_for_this_subset() -> None:
    cursor = Cursor()
    result = inspect(cursor)
    assert result["receipt_readiness"] == "READY"
    assert result["receipt_identity"] == {
        "extraction_attempt_id": ATTEMPT_ID,
        "graph_receipt_id": RECEIPT_ID,
        "artifact_id": ARTIFACT_ID,
        "pmid": "1000",
    }
    assert cursor.executed[0][1] == (GROUP.discovery_run_id, GROUP.group_id)
    assert cursor.executed[1][1] == (ATTEMPT_ID,)
    assert (
        "a.extraction_attempt_id = d.extraction_attempt_id AND a.pmid = d.pmid"
        in cursor.executed[0][0]
    )
    assert "discovery.request_evidence:pmids" in cursor.executed[0][0]
    assert "f.artifact_id = r.artifact_id AND f.pmid = r.pmid" in cursor.executed[1][0]
    assert "fresh_completed_corpus_admission_not_verified" in json.dumps(result)
    assert "actual_serving_query_visibility_not_verified" in json.dumps(result)
    assert "group_continuation_not_implemented" in json.dumps(result)


def test_snowflake_datetime_and_serialized_variant_are_supported() -> None:
    cursor = Cursor()
    cursor.attempts[0]["started_at"] = datetime(2026, 10, 1, 10, 2, tzinfo=UTC)
    cursor.attempts[0]["finished_at"] = datetime(2026, 10, 1, 10, 4, tzinfo=UTC)
    cursor.attempts[0]["details"] = json.dumps(cursor.attempts[0]["details"])
    assert inspect(cursor)["receipt_readiness"] == "READY"


@pytest.mark.parametrize("table", ["attempts", "graphs"])
@pytest.mark.parametrize("count", [0, 2])
def test_missing_or_ambiguous_lineage_is_closed(table: str, count: int) -> None:
    cursor = Cursor()
    rows = getattr(cursor, table)
    setattr(cursor, table, [copy.deepcopy(rows[0]) for _ in range(count)])
    result = inspect(cursor)
    assert result["receipt_readiness"] == "BLOCKED"
    assert "receipt_identity" not in result


@pytest.mark.parametrize(
    "key,value",
    [
        ("status", "failed"),
        ("status", "reserved"),
        ("paper_state", "approved"),
        ("review_decision_id", None),
        ("method_version", "kg-v2.0.0"),
        ("context_attempt_id", RECEIPT_ID),
        ("context_pmid", "1001"),
        ("pmid", "9999"),
        ("attempt_id", None),
        ("authoritative_discovery_run_id", None),
        ("started_at", "2026-10-01T09:59:00+00:00"),
        ("finished_at", "2026-10-01T10:01:00+00:00"),
        ("finished_at", None),
        ("started_at", "2026-10-01T10:02:00"),
        ("details", None),
    ],
)
def test_failed_partial_stale_or_mismatched_attempt_blocks_before_graph_read(
    key: str, value: Any
) -> None:
    cursor = Cursor()
    cursor.attempts[0][key] = value
    result = inspect(cursor)
    assert result["receipt_readiness"] == "BLOCKED"
    assert len(cursor.executed) == 1


@pytest.mark.parametrize(
    "key,value",
    [
        ("group_id", RECEIPT_ID),
        ("discovery_run_id", RECEIPT_ID),
        ("image_digest", "sha256:" + "b" * 64),
        ("configuration_version", "kg-v2.0.0"),
        ("inventory_sha256", "b" * 64),
        ("pmids", [*GROUP.pmids[:-1], "9999"]),
        ("group_contract_version", 2),
        ("group_contract_version", True),
        ("phase", "continue"),
        ("caller_success", True),
        ("readiness_completed_at", None),
        ("readiness_completed_at", "2026-10-01T10:05:00+00:00"),
    ],
)
def test_cross_group_reuse_and_context_drift_cannot_pass(key: str, value: Any) -> None:
    cursor = Cursor()
    cursor.attempts[0]["details"]["extraction_group"][key] = value
    assert inspect(cursor)["receipt_readiness"] == "BLOCKED"
    assert len(cursor.executed) == 1


@pytest.mark.parametrize("key", ["image_sha", "discovery_run_id"])
def test_root_attempt_identity_must_also_match(key: str) -> None:
    cursor = Cursor()
    cursor.attempts[0]["details"][key] = "other"
    assert inspect(cursor)["receipt_readiness"] == "BLOCKED"


@pytest.mark.parametrize(
    "key,value",
    [
        ("receipt_id", "invalid"),
        ("attempt_id", RECEIPT_ID),
        ("pmid", "1001"),
        ("artifact_pmid", "1001"),
        ("artifact_id", RECEIPT_ID),
        ("fulltext_artifact_id", None),
        ("pmcid", "PMC999"),
        ("object_key", None),
        ("license_url", ""),
        ("transaction_id", ""),
        ("contribution_sha256", "invalid"),
        ("jats_sha256", None),
        ("text_sha256", ""),
        ("node_count", 0),
        ("passage_count", 0),
        ("admitted_at", "2026-10-01T09:59:00+00:00"),
        ("admitted_at", "2026-10-01T10:03:00+00:00"),
        ("published_at", "2026-10-01T10:01:00+00:00"),
        ("published_at", "2026-10-01T10:05:00+00:00"),
        ("published_at", None),
    ],
)
def test_graph_artifact_mismatch_or_stale_chronology_is_closed(key: str, value: Any) -> None:
    cursor = Cursor()
    cursor.graphs[0][key] = value
    result = inspect(cursor)
    assert result["receipt_readiness"] == "BLOCKED"
    assert "receipt_identity" not in result


@pytest.mark.parametrize("query", [1, 2])
def test_authoritative_read_failure_is_typed_and_sanitized(query: int) -> None:
    cursor = Cursor()
    cursor.fail_on_query = query
    result = inspect(cursor)
    assert result["receipt_readiness"] == "BLOCKED"
    assert result["blockers"][0]["capability"] == "authoritative_canary_receipt_read_failed"
    assert all(blocker["retryable"] is False for blocker in result["blockers"])
