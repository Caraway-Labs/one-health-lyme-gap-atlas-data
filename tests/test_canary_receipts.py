from __future__ import annotations

import copy
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import pytest

from lyme_gap_atlas_data.canary_receipts import (
    _ATTEMPT_COLUMNS,
    _CORPUS_COLUMNS,
    _GRAPH_COLUMNS,
    inspect_group_canary_corpus_receipts,
    inspect_group_canary_receipts,
)
from lyme_gap_atlas_data.extraction_group import ExtractionGroup
from lyme_gap_atlas_data.retrieval_corpus import (
    CorpusRules,
    EligiblePaper,
    chunk_paper_sections,
    corpus_content_sha256,
)

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
BUILD_ID = "62345678-1234-4234-8234-123456789abc"


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


def corpus() -> list[dict[str, Any]]:
    source = graph()
    paper = EligiblePaper(
        **{
            key: source[key]
            for key in (
                "pmid",
                "pmcid",
                "artifact_id",
                "object_key",
                "jats_sha256",
                "text_sha256",
                "contribution_sha256",
            )
        }
    )
    text = "private-unit-sentinel " + " ".join(
        f"Sentence {index} describes a distinct observed finding in the study."
        for index in range(60)
    )
    rules = CorpusRules()
    units, _metrics = chunk_paper_sections([("Results", text)], paper=paper, rules=rules)
    assert len(units) > 2
    return [
        {
            **asdict(unit),
            "unit_rules_version": rules.rules_version,
            "unit_build_id": BUILD_ID,
            "built_at": "2026-10-01T10:06:00+00:00",
            "build_id": BUILD_ID,
            "build_rules_version": rules.rules_version,
            "rules_sha256": rules.sha256(),
            "discovery_run_id": GROUP.discovery_run_id,
            "status": "completed",
            "started_at": "2026-10-01T10:05:00+00:00",
            "finished_at": "2026-10-01T10:08:00+00:00",
            "papers_admitted": 1,
            "chunks_written": len(units),
            "corpus_content_sha256": corpus_content_sha256(units),
        }
        for unit in units
    ]


class Cursor:
    def __init__(self) -> None:
        self.attempts = [attempt()]
        self.graphs = [graph()]
        self.units = corpus()
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.fail_on_query: int | None = None

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executed.append((sql, params))
        if len(self.executed) == self.fail_on_query:
            raise RuntimeError("private-error-sentinel")

    def fetchall(self) -> list[tuple[Any, ...]]:
        rows, columns = {
            1: (self.attempts, _ATTEMPT_COLUMNS),
            2: (self.graphs, _GRAPH_COLUMNS),
            3: (self.units, _CORPUS_COLUMNS),
        }[len(self.executed)]
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


def test_retry_reuses_older_exact_immutable_artifact_with_fresh_group_canary() -> None:
    cursor = Cursor()
    cursor.graphs[0]["admitted_at"] = "2026-09-01T10:00:00+00:00"
    result = inspect(cursor)
    assert result["receipt_readiness"] == "READY"
    assert result["receipt_identity"]["artifact_id"] == ARTIFACT_ID


@pytest.mark.parametrize("failure", ["source", "receipt", "stale_attempt", "stale_publication"])
def test_older_artifact_does_not_relax_attempt_or_publication_identity(failure: str) -> None:
    cursor = Cursor()
    cursor.graphs[0]["admitted_at"] = "2026-09-01T10:00:00+00:00"
    if failure == "source":
        cursor.graphs[0]["artifact_pmid"] = "1001"
    elif failure == "receipt":
        cursor.graphs[0]["attempt_id"] = RECEIPT_ID
    elif failure == "stale_attempt":
        cursor.attempts[0]["started_at"] = "2026-09-01T10:01:00+00:00"
        cursor.attempts[0]["finished_at"] = "2026-09-01T10:04:00+00:00"
    else:
        cursor.graphs[0]["published_at"] = "2026-09-01T10:03:00+00:00"
    assert inspect(cursor)["receipt_readiness"] == "BLOCKED"


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


def inspect_corpus(cursor: Cursor) -> dict[str, Any]:
    result = inspect_group_canary_corpus_receipts(GROUP, cursor)
    assert result["status"] == "BLOCKED"
    assert result["serving_visibility"] == "NOT_CHECKED"
    assert result["full_pre_topology_readiness"] == "NOT_CHECKED"
    assert all(sql.lstrip().startswith("SELECT") for sql, _params in cursor.executed)
    serialized = json.dumps(result)
    for sentinel in (
        "private-object-sentinel",
        "private-license-sentinel",
        "private-unit-sentinel",
        "private-error-sentinel",
    ):
        assert sentinel not in serialized
    return result


def change_build(cursor: Cursor, key: str, value: Any) -> None:
    for unit in cursor.units:
        unit[key] = value


def test_fresh_completed_corpus_joins_real_producer_units_but_gate_stays_closed() -> None:
    cursor = Cursor()
    result = inspect_corpus(cursor)
    assert result["receipt_readiness"] == "READY"
    assert result["corpus_admission"] == "READY"
    assert result["corpus_identity"] == {
        "build_id": BUILD_ID,
        "pmid": "1000",
        "unit_count": len(cursor.units),
        "rules_version": CorpusRules().rules_version,
    }
    assert cursor.executed[2][1] == ("1000", CorpusRules().rules_version)
    assert "b.build_id = u.build_id" in cursor.executed[2][0]
    assert "actual_serving_query_visibility_not_verified" in json.dumps(result)
    assert "group_continuation_not_implemented" in json.dumps(result)
    assert "fresh_completed_corpus_admission_not_verified" not in json.dumps(result)


