"""Shared offline seams for intelligence storage bulk LOAD tests."""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _fake_intelligence_bulk_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    def stage(cursor: Any, *, run_id: str, kind: str, rows: list[dict[str, Any]]) -> str:
        reference = f"@GOVERNANCE.INGESTION_BULK_STAGE/{run_id}/{kind}/bulk-test.json.gz"
        cursor.connection.ledger.bulk_rows = rows
        cursor.connection.ledger.bulk_transport = reference
        return reference

    monkeypatch.setattr(
        "lyme_gap_atlas_data.intelligence_bulk_write.stage_json_rows",
        stage,
    )
    monkeypatch.setattr(
        "lyme_gap_atlas_data.ingestion.bulk_stage.remove_transport",
        lambda _cursor, _source: None,
    )
