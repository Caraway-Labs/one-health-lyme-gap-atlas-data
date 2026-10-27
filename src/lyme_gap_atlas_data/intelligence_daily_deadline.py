"""Terminalize a daily run after the per-source pilot budget expires."""

from __future__ import annotations

from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from .ingestion.intelligence_runtime import (
    DEADLINE_GRACE_SECONDS,
    PROD_SOURCE_DEFINITIONS,
    prod_daily_config_sha256_allowed,
)
from .ingestion.types import FailureCategory
from .intelligence_daily_telemetry import observed
from .settings import PipelineSettings
from .sql_sessions import connect

DAILY_CODE_VERSION = "intelligence-daily-v1"
ERROR_CLASS = "INTELLIGENCE_PILOT_DEADLINE"
DIAGNOSTIC = "PILOT_BUDGET_EXCEEDED"
GRACE_SECONDS = DEADLINE_GRACE_SECONDS


def terminalize_daily_pilot_deadline(ingestion_run_id: str) -> dict[str, Any]:
    """Mark RUNNING daily admission FAILED after budget expiry using a grace connection."""
    settings = PipelineSettings()
    if (
        settings.topx_env != "prod"
        or not settings.enable_production_execution
        or settings.snowflake_database != "ONE_HEALTH_LYME_GAP_ATLAS_PROD"
    ):
        raise PermissionError("INTELLIGENCE_DAILY_DEADLINE_PROD_REQUIRED")
    if ingestion_run_id.strip() != ingestion_run_id or len(ingestion_run_id) != 36:
        raise ValueError("INTELLIGENCE_DAILY_DEADLINE_RUN_ID_REQUIRED")
    snowflake = SnowflakeSettings()
    with observed(), connect(snowflake) as connection, connection.cursor() as cursor:
        cursor.execute(
            "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=%s",
            (GRACE_SECONDS,),
        )
        cursor.execute(
            "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()"
        )
        if cursor.fetchall() != [
            (
                "OH_LYME_PROD_PIPELINE_SVC",
                "OH_LYME_PROD_RUNTIME",
                "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
                "OH_LYME_PROD_INGEST_XS_WH",
            )
        ]:
            raise PermissionError("INTELLIGENCE_DAILY_DEADLINE_RUNTIME_CONTEXT_REQUIRED")
        cursor.execute(
            """SELECT resource_key, status, code_version, config_sha256
            FROM GOVERNANCE.INGESTION_RUNS WHERE ingestion_run_id=%s""",
            (ingestion_run_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise PermissionError("INTELLIGENCE_DAILY_DEADLINE_RUN_NOT_FOUND")
        resource_key, status, code_version, config_sha256 = row
        if (
            status != "RUNNING"
            or code_version != DAILY_CODE_VERSION
            or resource_key not in PROD_SOURCE_DEFINITIONS
            or not prod_daily_config_sha256_allowed(resource_key, config_sha256)
        ):
            raise PermissionError("INTELLIGENCE_DAILY_DEADLINE_SCOPE_REQUIRED")
        cursor.execute(
            """SELECT stage, status FROM GOVERNANCE.INGESTION_RUN_CHECKPOINTS
            WHERE ingestion_run_id=%s ORDER BY updated_at""",
            (ingestion_run_id,),
        )
        checkpoints = cursor.fetchall()
        running_stages = [stage for stage, stage_status in checkpoints if stage_status == "RUNNING"]
        connection.autocommit(False)
        try:
            if running_stages:
                cursor.execute(
                    """UPDATE GOVERNANCE.INGESTION_RUN_CHECKPOINTS
                    SET status='FAILED', failure_category=%s,
                        redacted_diagnostic_code=%s, updated_at=CURRENT_TIMESTAMP(),
                        completed_at=CURRENT_TIMESTAMP()
                    WHERE ingestion_run_id=%s AND status='RUNNING'""",
                    (FailureCategory.DEADLINE.value, DIAGNOSTIC, ingestion_run_id),
                )
                if cursor.rowcount != len(running_stages):
                    raise PermissionError("INTELLIGENCE_DAILY_DEADLINE_CHECKPOINT_MISMATCH")
            cursor.execute(
                """UPDATE GOVERNANCE.INGESTION_RUNS
                SET status='FAILED', completed_at=CURRENT_TIMESTAMP(),
                    error_classification=%s,
                    redacted_error='Daily source pilot budget exceeded before completion.'
                WHERE ingestion_run_id=%s AND status='RUNNING'""",
                (ERROR_CLASS, ingestion_run_id),
            )
            if cursor.rowcount != 1:
                raise PermissionError("INTELLIGENCE_DAILY_DEADLINE_RUN_UPDATE_REQUIRED")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    return {
        "status": "SUCCEEDED",
        "ingestion_run_id": ingestion_run_id,
        "resource_key": resource_key,
        "terminalized_stages": running_stages,
    }
