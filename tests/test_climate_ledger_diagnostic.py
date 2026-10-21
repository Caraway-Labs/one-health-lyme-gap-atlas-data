import copy
import json
import runpy
from datetime import UTC, datetime

import pytest
from test_climate_metadata_preflight import HELPERS, Cursor, budget, responses

from lyme_gap_atlas_data import climate_metadata_preflight as preflight
from lyme_gap_atlas_data.migrations import load_migrations


def records():
    item = next(item for item in load_migrations() if item.version == "V136")
    return [
        {
            "version": item.version,
            "filename": item.filename,
            "sha256": item.sha256,
            "applied_at": datetime(2026, 10, 1, tzinfo=UTC),
        }
    ]


@pytest.mark.parametrize("kind", ["valid", "identical", "conflicting", "unexpected"])
def test_ledger_evidence_preserves_every_record(kind):
    rows = records()
    if kind in {"identical", "conflicting"}:
        rows.append(copy.deepcopy(rows[0]))
        rows[1]["applied_at"] = datetime(2026, 10, 2, tzinfo=UTC)
    if kind == "conflicting":
        rows[1]["sha256"] = "0" * 64
    if kind == "unexpected":
        rows[0]["version"] = "V999"
    evidence = preflight.ledger_evidence(rows)
    assert evidence["row_count"] == len(rows) == len(evidence["records"])
    assert evidence["integrity"] == (
        "SOURCE_IDENTITIES_MATCH_ONLY" if kind == "valid" else "BLOCKED"
    )
    if kind in {"identical", "conflicting"}:
        duplicate = evidence["duplicates"][0]
        assert duplicate["row_count"] == 2
        assert duplicate["classification"] == (
            "IDENTICAL_SOURCE_ENTRIES" if kind == "identical" else "CONFLICTING_SOURCE_ENTRIES"
        )
        assert duplicate["records"][0]["applied_at"] != duplicate["records"][1]["applied_at"]
    if kind == "unexpected":
        assert evidence["records"][0]["canonical_comparison"] == "UNEXPECTED_VERSION"


def run_diagnostic(rows):
    data = responses()
    cursor = Cursor([data[0], data[1], rows])
    report = preflight.receipt("reviewed-head")
    evidence = preflight.prepare_evidence(json.dumps(budget(standard=True, price=2)), report)
    report = preflight.inspect_ledger(cursor, report, {**HELPERS, "budget_evidence": evidence})
    return report, cursor


def test_diagnostic_exact_three_statements_and_no_acceptance():
    rows = records() * 2
    report, cursor = run_diagnostic(rows)
    sql = preflight.statements()
    assert cursor.calls == [sql[0], sql[1], sql[8]]
    assert report["status"] == "PASS" and report["ledger_evidence"]["integrity"] == "BLOCKED"
    assert report["pending_migrations"] is None and report["sole_v147_ready"] is False
    assert len(report["checks"]) == 3 and report["statements_executed"] == 3
    assert "metadata_prerequisites_pass" not in report


def test_truncated_results_never_claim_completeness():
    report, cursor = run_diagnostic(records() * 151)
    assert len(cursor.calls) == 3 and report["status"] == "BLOCKED"
    assert report["checks"][-1]["category"] == "LEDGER_RESULT_TRUNCATED"
    assert report["ledger_evidence"]["complete"] is False


def test_invalid_result_column_shape_is_not_duplicate_ledger_evidence():
    rows = records()
    rows[0]["secret"] = "must-not-leak"
    report, _ = run_diagnostic(rows)
    assert report["checks"][-1]["category"] == "LEDGER_COLUMNS"
    assert "must-not-leak" not in json.dumps(report)


def test_failed_identity_never_reads_ledger():
    data = responses()
    data[0][0]["account"] = "WRONG_ACCOUNT"
    cursor = Cursor([data[0]])
    report = preflight.receipt("reviewed-head")
    evidence = preflight.prepare_evidence(json.dumps(budget(standard=True, price=2)), report)
    report = preflight.inspect_ledger(cursor, report, {**HELPERS, "budget_evidence": evidence})
    assert report["status"] == "BLOCKED" and len(cursor.calls) == 1


def test_entrypoint_closes_without_transaction_or_retry(monkeypatch, capsys):
    main = runpy.run_path(str(preflight.ROOT / "scripts/preflight_climate_v147_dev.py"))["main"]

    data = responses()
    cursor = Cursor([data[0], data[1], records() * 2])
    closed = []

    class Connection:
        def cursor(self):
            class Context:
                def __enter__(self):
                    return cursor

                def __exit__(self, *args):
                    pass

            return Context()

        def close(self, *, retry):
            closed.append(retry)

    monkeypatch.setattr(
        runpy, "run_path", lambda path: {**HELPERS, "bounded_connection": Connection}
    )
    monkeypatch.setenv("LEDGER_DIAGNOSTIC_ONLY", "true")
    monkeypatch.setenv(
        "JANUARY_DIAGNOSTIC_BUDGET_EVIDENCE", json.dumps(budget(standard=True, price=2))
    )
    main()
    report = json.loads(capsys.readouterr().out)
    assert closed == [False] and len(cursor.calls) == 3
    assert report["close_state"] == "CLOSED_NO_RETRY"
    assert report["ledger_evidence"]["integrity"] == "BLOCKED"
