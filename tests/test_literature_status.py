"""Read-only batch reconciliation from authoritative literature ledger rows."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from lyme_gap_atlas_data import literature_status as module


class Cursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def __enter__(self) -> Cursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, args: tuple[str, ...]) -> None:
        self.calls.append((sql, args))

    def fetchone(self) -> tuple[str, int]:
        return ("COMPLETED", 25)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return [
            (
                "1",
                "PMC1",
                "processed",
                "review-1",
                "attempt-1",
                "completed",
                None,
                1,
                None,
                None,
                None,
                None,
                None,
                "run-1",
                "workflow-1",
                "prod",
                "code-1",
                "image-1",
                True,
                True,
                True,
            ),
            (
                "1",
                "PMC1",
                "processed",
                "review-1",
                "attempt-0",
                "failed",
                "RuntimeError",
                0,
                "model_execution",
                True,
                "inspect_model_execution_then_retry",
                "extract",
                None,
                "run-0",
                "workflow-0",
                "prod",
                "code-0",
                "image-0",
                True,
                True,
                True,
            ),
            (
                "2",
                "PMC2",
                "retry_pending",
                "review-2",
                "attempt-2",
                "failed",
                "HTTPStatusError",
                2,
                "provider_rejected_pre_inference",
                False,
                "review_provider_contract",
                "extract",
                "provider_http_400:request_id_req_2",
                "run-2",
                "workflow-2",
                "prod",
                "code-2",
                "image-2",
                True,
                False,
                False,
            ),
        ]


class Connection:
    def __init__(self, cursor: Cursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> Cursor:
        return self._cursor


def test_reconcile_counts_and_failed_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = Cursor()
    monkeypatch.setattr(module, "connect", lambda _settings: Connection(cursor))
    run_id = str(uuid.uuid4())
    result = module.literature_status(run_id)
    assert result["discovered"] == 2
    assert result["stage_counts"] == {"corpus_admit": 1, "extract": 1}
    assert result["failure_category_counts"] == {
        "provider_rejected_pre_inference": 1,
        "model_execution": 1,
    }
    assert result["stage_totals"]["extraction"] == {"entered": 3, "succeeded": 1, "failed": 2}
    assert result["stage_totals"]["corpus_admission"] == {
        "entered": 1,
        "succeeded": 1,
        "failed": None,
    }
    assert result["papers"][1]["extraction_attempt_id"] == "attempt-2"
    assert result["papers"][1]["next_action"] == "review_provider_contract"
    assert result["papers"][1]["provider_rationale"] == "provider_http_400:request_id_req_2"
    assert result["papers"][1]["correlation_id"] == "run-2"
    assert result["papers"][0]["extraction_attempt_id"] == "attempt-1"
    assert [item["extraction_attempt_id"] for item in result["attempt_history"]] == [
        "attempt-1",
        "attempt-0",
        "attempt-2",
    ]
    assert cursor.calls[0][1] == (run_id,)
    assert cursor.calls[1][1] == (run_id, run_id, run_id)


def test_reconcile_rejects_unbounded_identifier() -> None:
    with pytest.raises(ValueError, match="UUID"):
        module.literature_status("' OR 1=1 --")


def test_graph_published_paper_has_corpus_next_action() -> None:
    row = (
        "3",
        "PMC3",
        "processed",
        "review-3",
        "attempt-3",
        "completed",
        None,
        1,
        None,
        None,
        None,
        None,
        None,
        "run-3",
        "workflow-3",
        "prod",
        "code-3",
        "image-3",
        True,
        True,
        False,
    )
    paper = module._paper_status(row)
    assert paper["next_action"] == "run_or_inspect_corpus_rebuild"
    assert paper["corpus_admitted"] is False


def test_pre_attempt_failure_from_state_event_is_reported() -> None:
    row = (
        "4",
        "PMC4",
        "retry_pending",
        "review-4",
        None,
        None,
        None,
        None,
        "artifact_license_identity",
        False,
        "review_open_access_and_identity",
        "acquire",
        None,
        "worker-run-before-attempt",
        None,
        "prod",
        None,
        None,
        False,
        False,
        False,
    )
    paper = module._paper_status(row)
    assert paper["failure_category"] == "artifact_license_identity"
    assert paper["failure_stage"] == "acquire"
    assert paper["retryable"] is False
    assert paper["next_action"] == "review_open_access_and_identity"
