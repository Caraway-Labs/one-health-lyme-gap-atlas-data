"""Fail-closed recovery of DATA443's one retained, pre-output January run."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from .climate_prod_binding import approved_capture_binding, verify_execution_resource
from .climate_prod_manifest import PLANNED_RUN
from .climate_publication import NOAA_SHA, TIGER_SHA
from .ingestion.artifact_replay import ArtifactMember, validate_members
from .ingestion.types import (
    FailureCategory,
    RunState,
    RunStatus,
    SourceDefinition,
    Stage,
    StageStatus,
    Tier,
)
from .migrations import load_migrations
from .sql_sessions import connect

NOAA_VERSION = "94f08af7-8fa7-4452-987a-a7229f4b640d"
NOAA_DECISION = "0de41cea-7fd0-4b9b-bd79-31fb2f879dde"
TIGER_VERSION = "e215a4a6-bbba-4483-8c8b-fd5eee5531b3"
TIGER_DECISION = "8eba4a9b-76e1-4ccd-8a71-88e25048d37b"


def require_recovery_state(state: RunState, definition: SourceDefinition) -> None:
    """No broad resume admission, completed outputs, second attempt or fixture."""
    stages = (
        Stage.ACQUIRE,
        Stage.VALIDATE,
        Stage.NORMALIZE,
        Stage.LOAD,
        Stage.QUALITY,
        Stage.PUBLISH_STAGE,
    )
    if (
        os.environ.get("JANUARY_NORMALIZE_RECOVERY") != "true"
        or os.environ.get("TOPX_ENV") != "prod"
        or os.environ.get("ENABLE_PRODUCTION_EXECUTION") != "true"
        or os.environ.get("ATLAS_JANUARY_PROD_SESSION") != "true"
        or state.ingestion_run_id != PLANNED_RUN
        or state.status is not RunStatus.FAILED
        or state.dry_run
        or state.tier is not Tier.C
        or state.resource_key != "noaa_nclimgrid_daily_202501"
        or definition.resource_key != state.resource_key
        or definition.definition_version != state.source_definition_version
        or definition.extra.get("noaa_sha256") != NOAA_SHA
        or definition.extra.get("tiger_sha256") != TIGER_SHA
        or tuple(item.stage for item in state.stages) != stages
        or state.next_action != "resume:NORMALIZE"
    ):
        raise PermissionError("JANUARY_RECOVERY_SCOPE")
    for index, item in enumerate(state.stages):
        expected = (
            StageStatus.COMPLETED
            if index < 2
            else (StageStatus.FAILED if index == 2 else StageStatus.PENDING)
        )
        if item.status is not expected or item.attempt_count != (1 if index < 3 else 0):
            raise PermissionError("JANUARY_RECOVERY_CHECKPOINT")
    failed = state.stages[2]
    if failed.failure_category is not FailureCategory.WAREHOUSE:
        raise PermissionError("JANUARY_RECOVERY_FAILURE")
    if (
        failed.redacted_diagnostic_code != "PROGRAMMINGERROR"
        or failed.next_action != "resume:NORMALIZE"
    ):
        raise PermissionError("JANUARY_RECOVERY_FAILURE")
    members = validate_members(
        ArtifactMember.from_dict(item) for item in state.stages[0].detail["artifacts"]
    )
    if (
        len(members) != 2
        or {m.sha256 for m in members} != {NOAA_SHA, TIGER_SHA}
        or any(m.ingestion_run_id != PLANNED_RUN for m in members)
    ):
        raise PermissionError("JANUARY_RECOVERY_ARTIFACTS")


def require_runtime_stage(cursor: Any) -> None:
    """Inspect the actual service's stage; never test by PUT or change grants."""
    cursor.execute("SHOW STAGES LIKE 'INGESTION_BULK_STAGE' IN SCHEMA GOVERNANCE")
    columns = [str(col[0]).lower() for col in cursor.description]
    stages = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    stages = [row for row in stages if row.get("name") == "INGESTION_BULK_STAGE"]
    if (
        len(stages) != 1
        or not str(stages[0].get("type", "")).startswith("INTERNAL")
        or stages[0].get("url")
    ):
        raise PermissionError("JANUARY_RECOVERY_INTERNAL_STAGE")
    cursor.execute("DESC STAGE GOVERNANCE.INGESTION_BULK_STAGE")
    rows = cursor.fetchall()
    properties = {(str(r[0]), str(r[1])): str(r[3]).upper() for r in rows}
    required = {
        ("STAGE_FILE_FORMAT", "TYPE"): "JSON",
        ("STAGE_FILE_FORMAT", "COMPRESSION"): "AUTO",
        ("STAGE_FILE_FORMAT", "MULTI_LINE"): "FALSE",
    }
    if any(properties.get(key) != value for key, value in required.items()):
        raise PermissionError("JANUARY_RECOVERY_STAGE_CONFIGURATION")
    cursor.execute("SHOW GRANTS ON STAGE GOVERNANCE.INGESTION_BULK_STAGE")
    columns = [str(col[0]).lower() for col in cursor.description]
    grants = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    privileges = {
        r.get("privilege")
        for r in grants
        if r.get("grantee_name") == "OH_LYME_PROD_RUNTIME"
        and r.get("granted_on") == "STAGE"
        and r.get("granted_to") == "ROLE"
    }
    if not {"READ", "WRITE"} <= privileges:
        raise PermissionError("JANUARY_RECOVERY_STAGE_ACCESS")