def test_older_immutable_artifact_can_have_fresh_completed_canary_corpus() -> None:
    cursor = Cursor()
    cursor.graphs[0]["admitted_at"] = "2026-09-01T10:00:00+00:00"
    assert inspect_corpus(cursor)["corpus_admission"] == "READY"


def test_multi_paper_build_proves_canary_subset_without_global_reconciliation() -> None:
    cursor = Cursor()
    change_build(cursor, "papers_admitted", 5)
    change_build(cursor, "chunks_written", len(cursor.units) + 100)
    result = inspect_corpus(cursor)
    assert result["corpus_admission"] == "READY"
    assert result["corpus_identity"]["unit_count"] == len(cursor.units)


def test_failed_lineage_does_not_read_or_accept_corpus() -> None:
    cursor = Cursor()
    cursor.attempts[0]["status"] = "failed"
    result = inspect_corpus(cursor)
    assert result["receipt_readiness"] == "BLOCKED"
    assert result["corpus_admission"] == "NOT_CHECKED"
    assert len(cursor.executed) == 1


@pytest.mark.parametrize(
    "failure", ["empty", "duplicate", "gap", "missing_tail", "mixed_builds", "orphan_build"]
)
def test_missing_partial_ambiguous_or_orphan_corpus_is_closed(failure: str) -> None:
    cursor = Cursor()
    if failure == "empty":
        cursor.units = []
    elif failure == "duplicate":
        cursor.units.append(copy.deepcopy(cursor.units[0]))
    elif failure == "gap":
        cursor.units.pop(1)
    elif failure == "missing_tail":
        cursor.units.pop()
    elif failure == "mixed_builds":
        cursor.units[-1]["build_id"] = ARTIFACT_ID
    else:
        change_build(cursor, "build_id", None)
    result = inspect_corpus(cursor)
    assert result["receipt_readiness"] == "READY"
    assert result["corpus_admission"] == "BLOCKED"
    assert "corpus_identity" not in result


@pytest.mark.parametrize(
    "key,value",
    [
        ("status", "failed"),
        ("status", "running"),
        ("status", None),
        ("build_rules_version", "other"),
        ("rules_sha256", "f" * 64),
        ("discovery_run_id", RECEIPT_ID),
        ("discovery_run_id", None),
        ("papers_admitted", 0),
        ("papers_admitted", True),
        ("chunks_written", 0),
        ("chunks_written", 9999),
        ("corpus_content_sha256", None),
        ("started_at", "2026-10-01T10:01:00+00:00"),
        ("finished_at", "2026-10-01T10:04:00+00:00"),
        ("finished_at", None),
        ("started_at", "2026-10-01T10:05:00"),
    ],
)
def test_build_status_identity_counts_and_freshness_are_authoritative(key: str, value: Any) -> None:
    cursor = Cursor()
    change_build(cursor, key, value)
    assert inspect_corpus(cursor)["corpus_admission"] == "BLOCKED"


@pytest.mark.parametrize(
    "key,value",
    [
        ("pmid", "1001"),
        ("pmcid", "PMC999"),
        ("artifact_id", RECEIPT_ID),
        ("object_key", "other"),
        ("jats_sha256", "f" * 64),
        ("text_sha256", "f" * 64),
        ("contribution_sha256", "f" * 64),
        ("unit_build_id", RECEIPT_ID),
        ("unit_rules_version", "other"),
        ("unit_id", "f" * 64),
        ("unit_text_sha256", "f" * 64),
        ("unit_text", "tampered-unit-sentinel"),
        ("char_start", -1),
        ("char_start", True),
        ("char_end", 1),
        ("section_label", ""),
        ("chunk_index", True),
        ("built_at", "2026-10-01T10:03:00+00:00"),
        ("built_at", "2026-10-01T10:09:00+00:00"),
        ("built_at", None),
    ],
)
def test_unit_source_contribution_content_identity_and_chronology_must_match(
    key: str, value: Any
) -> None:
    cursor = Cursor()
    cursor.units[0][key] = value
    result = inspect_corpus(cursor)
    assert result["corpus_admission"] == "BLOCKED"
    assert "tampered-unit-sentinel" not in json.dumps(result)


def test_changed_expected_rules_do_not_accept_existing_projection() -> None:
    cursor = Cursor()
    result = inspect_group_canary_corpus_receipts(
        GROUP, cursor, rules=CorpusRules(target_chars=1300)
    )
    assert result["status"] == "BLOCKED"
    assert result["corpus_admission"] == "BLOCKED"


def test_corpus_read_failure_is_typed_sanitized_and_does_not_open_gate() -> None:
    cursor = Cursor()
    cursor.fail_on_query = 3
    result = inspect_corpus(cursor)
    assert result["receipt_readiness"] == "READY"
    assert result["corpus_admission"] == "BLOCKED"
    assert result["blockers"][0]["capability"] == "authoritative_canary_corpus_read_failed"
