"""Bounded DEV Snowflake rehearsal for intelligence feed bulk LOAD."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from ..settings import PipelineSettings
from .intelligence_runtime import (
    DAILY_RECEIPTS,
    DAILY_SOURCE_WATCHDOG_SECONDS,
    RECEIPTS,
    PilotBudget,
    _Connection,
    compose_pilot,
    pilot_watchdog,
)
from .source_definition import load_source_definition
from .types import RunStatus, Stage, Tier

CDC_MMWR_DEFINITION = Path("config/sources/intelligence_cdc_mmwr.yml")
CDC_MMWR_SOURCE_ID = "cdc-mmwr"

_STAGE_PUT = re.compile(r"\bPUT\b", re.IGNORECASE)
_STAGE_MERGE = re.compile(r"\bMERGE\b", re.IGNORECASE)
_STAGE_PARSE_JSON = re.compile(r"\bPARSE_JSON\b", re.IGNORECASE)


@dataclass(frozen=True)
class RehearsalPass:
    attempt: int
    run_id: str
    status: str
    statement_count: int
    stage_timings: list[dict[str, Any]]
    record_count: int
    revisions_inserted: int
    captures_inserted: int
    captures_replayed: int
    publish_status: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "run_id": self.run_id,
            "status": self.status,
            "statement_count": self.statement_count,
            "stage_timings": self.stage_timings,
            "record_count": self.record_count,
            "revisions_inserted": self.revisions_inserted,
            "captures_inserted": self.captures_inserted,
            "captures_replayed": self.captures_replayed,
            "publish_status": self.publish_status,
        }


def permission_guidance_for_error(message: str, sqlstate: str | None = None) -> str | None:
    """Map a Snowflake failure to the reviewed grant surface; no credential workarounds."""
    upper = message.upper()
    if (_STAGE_PUT.search(message) or "INGESTION_BULK_STAGE" in upper) and (
        "403" in message or "ACCESS DENIED" in upper or "INSUFFICIENT" in upper
    ):
        return (
            "Grant READ, WRITE on stage GOVERNANCE.INGESTION_BULK_STAGE to role "
            "OH_LYME_DEV_RUNTIME (see migrations/V117__ingestion_bulk_transport_stage.sql)."
        )
    if (_STAGE_MERGE.search(message) or _STAGE_PARSE_JSON.search(message)) and (
        "ACCESS DENIED" in upper or "INSUFFICIENT" in upper or "OBJECT DOES NOT EXIST" in upper
    ):
        return (
            "Verify OH_LYME_DEV_RUNTIME has INSERT (and SELECT for conflict checks) on "
            "CONFORMED.INTELLIGENCE_ITEM_REVISIONS and GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES, "
            "plus USAGE on the GOVERNANCE and CONFORMED schemas and the DEV warehouse."
        )
    if sqlstate == "42501":
        return (
            "Operation lacks privilege under the current role. Review SHOW GRANTS TO ROLE "
            "OH_LYME_DEV_RUNTIME for the failing object named in the Snowflake error."
        )
    return None


def _snowflake_error_fields(error: BaseException) -> tuple[str, str | None]:
    message = str(error)
    sqlstate = getattr(error, "sqlstate", None)
    if sqlstate is None and error.__cause__ is not None:
        sqlstate = getattr(error.__cause__, "sqlstate", None)
    return message, sqlstate


def _checkpoint_detail(state: Any, stage: Stage) -> dict[str, Any]:
    for checkpoint in state.checkpoints:
        if checkpoint.stage is stage and checkpoint.detail:
            detail = checkpoint.detail
            if isinstance(detail, dict):
                return detail
    return {}


def _rehearsal_pilot(definition: Any, *, budget_seconds: int) -> tuple[Any, Any]:
    """Compose the MMWR pilot using the highest registered DEV source version."""
    settings = PipelineSettings()
    budget = PilotBudget(seconds=budget_seconds)
    receipts = json.loads(RECEIPTS.read_text(encoding="utf-8"))["receipts"]
    version = 1
    with connect(SnowflakeSettings()) as raw, _Connection(raw, budget).cursor() as cursor:
        cursor.execute("ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=30")
        cursor.execute(
            "SELECT registry_version FROM GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS "
            "WHERE source_id=%s ORDER BY registry_version DESC LIMIT 1",
            (CDC_MMWR_SOURCE_ID,),
        )
        rows = cursor.fetchall()
        if len(rows) == 1 and rows[0][0] in {1, 2}:
            version = rows[0][0]
    if version == 2:
        receipts = receipts + json.loads(DAILY_RECEIPTS.read_text(encoding="utf-8"))["receipts"]
    return compose_pilot(
        definition,
        receipts=receipts,
        settings=settings,
        connection_factory=lambda: connect(SnowflakeSettings()),
        budget=budget,
        registry_version=version,
    )


def run_rehearsal_pass(attempt: int) -> RehearsalPass:
    """Run one full ACQUIRE→PUBLISH intelligence pilot against DEV Snowflake."""
    loaded = load_source_definition(CDC_MMWR_DEFINITION)
    if loaded.source_id != CDC_MMWR_SOURCE_ID:
        raise ValueError("INTELLIGENCE_REHEARSAL_DEFINITION_MISMATCH")
    with pilot_watchdog(seconds=DAILY_SOURCE_WATCHDOG_SECONDS):
        orchestrator, definition = _rehearsal_pilot(loaded, budget_seconds=900)
        state = orchestrator.run(definition, tier=Tier.B, dry_run=False)
    budget = orchestrator.pilot_budget
    if budget is None:
        raise RuntimeError("INTELLIGENCE_REHEARSAL_BUDGET_MISSING")
    load_detail = _checkpoint_detail(state, Stage.LOAD)
    publish_detail = _checkpoint_detail(state, Stage.PUBLISH_STAGE)
    return RehearsalPass(
        attempt=attempt,
        run_id=state.ingestion_run_id,
        status=state.status.value,
        statement_count=budget.queries,
        stage_timings=budget.timing_report(),
        record_count=int(load_detail.get("record_count", 0)),
        revisions_inserted=int(load_detail.get("revisions_inserted", 0)),
        captures_inserted=int(load_detail.get("captures_inserted", 0)),
        captures_replayed=int(load_detail.get("captures_replayed", 0)),
        publish_status=publish_detail.get("status") if publish_detail else None,
    )


def rehearse_cdc_mmwr_dev() -> dict[str, Any]:
    """Two bounded passes: first may insert rows; second must insert zero new rows."""
    passes: list[RehearsalPass] = []
    try:
        passes.append(run_rehearsal_pass(1))
        if passes[0].status != RunStatus.SUCCEEDED.value:
            raise RuntimeError("INTELLIGENCE_REHEARSAL_FIRST_PASS_FAILED")
        passes.append(run_rehearsal_pass(2))
    except Exception as error:
        message, sqlstate = _snowflake_error_fields(error)
        guidance = permission_guidance_for_error(message, sqlstate)
        payload: dict[str, Any] = {
            "source_id": CDC_MMWR_SOURCE_ID,
            "definition": CDC_MMWR_DEFINITION.as_posix(),
            "status": "FAILED",
            "passes": [row.as_dict() for row in passes],
            "error_type": type(error).__name__,
            "snowflake_error": message,
            "sqlstate": sqlstate,
        }
        if guidance:
            payload["required_grant"] = guidance
        return payload

    second = passes[1]
    zero_new_rows = second.revisions_inserted == 0 and second.captures_inserted == 0
    succeeded = second.status == RunStatus.SUCCEEDED.value and zero_new_rows
    return {
        "source_id": CDC_MMWR_SOURCE_ID,
        "definition": CDC_MMWR_DEFINITION.as_posix(),
        "status": "SUCCEEDED" if succeeded else "FAILED",
        "passes": [row.as_dict() for row in passes],
        "idempotent_second_pass": zero_new_rows,
        "publish_status_second_pass": second.publish_status,
    }


def emit_rehearsal_report(payload: dict[str, Any]) -> None:
    """Print a redacted JSON report for workflow logs."""
    print(json.dumps(payload, indent=2, sort_keys=True))
    for row in payload.get("passes", []):
        print(
            "INTELLIGENCE_DEV_REHEARSAL_PASS "
            f"attempt={row['attempt']} "
            f"statement_count={row['statement_count']} "
            f"items_loaded={row['record_count']} "
            f"revisions_inserted={row['revisions_inserted']} "
            f"captures_inserted={row['captures_inserted']} "
            f"captures_replayed={row['captures_replayed']}"
        )
    if payload.get("snowflake_error"):
        print(f"SNOWFLAKE_ERROR {payload['snowflake_error']}")
    if payload.get("required_grant"):
        print(f"REQUIRED_GRANT {payload['required_grant']}")
