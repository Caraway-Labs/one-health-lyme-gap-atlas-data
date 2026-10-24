"""Offline checks for the bounded cdc-mmwr DEV bulk LOAD rehearsal."""

from __future__ import annotations

from pathlib import Path

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
    text = (ROOT / ".github/workflows/run-ingestion.yml").read_text(encoding="utf-8")
    assert "- intelligence-cdc-mmwr-rehearsal" in text
    assert "rehearse_intelligence_cdc_mmwr_dev.py" in text
    assert 'test "$SOURCE_DEFINITION" = "config/sources/intelligence_cdc_mmwr.yml"' in text
    assert "inputs.operation == 'intelligence-cdc-mmwr-rehearsal' && 'dev'" in text
    block = text.rsplit(
        'elif [ "${{ inputs.operation }}" = "intelligence-cdc-mmwr-rehearsal" ]; then', 1
    )[1]
    pilot_branch = 'elif [ "${{ inputs.operation }}" = "nclimgrid-pilot-measurement" ]; then'
    block = block.split(pilot_branch, 1)[0]
    assert "atlas-data source run" not in block
    assert "apply-migrations" not in block
