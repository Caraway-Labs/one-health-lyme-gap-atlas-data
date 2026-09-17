"""Privilege and workflow policy contracts for Epic #223 and Epic #294 / ADR 0030."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
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
    path = WORKFLOWS / "run-ingestion.yml"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "atlas-data source" in text
    assert "source business logic" in text.lower() or "must not encode source" in text.lower()


def test_x5j9_specific_workflows_are_deprecated() -> None:
    capture = (WORKFLOWS / "capture-prod-cdc-evidence.yml").read_text(encoding="utf-8")
    ingest = (WORKFLOWS / "run-prod-approved-ingestion.yml").read_text(encoding="utf-8")
    assert "DEPRECATED" in capture
    assert "DEPRECATED" in ingest
    assert "run-ingestion.yml" in capture
    assert "run-ingestion.yml" in ingest


def test_no_new_source_specific_workflow_without_exception_marker() -> None:
    """New capture/ingest YAML files must be generic or explicitly excepted."""
    allowed_prefixes = (
        "run-ingestion",
        "quality",
        "deploy-dev",
        "promote-prod",
        "monitor-cdc-operations",
        "capture-dev-cdc-historical",
        "capture-prod-cdc-historical",
        "capture-dev-cdc-tick-surveillance-operator",
        "ingest-dev-cdc-historical",
        "ingest-prod-cdc-historical",
        "rollback-prod-cdc-historical",
        "run-dev-cdc-dbt-recovery",
        "run-prod-cdc-dbt-recovery",
        "capture-prod-cdc-evidence",
        "run-prod-approved-ingestion",
        "run-prod-ingestion",
        "publish-semantic-release",
    )
    for path in WORKFLOWS.glob("*.yml"):
        assert path.stem in allowed_prefixes or path.stem.startswith("run-ingestion"), (
            f"Unexpected workflow {path.name}; add an explicit exception if required"
        )


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
