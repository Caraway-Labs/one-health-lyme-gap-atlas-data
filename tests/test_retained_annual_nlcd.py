"""Bounded retained-cohort admission preserves scientific records and receipts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from lyme_gap_atlas_data.ingestion.adapters import (
    AcquisitionError,
    StreamingSourceAdapter,
    get_adapter,
)
from lyme_gap_atlas_data.ingestion.checkpoints import FileCheckpointStore
from lyme_gap_atlas_data.ingestion.orchestrator import IngestionOrchestrator
from lyme_gap_atlas_data.ingestion.retained_annual_nlcd import RetainedAnnualNLCDAggregateAdapter
from lyme_gap_atlas_data.ingestion.runtime import (
    SnowflakeStageEffects,
    _bulk_lineage_documents,
    _lineage_rows,
)
from lyme_gap_atlas_data.ingestion.source_definition import (
    load_source_definition,
    validate_source_definition,
)
from lyme_gap_atlas_data.ingestion.types import (
    RunState,
    RunStatus,
    Stage,
    StageCheckpoint,
    StageStatus,
    Tier,
)

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = ROOT / "config/sources/mrlc_annual_nlcd_c1v2_2025_demo_cohort.yml"
ARTIFACT = ROOT / "src/lyme_gap_atlas_data/data/annual-nlcd-2025-demo-cohort.json"


def test_exact_fourteen_records_survive_both_canonical_load_shapes() -> None:
    definition = load_source_definition(DEFINITION)
    assert validate_source_definition(definition).ok
    adapter = get_adapter(definition.adapter_kind)
    assert isinstance(adapter, RetainedAnnualNLCDAggregateAdapter)
    acquired = adapter.acquire(definition)
    assert acquired.raw_payload == ARTIFACT.read_bytes()
    assert acquired.artifact_sha256 == definition.extra["aggregate_artifact_sha256"]
    assert acquired.row_count == 14
    records = adapter.normalize(definition, acquired.payload).records
    assert [row["record"] for row in records] == acquired.payload["records"]
    assert not isinstance(adapter, StreamingSourceAdapter)
    state = RunState("fixture-run", definition.resource_key, 1, Tier.A, RunStatus.RUNNING)
    rows = _lineage_rows(definition, state, records)
    assert len(rows) == len({row[0] for row in rows}) == 14
    assert [json.loads(row[8])["record"] for row in rows] == acquired.payload["records"]
    documents = _bulk_lineage_documents(definition, state, [records])
    assert len(documents) == 14
    assert [json.loads(row["payload"])["record"] for row in documents] == acquired.payload[
        "records"
    ]
    assert {row["county_fips"] for row in acquired.payload["records"]} == {"09110", "51013"}
    assert "id" not in acquired.payload["records"][0]  # Do not fabricate a publisher ID.


def test_durable_restart_replays_capture_without_reacquisition(tmp_path: Path) -> None:
    definition = load_source_definition(DEFINITION)
    (tmp_path / ARTIFACT.name).write_bytes(ARTIFACT.read_bytes())
    store = FileCheckpointStore(tmp_path / "checkpoints")
    store.save_partition = Mock(side_effect=AssertionError("DEV-only bulk path selected"))
    adapter = RetainedAnnualNLCDAggregateAdapter()
    first = IngestionOrchestrator(store, fixture_dir=tmp_path, adapter=adapter).run(
        definition, tier=Tier.A, fail_after_stage="NORMALIZE"
    )
    assert first.status is RunStatus.FAILED
    checkpoint = first.checkpoint(Stage.ACQUIRE)
    assert checkpoint and checkpoint.artifact_id
    assert checkpoint.artifact_sha256 == definition.extra["aggregate_artifact_sha256"]
    (tmp_path / ARTIFACT.name).unlink()  # Resume must use retained bytes and normalized rows.
    runner = IngestionOrchestrator(store, fixture_dir=tmp_path, adapter=adapter)
    resumed = runner.resume(first.ingestion_run_id, definition=definition)
    assert resumed.status is RunStatus.SUCCEEDED
    assert (
        runner.resume(first.ingestion_run_id, definition=definition).status is RunStatus.SUCCEEDED
    )
    assert len(store.load_normalized(first.ingestion_run_id) or []) == 14
    store.save_partition.assert_not_called()
    restored = store.load_payload(first.ingestion_run_id)
    assert isinstance(restored, dict)
    assert restored["records"] == json.loads(ARTIFACT.read_bytes())["records"]


@pytest.mark.parametrize("mutation", ["value", "duplicate", "revision", "distribution", "county"])
def test_mutated_retained_capture_rejected_even_with_new_outer_pin(
    tmp_path: Path, mutation: str
) -> None:
    definition = load_source_definition(DEFINITION)
    payload = json.loads(ARTIFACT.read_bytes())
    if mutation == "value":
        payload["records"][0]["value"] = None
    elif mutation == "duplicate":
        payload["records"][1] = payload["records"][0]
    elif mutation == "revision":
        payload["calculation_lineage"]["code_revision"] = "unreviewed"
    elif mutation == "distribution":
        payload["distribution"] = "USGS_S3_TILES"
    else:
        payload["records"][0]["county_fips"] = "09003"
    body = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    )
    (tmp_path / ARTIFACT.name).write_bytes(body)
    changed = replace(
        definition,
        extra={**definition.extra, "aggregate_artifact_sha256": hashlib.sha256(body).hexdigest()},
    )
    with pytest.raises(AcquisitionError, match="integrity"):
        RetainedAnnualNLCDAggregateAdapter().acquire(changed, fixture_dir=tmp_path)


@pytest.mark.parametrize("method", ["load", "load_partition_batch", "load_bulk_batch"])
@pytest.mark.parametrize("receipt", ["absent", "id_only", "wrong_checksum"])
def test_load_fails_before_connection_when_revision_receipt_is_invalid(
    method: str, receipt: str
) -> None:
    definition = load_source_definition(DEFINITION)
    adapter = RetainedAnnualNLCDAggregateAdapter()
    records = adapter.normalize(definition, adapter.acquire(definition).payload).records
    state = RunState("fixture-run", definition.resource_key, 1, Tier.A, RunStatus.RUNNING)
    if receipt != "absent":
        state.stages.append(
            StageCheckpoint(
                Stage.ACQUIRE,
                StageStatus.COMPLETED,
                artifact_id="captured",
                artifact_sha256=None if receipt == "id_only" else "0" * 64,
            )
        )
    effects = object.__new__(SnowflakeStageEffects)
    effects._connection_factory = Mock(side_effect=AssertionError("No writes without receipt"))
    with pytest.raises(ValueError, match="Retained aggregate"):
        getattr(effects, method)(definition, state, records if method == "load" else [records])
    effects._connection_factory.assert_not_called()
