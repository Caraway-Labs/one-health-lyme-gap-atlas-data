from pathlib import Path


def test_observability_migration_exposes_only_redacted_governed_views() -> None:
    source = Path("migrations/V033__pipeline_observability_views.sql").read_text(encoding="utf-8")
    for view in (
        "V_PIPELINE_OBSERVABILITY_OVERVIEW",
        "V_PIPELINE_ARTIFACT_BACKLOG",
        "V_PIPELINE_DISCOVERY_RUNS",
        "V_PIPELINE_CATALOG_COVERAGE",
        "V_PIPELINE_REGISTRATION_OUTCOMES",
        "V_PIPELINE_SOURCE_GOVERNANCE",
    ):
        assert f"CREATE OR REPLACE VIEW GOVERNANCE.{view}" in source
        assert f"GRANT SELECT ON VIEW GOVERNANCE.{view}" in source
    assert "artifact_uri" not in source
    assert "redacted_request" in source
    assert "RAW_ARTIFACTS" in source


def test_console_includes_all_operational_views_and_explains_metric_semantics() -> None:
    source = Path("streamlit_approval/streamlit_app.py").read_text(encoding="utf-8")
    for page in (
        "Overview",
        "Pipeline health",
        "Artifact backlog",
        "Discovery coverage",
        "Registration outcomes",
        "Governance & approval",
        "Run explorer",
    ):
        assert f'"{page}"' in source
    for view in (
        "V_PIPELINE_OBSERVABILITY_OVERVIEW",
        "V_PIPELINE_ARTIFACT_BACKLOG",
        "V_PIPELINE_DISCOVERY_RUNS",
        "V_PIPELINE_CATALOG_COVERAGE",
        "V_PIPELINE_REGISTRATION_OUTCOMES",
        "V_PIPELINE_SOURCE_GOVERNANCE",
    ):
        assert view in source
    assert "historical inventory" in source
    assert "active chain" in source
    assert "artifact payloads" in source
    assert "LIMIT ? OFFSET ?" in source
    assert "_artifact_backlog_page" in source
    assert "INSERT INTO GOVERNANCE" not in source
    assert "UPDATE GOVERNANCE" not in source


def test_operations_console_uses_durable_redacted_run_summaries() -> None:
    migration = Path("migrations/V034__pipeline_operations_console.sql").read_text(encoding="utf-8")
    app = Path("streamlit_approval/streamlit_app.py").read_text(encoding="utf-8")
    for view in (
        "V_PIPELINE_REGISTRATION_RUNS",
        "V_PIPELINE_COMMAND_CENTER",
        "V_PIPELINE_SEARCH_COVERAGE",
    ):
        assert f"CREATE OR REPLACE VIEW GOVERNANCE.{view}" in migration
        assert f"GRANT SELECT ON VIEW GOVERNANCE.{view}" in migration
        assert view in app
    for page in (
        "Pipeline command center",
        "Registration recovery",
        "Search coverage and gaps",
    ):
        assert f'"{page}"' in app
    assert "artifact_uri" not in migration
    assert "redacted_request" in migration
    assert "error_classification" in migration
