"""Run the bounded DEV cdc-mmwr intelligence bulk LOAD rehearsal."""

from __future__ import annotations

from lyme_gap_atlas_data.ingestion.intelligence_dev_rehearsal import (
    emit_rehearsal_report,
    rehearse_cdc_mmwr_dev,
)
from lyme_gap_atlas_data.settings import PipelineSettings


def main() -> None:
    settings = PipelineSettings()
    if settings.topx_env != "dev":
        raise SystemExit("INTELLIGENCE_REHEARSAL_DEV_ONLY")
    if settings.snowflake_database != "ONE_HEALTH_LYME_GAP_ATLAS_DEV":
        raise SystemExit("INTELLIGENCE_REHEARSAL_DATABASE_MISMATCH")
    payload = rehearse_cdc_mmwr_dev()
    emit_rehearsal_report(payload)
    if payload.get("status") != "SUCCEEDED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
