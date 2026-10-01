from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from lyme_gap_atlas_data import pmc_extraction_worker as worker
from lyme_gap_atlas_data.extraction_group import ExtractionGroup, GroupGateBlocked

SCOPE = "12345678-1234-4234-8234-123456789abc"
GROUP = "22345678-1234-4234-8234-123456789abc"
IMAGE = "sha256:" + "a" * 64
PMIDS = [str(1000 + index) for index in range(10)]


def manifest(**changes: Any) -> dict[str, Any]:
    return {
        "group_id": GROUP,
        "discovery_run_id": SCOPE,
        "pmids": PMIDS,
        "image_digest": IMAGE,
        "configuration_version": "kg-v1.0.0",
        "group_contract_version": 1,
        "phase": "canary",
        **changes,
    }


def parse(value: dict[str, Any]) -> ExtractionGroup:
    return ExtractionGroup.parse(
        json.dumps(value),
        discovery_run_id=SCOPE,
        image_digest=IMAGE,
        configuration_version="kg-v1.0.0",
    )


@pytest.mark.parametrize("count", [10, 25])
def test_exact_inventory_bounds_and_order_independent_fingerprint(count: int) -> None:
    inventory = [str(1000 + index) for index in range(count)]
    group = parse(manifest(pmids=inventory))
    reordered = parse(manifest(pmids=list(reversed(inventory))))
    assert group.inventory_sha256 == reordered.inventory_sha256
    assert set(group.pmids) == set(inventory)
    changed = parse(manifest(pmids=[*inventory[:-1], "9999"]))
    assert changed.inventory_sha256 != group.inventory_sha256


@pytest.mark.parametrize(
    "change",
    [
        {"pmids": PMIDS[:9]},
        {"pmids": [str(1000 + i) for i in range(26)]},
        {"pmids": [*PMIDS[:-1], PMIDS[0]]},
        {"pmids": [*PMIDS[:-1], 42]},
        {"pmids": [*PMIDS[:-1], "00123"]},
        {"group_id": "secret-sentinel"},
        {"group_contract_version": True},
        {"extra": "secret-sentinel"},
        {"image_digest": "latest"},
        {"phase": "unknown"},
    ],
)
def test_malformed_manifest_blocks_without_echoing_input(change: dict[str, Any]) -> None:
    with pytest.raises(GroupGateBlocked) as failure:
        parse(manifest(**change))
    assert failure.value.capability == "valid_bounded_group_manifest"
    assert "secret-sentinel" not in str(failure.value)
    assert failure.value.report["retryable"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"discovery_run_id": GROUP},
        {"image_digest": "sha256:" + "b" * 64},
        {"configuration_version": "kg-v2.0.0"},
    ],
)
def test_runtime_identity_drift_blocks(change: dict[str, Any]) -> None:
    with pytest.raises(GroupGateBlocked, match="matching_group_runtime_identity"):
        parse(manifest(**change))


def test_continuation_cannot_accept_unimplemented_or_caller_asserted_proof() -> None:
    with pytest.raises(GroupGateBlocked, match="not_implemented"):
        parse(manifest(phase="continue"))
    with pytest.raises(GroupGateBlocked, match="valid_bounded_group_manifest"):
        parse(manifest(phase="continue", canary_complete=True))


@pytest.mark.parametrize("raw", ["", "{", "[]", "null", '"secret-sentinel"', " " * 8193])
def test_invalid_serialization_is_typed_and_sanitized(raw: str) -> None:
    with pytest.raises(GroupGateBlocked) as failure:
        ExtractionGroup.parse(
            raw, discovery_run_id=SCOPE, image_digest=IMAGE, configuration_version="kg-v1.0.0"
        )
    assert "secret-sentinel" not in str(failure.value)


def test_duplicate_json_fields_cannot_change_reviewed_identity() -> None:
    raw = json.dumps(manifest())[:-1] + ', "group_id": "' + GROUP + '"}'
    with pytest.raises(GroupGateBlocked, match="valid_bounded_group_manifest"):
        ExtractionGroup.parse(
            raw, discovery_run_id=SCOPE, image_digest=IMAGE, configuration_version="kg-v1.0.0"
        )


