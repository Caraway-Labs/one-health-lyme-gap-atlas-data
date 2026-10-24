"""Bulk intelligence load statement bounds and pilot failure marking."""

from __future__ import annotations

from typing import Any

import pytest
from test_intelligence_feed import approved
from test_intelligence_storage import Cursor as LedgerCursor
from test_intelligence_storage import Ledger, item, write

from lyme_gap_atlas_data.ingestion import IngestionOrchestrator
from lyme_gap_atlas_data.intelligence_storage import WriteReceipt


@pytest.fixture(autouse=True)
def _fake_intelligence_bulk_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    def stage(cursor: Any, *, run_id: str, kind: str, rows: list[dict[str, Any]]) -> str:
        reference = f"@GOVERNANCE.INGESTION_BULK_STAGE/{run_id}/{kind}/bulk-test.json.gz"
        cursor.connection.ledger.bulk_rows = rows
        return reference

    monkeypatch.setattr(
        "lyme_gap_atlas_data.intelligence_bulk_write.stage_json_rows",
        stage,
    )
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.bulk_stage.remove_transport",
        lambda _cursor, _source: None,
    )


def test_bulk_write_250_items_uses_bounded_statement_count() -> None:
    database = Ledger()
    source = approved()
    source["limits"]["maximum_items"] = 250
    database.sources = [source]
    database.pin("fixture-run", "fixture-artifact", source, "2026-10-01T00:00:00Z")
    items = [item(source=source, title=f"Publication {index}") for index in range(250)]
    counts = [0]
    original = LedgerCursor.execute

    def counted(self: LedgerCursor, statement: str, params: tuple[Any, ...] = ()) -> None:
        counts[0] += 1
        return original(self, statement, params)

    LedgerCursor.execute = counted  # type: ignore[method-assign]
    try:
        assert write(database, items) == WriteReceipt(250, 250, 0)
    finally:
        LedgerCursor.execute = original  # type: ignore[method-assign]
    assert counts[0] <= 20


def test_bulk_write_rerun_is_zero_inserts() -> None:
    database = Ledger()
    source = approved()
    source["limits"]["maximum_items"] = 250
    database.sources = [source]
    database.pin("fixture-run", "fixture-artifact", source, "2026-10-01T00:00:00Z")
    document = item(source=source)
    batch = [document] * 250
    assert write(database, batch) == WriteReceipt(1, 1, 249)
    assert write(database, batch) == WriteReceipt(0, 0, 250)


def test_pilot_query_limit_marks_run_failed() -> None:
    from lyme_gap_atlas_data.ingestion.types import (
        RunState,
        RunStatus,
        Stage,
        StageCheckpoint,
        StageStatus,
        Tier,
    )

    orchestrator = IngestionOrchestrator()
    run = RunState(
        ingestion_run_id="00000000-0000-4000-8000-000000000001",
        resource_key="cdc-mmwr",
        source_definition_version=2,
        tier=Tier.C,
        status=RunStatus.RUNNING,
        stages=[StageCheckpoint(stage=Stage.LOAD, status=StageStatus.RUNNING)],
        dry_run=False,
        next_action="run",
    )
    failed = orchestrator._pilot_failure(run, PermissionError("INTELLIGENCE_PILOT_QUERY_LIMIT"))
    assert failed.status is RunStatus.FAILED
    assert (
        failed.checkpoint(Stage.LOAD).redacted_diagnostic_code == "INTELLIGENCE_PILOT_QUERY_LIMIT"
    )
