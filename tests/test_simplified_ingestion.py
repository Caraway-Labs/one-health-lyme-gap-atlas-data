"""Fast tests for simplified ingestion (Epic #223)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lyme_gap_atlas_data.ingestion import (
    AdapterKind,
    FileCheckpointStore,
    IngestionOrchestrator,
    InMemoryCheckpointStore,
    LiteratureStage,
    LiteratureWorkQueue,
    Stage,
    StageStatus,
    Tier,
    explain_run,
    load_source_definition,
    starter_definition_yaml,
    validate_source_definition,
)
from lyme_gap_atlas_data.ingestion.source_definition import source_definition_from_mapping

REPO = Path(__file__).resolve().parents[1]
X5J9 = REPO / "config" / "sources" / "cdc_x5j9_wybp.yml"
TICK = REPO / "config" / "sources" / "cdc_tick_ixodes_county_status.yml"
X5J9_FIXTURES = REPO / "tests" / "fixtures" / "sources" / "cdc_lyme_x5j9_wybp"
TICK_FIXTURES = REPO / "tests" / "fixtures" / "sources" / "cdc_tick_ixodes_county_status"


def test_load_and_validate_x5j9_definition() -> None:
    definition = load_source_definition(X5J9)
    assert definition.adapter_kind is AdapterKind.SOCRATA
    assert definition.resource_key == "cdc_lyme_x5j9_wybp"
    result = validate_source_definition(definition)
    assert result.ok, result.to_dict()


def test_load_and_validate_tick_definition() -> None:
    definition = load_source_definition(TICK)
    assert definition.adapter_kind is AdapterKind.HTTP_XLSX
    result = validate_source_definition(definition)
    assert result.ok, result.to_dict()


def test_invalid_definition_fails_locally() -> None:
    definition = source_definition_from_mapping(
        {
            "resource_key": "bad",
            "adapter_kind": "socrata",
            "endpoint_template": "http://insecure.example/resource.json",
            "deterministic_order_clause": "",
            "incremental_strategy": "FULL_REFRESH",
            "geography_semantics": "",
            "temporal_semantics": "",
        }
    )
    result = validate_source_definition(definition)
    assert not result.ok
    codes = {issue.code for issue in result.issues}
    assert "ENDPOINT_SCHEME" in codes
    assert "ORDER_CLAUSE_REQUIRED" in codes


def test_x5j9_fixture_run_succeeds() -> None:
    definition = load_source_definition(X5J9)
    orch = IngestionOrchestrator(
        store=InMemoryCheckpointStore(),
        fixture_dir=X5J9_FIXTURES,
    )
    state = orch.run(definition, tier=Tier.A)
    assert state.status.value == "SUCCEEDED"
    assert all(item.status is StageStatus.COMPLETED for item in state.stages)
    acquire = state.checkpoint(Stage.ACQUIRE)
    assert acquire is not None
    assert acquire.artifact_sha256


def test_resume_skips_completed_acquire(tmp_path: Path) -> None:
    definition = load_source_definition(X5J9)
    store = FileCheckpointStore(tmp_path / "runs")
    orch = IngestionOrchestrator(store=store, fixture_dir=X5J9_FIXTURES)
    failed = orch.run(definition, tier=Tier.A, fail_after_stage="ACQUIRE")
    assert failed.status.value == "FAILED"
    acquire = failed.checkpoint(Stage.ACQUIRE)
    validate = failed.checkpoint(Stage.VALIDATE)
    assert acquire is not None and acquire.status is StageStatus.COMPLETED
    assert validate is not None and validate.status is StageStatus.FAILED
    acquire_attempts = acquire.attempt_count

    resumed = orch.resume(failed.ingestion_run_id, definition=definition)
    assert resumed.status.value == "SUCCEEDED"
    assert resumed.checkpoint(Stage.ACQUIRE) is not None
    assert resumed.checkpoint(Stage.ACQUIRE).attempt_count == acquire_attempts
    assert resumed.checkpoint(Stage.VALIDATE) is not None
    assert resumed.checkpoint(Stage.VALIDATE).status is StageStatus.COMPLETED


def test_tick_fixture_run_succeeds() -> None:
    definition = load_source_definition(TICK)
    orch = IngestionOrchestrator(
        store=InMemoryCheckpointStore(),
        fixture_dir=TICK_FIXTURES,
    )
    state = orch.run(definition, tier=Tier.A)
    assert state.status.value == "SUCCEEDED"


def test_starter_definition_yaml_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "example.yml"
    path.write_text(
        starter_definition_yaml(resource_key="example_source", adapter_kind=AdapterKind.SOCRATA)
    )
    definition = load_source_definition(path)
    assert definition.resource_key == "example_source"
    assert validate_source_definition(definition).ok


def test_explain_run_guidance() -> None:
    definition = load_source_definition(X5J9)
    orch = IngestionOrchestrator(store=InMemoryCheckpointStore(), fixture_dir=X5J9_FIXTURES)
    failed = orch.run(definition, tier=Tier.A, fail_after_stage="ACQUIRE")
    explanation = explain_run(failed)
    assert explanation["failed_stage"] == "VALIDATE"
    assert "guidance" in explanation
    assert "ACQUIRE" in explanation["completed_stages"]


def test_literature_queue_independent_retries() -> None:
    queue = LiteratureWorkQueue()
    queue.enqueue("wi-1", pmid="12345678")
    failed = queue.advance("wi-1", fail_at=LiteratureStage.EXTRACT)
    extract = next(stage for stage in failed.stages if stage.stage is LiteratureStage.EXTRACT)
    assert extract.status.value == "FAILED"
    jats = next(stage for stage in failed.stages if stage.stage is LiteratureStage.JATS_ACQUIRE)
    assert jats.status.value == "COMPLETED"

    recovered = queue.retry_stage("wi-1", LiteratureStage.EXTRACT)
    extract = next(stage for stage in recovered.stages if stage.stage is LiteratureStage.EXTRACT)
    publish = next(stage for stage in recovered.stages if stage.stage is LiteratureStage.PUBLISH)
    assert extract.status.value == "COMPLETED"
    assert publish.status.value == "COMPLETED"
    assert jats.attempt_count == 1


def test_literature_license_exception_does_not_block_model() -> None:
    queue = LiteratureWorkQueue()
    queue.enqueue("wi-2", pmid="999")
    item = queue.advance("wi-2", license_ambiguous=True)
    assert item.license_exception is True
    admit = next(stage for stage in item.stages if stage.stage is LiteratureStage.PMCID_OA_ADMIT)
    assert admit.status.value == "EXCEPTION_REVIEW"


def test_tier_c_requires_protection() -> None:
    definition = load_source_definition(X5J9)
    orch = IngestionOrchestrator(store=InMemoryCheckpointStore(), fixture_dir=X5J9_FIXTURES)
    with pytest.raises(PermissionError):
        orch.run(definition, tier=Tier.C, dry_run=False)