def test_missing_runtime_identity_cannot_match_manifest() -> None:
    with pytest.raises(GroupGateBlocked, match="matching_group_runtime_identity"):
        ExtractionGroup.parse(
            json.dumps(manifest()),
            discovery_run_id=None,
            image_digest=None,
            configuration_version="kg-v1.0.0",
        )


class Cursor:
    def __init__(self) -> None:
        self.rows = [(pmid, "approved", "decision", True) for pmid in PMIDS]
        self.prior_count: int | None = 0
        self.claim_pmid = PMIDS[0]
        self.executed: list[tuple[str, Any]] = []
        self.rowcount = 1

    def __enter__(self) -> Cursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, args: Any) -> None:
        self.executed.append((sql, args))

    def fetchall(self) -> list[tuple[str, str, str | None]]:
        # The authoritative scope predicate excludes members outside discovery.
        sql, args = self.executed[-1]
        assert "d.request_evidence:pmids" in sql
        assert args == (json.dumps(tuple(sorted(PMIDS))), SCOPE)
        return [
            (pmid, state, decision) for pmid, state, decision, in_scope in self.rows if in_scope
        ]

    def fetchone(self) -> Any:
        if "COUNT(*)" in self.executed[-1][0] and "SELECT p.pmid" not in self.executed[-1][0]:
            return None if self.prior_count is None else (self.prior_count,)
        return (
            self.claim_pmid,
            "PMC123",
            "title",
            "journal",
            "2026-01-01",
            [],
            "en",
            [],
            "approved",
        )


class Connection:
    def __init__(self, cursor: Cursor) -> None:
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> Cursor:
        return self._cursor

    def autocommit(self, _enabled: bool) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


