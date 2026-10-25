"""Offline checks for the bounded cdc-mmwr DEV bulk LOAD rehearsal."""

from __future__ import annotations

from pathlib import Path

from semantic_contracts import (
    definition_paths_by_source_id,
    load_workflow,
    trigger_map,
    workflow_runs,
)

from lyme_gap_atlas_data.ingestion.intelligence_dev_rehearsal import (
    permission_guidance_for_error,
)

ROOT = Path(__file__).parents[1]


def test_put_permission_error_reports_stage_grant() -> None:
    guidance = permission_guidance_for_error(
        "SQL access control error: Insufficient privileges to operate on stage "
        "'GOVERNANCE.INGESTION_BULK_STAGE'."
    )
    assert guidance is not None
    assert "INGESTION_BULK_STAGE" in guidance
    assert "OH_LYME_DEV_RUNTIME" in guidance


def test_merge_permission_error_reports_table_grants() -> None:
    guidance = permission_guidance_for_error(
        "SQL compilation error: insufficient privileges to MERGE into "
        "CONFORMED.INTELLIGENCE_ITEM_REVISIONS"
    )
    assert guidance is not None
    assert "INTELLIGENCE_ITEM_REVISIONS" in guidance


def test_rehearsal_workflow_is_dev_only_and_fixed_definition() -> None:
    document = load_workflow(ROOT / ".github/workflows/run-ingestion.yml")
    operation = trigger_map(document)["workflow_dispatch"]["inputs"]["operation"]
    assert "intelligence-cdc-mmwr-rehearsal" in operation["options"]
    environment = document["jobs"]["ingest"]["environment"]
    assert "intelligence-cdc-mmwr-rehearsal" in environment
    assert "'dev'" in environment
    definition = definition_paths_by_source_id()["cdc-mmwr"]
    runs = "\n".join(workflow_runs(document))
    assert f'test "$SOURCE_DEFINITION" = "{definition}"' in runs
    assert "rehearse_intelligence_cdc_mmwr_dev.py" in runs
    block = runs.rsplit(
        'elif [ "${{ inputs.operation }}" = "intelligence-cdc-mmwr-rehearsal" ]; then', 1
    )[1]
    pilot_branch = 'elif [ "${{ inputs.operation }}" = "nclimgrid-pilot-measurement" ]; then'
    block = block.split(pilot_branch, 1)[0]
    assert "atlas-data source run" not in block
    assert "apply-migrations" not in block


def test_checkpoint_detail_reads_real_run_state_stages() -> None:
    from lyme_gap_atlas_data.ingestion.intelligence_dev_rehearsal import _checkpoint_detail
    from lyme_gap_atlas_data.ingestion.types import (
        RunState,
        RunStatus,
        Stage,
        StageCheckpoint,
        StageStatus,
        Tier,
    )

    state = RunState(
        ingestion_run_id="r",
        resource_key="cdc-mmwr",
        source_definition_version=1,
        tier=Tier.B,
        status=RunStatus.RUNNING,
        stages=[StageCheckpoint(stage=Stage.LOAD, status=StageStatus.COMPLETED, detail={"a": 1})],
    )
    assert _checkpoint_detail(state, Stage.LOAD) == {"a": 1}
    assert _checkpoint_detail(state, Stage.PUBLISH_STAGE) == {}
