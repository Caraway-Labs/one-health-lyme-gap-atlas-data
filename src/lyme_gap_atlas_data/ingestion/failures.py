"""Failure taxonomy helpers for operator diagnostics (#231)."""

from __future__ import annotations

from .types import FailureCategory, RunState, StageStatus

FAILURE_GUIDANCE: dict[FailureCategory, str] = {
    FailureCategory.CONFIGURATION: "Fix SourceDefinition fields and re-run source validate.",
    FailureCategory.ACQUISITION: "Retry ACQUIRE; completed upstream stages will not be replayed.",
    FailureCategory.POLICY_LICENSE: "Route to Tier D exception review; do not force Tier B.",
    FailureCategory.SCHEMA: "Align required columns/schema expectations, then resume VALIDATE.",
    FailureCategory.NORMALIZATION: "Fix normalization hook; resume NORMALIZE without reacquire.",
    FailureCategory.WAREHOUSE: "Check DEV role/warehouse; resume LOAD after permissions restore.",
    FailureCategory.QUALITY: "Inspect quality rule failures; resume QUALITY after correction.",
    FailureCategory.PROVIDER_MODEL: "Retry extract stage only; do not re-fetch durable JATS.",
    FailureCategory.GRAPH: "Retry Neo4j publish using existing validated contribution.",
    FailureCategory.DEPLOYMENT: (
        "Use protected deploy/promote workflows; do not patch topology by hand."
    ),
    FailureCategory.PERMISSION: (
        "Use least-privilege DEV role; escalate ownership handoffs only when documented."
    ),
}


def explain_run(state: RunState) -> dict[str, object]:
    failed = [checkpoint for checkpoint in state.stages if checkpoint.status is StageStatus.FAILED]
    if not failed:
        return {
            "ingestion_run_id": state.ingestion_run_id,
            "status": state.status.value,
            "next_action": state.next_action or "none",
            "guidance": "Run has no failed stages.",
        }
    checkpoint = failed[-1]
    category = checkpoint.failure_category or FailureCategory.CONFIGURATION
    next_action = checkpoint.next_action or state.next_action or f"resume:{checkpoint.stage.value}"
    return {
        "ingestion_run_id": state.ingestion_run_id,
        "status": state.status.value,
        "failed_stage": checkpoint.stage.value,
        "failure_category": category.value,
        "redacted_diagnostic_code": checkpoint.redacted_diagnostic_code,
        "next_action": next_action,
        "guidance": FAILURE_GUIDANCE[category],
        "completed_stages": [
            item.stage.value for item in state.stages if item.status is StageStatus.COMPLETED
        ],
    }
