"""Privilege and workflow policy contracts for Epic #223 and Epic #294 / ADR 0030."""

from __future__ import annotations

from pathlib import Path

from semantic_contracts import (
    WORKFLOWS,
    assert_retired_source_workflow,
    assert_workflow_security,
    load_workflow,
    trigger_map,
    workflow_runs,
)

REPO = Path(__file__).resolve().parents[1]
# Epic #294 / ADR 0030 consolidated model: PIPELINE_RUNTIME was renamed to
# RUNTIME; STREAMLIT_OWNER, GOVERNED_VIEW_OWNER, KG_PAPER_REVIEW_OWNER, and
# KG_LLM_BUDGET_OWNER merged into OWNER; PMC_AUDITOR and the reserved
# API_RUNTIME grants merged into READ. STREAMLIT_OWNER is retained as its own
# role (nested under OWNER via role hierarchy) because Snowflake does not
# support GRANT/REVOKE OWNERSHIP ON STREAMLIT, so Streamlit app ownership
# cannot be transferred to another role.
STABLE_ROLES = {
    "OH_LYME_{ENV}_RUNTIME",
    "OH_LYME_{ENV}_OWNER",
    "OH_LYME_{ENV}_READ",
    "OH_LYME_{ENV}_MIGRATION_DEPLOYER",
    "OH_LYME_{ENV}_STREAMLIT_OWNER",
}


def test_generic_run_ingestion_workflow_exists() -> None:
    document = load_workflow(WORKFLOWS / "run-ingestion.yml")
    inputs = trigger_map(document)["workflow_dispatch"]["inputs"]
    assert inputs["source_definition"]["required"] is True
    assert inputs["operation"]["type"] == "choice"
    assert "run" in inputs["operation"]["options"]
    assert "atlas-data source" in "\n".join(workflow_runs(document))


def test_x5j9_specific_workflows_are_deprecated() -> None:
    assert_retired_source_workflow(WORKFLOWS / "capture-prod-cdc-evidence.yml")
    assert_retired_source_workflow(WORKFLOWS / "run-prod-approved-ingestion.yml")


def test_workflows_declare_minimal_permissions_and_protected_prod_environments() -> None:
    """A new workflow is allowed when its parsed properties stay inside these bounds."""
    for path in sorted(WORKFLOWS.glob("*.yml")):
        assert_workflow_security(path)


def test_stable_role_model_document_lists_minimal_roles() -> None:
    doc = (REPO / "docs" / "operations" / "snowflake-stable-role-model.md").read_text(
        encoding="utf-8"
    )
    for role in STABLE_ROLES:
        assert role in doc


def test_checkpoint_migration_uses_pipeline_runtime_not_source_role() -> None:
    sql = (REPO / "migrations" / "V068__simplified_ingestion_checkpoints.sql").read_text(
        encoding="utf-8"
    )
    assert "PIPELINE_RUNTIME" in sql
    assert "_X5J9_" not in sql
    assert "cdc_lyme" not in sql.lower()