@pytest.fixture
def runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[worker.SnowflakePMCExtractionLedger, Cursor, Connection]:
    monkeypatch.setenv("ATLAS_DISCOVERY_RUN_ID", SCOPE)
    monkeypatch.setenv("IMAGE_DIGEST", IMAGE)
    monkeypatch.setenv("ATLAS_EXTRACTION_GROUP_MANIFEST", json.dumps(manifest()))
    cursor = Cursor()
    connection = Connection(cursor)
    monkeypatch.setattr(worker, "connect", lambda _settings: connection)
    return worker.SnowflakePMCExtractionLedger(bucket="private"), cursor, connection


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "outside_scope",
        "unapproved",
        "no_decision",
        "duplicate",
        "prior_failed",
        "prior_partial",
        "unknown_prior",
    ],
)
def test_authoritative_gate_blocks_before_claim_or_provider(
    runtime: tuple[worker.SnowflakePMCExtractionLedger, Cursor, Connection],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    _ledger, cursor, connection = runtime
    if failure == "missing":
        cursor.rows.pop()
    elif failure == "duplicate":
        cursor.rows[-1] = cursor.rows[0]
    elif failure == "outside_scope":
        cursor.rows[-1] = (PMIDS[-1], "approved", "decision", False)
    elif failure == "unapproved":
        cursor.rows[-1] = (PMIDS[-1], "rejected", "decision", True)
    elif failure == "no_decision":
        cursor.rows[-1] = (PMIDS[-1], "approved", None, True)
    else:
        # Any recorded attempt, including failed/reserved/partial, fences reuse.
        cursor.prior_count = None if failure == "unknown_prior" else 1
    monkeypatch.setattr(
        worker, "literature_preflight", lambda *_args, **_kwargs: {"status": "READY"}
    )

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("provider, graph driver, or artifact client constructed after blocked gate")

    monkeypatch.setattr(worker.GraphDatabase, "driver", forbidden)
    monkeypatch.setattr(worker, "GroqStructuredExtractor", forbidden)
    monkeypatch.setattr(worker, "OpenAIResponsesExtractor", forbidden)
    monkeypatch.setattr(worker, "OpenAIEmbeddingClient", forbidden)
    monkeypatch.setattr(worker, "_spaces_client", forbidden)
    with pytest.raises(GroupGateBlocked):
        worker.run_pmc_extraction(
            estimated_cost_usd=0.20, settings=SimpleNamespace(spaces_bucket="private")
        )
    assert connection.commits == 0
    assert all(sql.lstrip().startswith("SELECT") for sql, _args in cursor.executed)


def test_group_claim_is_bound_and_context_appends_same_identity(
    runtime: tuple[worker.SnowflakePMCExtractionLedger, Cursor, Connection],
) -> None:
    ledger, cursor, connection = runtime
    ledger.validate_group_before_providers()
    paper = ledger.claim_one(900)
    assert paper is not None
    claim_sql, claim_args = next((sql, args) for sql, args in cursor.executed if "LIMIT 1" in sql)
    assert "ARRAY_CONTAINS(TO_VARIANT(p.pmid), PARSE_JSON(%s))" in claim_sql
    assert json.loads(claim_args[2]) == sorted(PMIDS)
    assert claim_args[2] == claim_args[3]
    ledger.record_attempt(paper, "c" * 64, "openai:test", 10, 900)
    details = json.loads(cursor.executed[-1][1][3])["extraction_group"]
    assert details["group_id"] == GROUP
    assert details["pmids"] == sorted(PMIDS)
    assert details["inventory_sha256"] == parse(manifest()).inventory_sha256
    assert datetime.fromisoformat(details["readiness_completed_at"]).tzinfo is not None
    assert connection.commits == 2
    # An authoritative existing attempt blocks another canary for this group.
    cursor.prior_count = 1
    with pytest.raises(GroupGateBlocked, match="already_attempted"):
        ledger.claim_one(900)
    assert connection.commits == 2
    assert connection.rollbacks == 1


def test_approval_drift_between_readiness_and_claim_has_no_writes(
    runtime: tuple[worker.SnowflakePMCExtractionLedger, Cursor, Connection],
) -> None:
    ledger, cursor, connection = runtime
    ledger.validate_group_before_providers()
    cursor.rows[-1] = (PMIDS[-1], "rejected", "decision", True)
    with pytest.raises(GroupGateBlocked):
        ledger.claim_one(900)
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert all(sql.lstrip().startswith("SELECT") for sql, _args in cursor.executed)


def test_outside_inventory_row_rolls_back_before_paper_update(
    runtime: tuple[worker.SnowflakePMCExtractionLedger, Cursor, Connection],
) -> None:
    ledger, cursor, connection = runtime
    ledger.validate_group_before_providers()
    cursor.claim_pmid = "9999"
    with pytest.raises(GroupGateBlocked, match="claimed_paper_in_exact"):
        ledger.claim_one(900)
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert all(sql.lstrip().startswith("SELECT") for sql, _args in cursor.executed)


def test_group_claim_without_successful_readiness_is_closed(
    runtime: tuple[worker.SnowflakePMCExtractionLedger, Cursor, Connection],
) -> None:
    ledger, _cursor, connection = runtime
    with pytest.raises(GroupGateBlocked, match="successful_group_readiness"):
        ledger.claim_one(900)
    assert connection.commits == 0


def test_direct_group_attempt_cannot_bypass_claim(
    runtime: tuple[worker.SnowflakePMCExtractionLedger, Cursor, Connection],
) -> None:
    ledger, cursor, connection = runtime
    ledger.validate_group_before_providers()
    cursor.executed.clear()
    with pytest.raises(GroupGateBlocked, match="validated_group_claim"):
        ledger.record_attempt(SimpleNamespace(pmid=PMIDS[0]), "c" * 64, "openai:test", 10, 900)
    assert cursor.executed == []
    assert connection.commits == 0


def test_legacy_one_paper_ledger_does_not_query_group_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATLAS_EXTRACTION_GROUP_MANIFEST", raising=False)
    monkeypatch.delenv("ATLAS_DISCOVERY_RUN_ID", raising=False)
    monkeypatch.setattr(worker, "connect", lambda _settings: pytest.fail("unexpected group query"))
    worker.SnowflakePMCExtractionLedger(bucket="private").validate_group_before_providers()


def test_malformed_runtime_discovery_identity_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_DISCOVERY_RUN_ID", "secret-sentinel")
    monkeypatch.setenv("ATLAS_EXTRACTION_GROUP_MANIFEST", json.dumps(manifest()))
    with pytest.raises(GroupGateBlocked, match="matching_group_runtime_identity") as failure:
        worker.SnowflakePMCExtractionLedger(bucket="private")
    assert "secret-sentinel" not in str(failure.value)