def verified_recovery_definition(state: RunState, definition: SourceDefinition) -> SourceDefinition:
    require_recovery_state(state, definition)
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        verify_execution_resource(cursor, "OH_LYME_PROD_RUNTIME", "OH_LYME_PROD_PIPELINE_SVC")
        migration = next(item for item in load_migrations() if item.version == "V153")
        cursor.execute(
            "SELECT filename,sha256 FROM GOVERNANCE.SCHEMA_MIGRATIONS WHERE version='V153'"
        )
        if cursor.fetchall() != [(migration.filename, migration.sha256)]:
            raise PermissionError("JANUARY_RECOVERY_MIGRATION")
        require_runtime_stage(cursor)
        approvals = approved_capture_binding(
            cursor, NOAA_VERSION, NOAA_DECISION, recovery_run_id=PLANNED_RUN
        )
        if (approvals["tiger"]["source_version_id"], approvals["tiger"]["decision_id"]) != (
            TIGER_VERSION,
            TIGER_DECISION,
        ):
            raise PermissionError("JANUARY_RECOVERY_APPROVAL_CHANGED")
        cursor.execute(
            "SELECT resource_key,COUNT(*) FROM GOVERNANCE.DATA_SOURCE_VERSIONS "
            "WHERE resource_key IN (%s,%s) AND retired_at IS NULL GROUP BY resource_key",
            ("noaa_nclimgrid_daily_202501", "census_tiger_2025_us_county_analysis"),
        )
        if set(cursor.fetchall()) != {
            ("noaa_nclimgrid_daily_202501", 1),
            ("census_tiger_2025_us_county_analysis", 1),
        }:
            raise PermissionError("JANUARY_RECOVERY_ACTIVE_APPROVALS")
        for table in (
            "GOVERNANCE.INGESTION_RUN_NORMALIZED_PARTITIONS",
            "GOVERNANCE.INGESTION_RUN_PARTITION_COMPLETIONS",
            "GOVERNANCE.INGESTION_PUBLICATIONS",
            "STAGING.GOVERNED_SOURCE_RECORDS",
            "CONFORMED.GOVERNED_SOURCE_RECORDS",
            "RAW.GOVERNED_SOURCE_RECORDS",
            "GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS",
        ):
            cursor.execute(
                f"SELECT COUNT(*) FROM {table} WHERE ingestion_run_id=%s", (PLANNED_RUN,)
            )
            if cursor.fetchone() != (0,):
                raise PermissionError("JANUARY_RECOVERY_OUTPUT_EXISTS")
    return replace(definition, extra={**definition.extra, "source_approvals": approvals})
