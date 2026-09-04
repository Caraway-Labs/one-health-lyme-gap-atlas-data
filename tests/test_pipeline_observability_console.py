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


def test_operations_console_uses_bounded_server_side_backlog_pagination() -> None:
    source = Path("streamlit_approval/streamlit_app.py").read_text(encoding="utf-8")
    assert "BACKLOG_PAGE_SIZE: Final = 100" in source
    assert "LIMIT ? OFFSET ?" in source
    assert "offset = (page_number - 1) * BACKLOG_PAGE_SIZE" in source
    assert "No redacted artifacts match the selected filters." in source


def test_operations_console_has_safe_durable_registration_views() -> None:
    source = Path("migrations/V039__pipeline_operations_console.sql").read_text(encoding="utf-8")
    app = Path("streamlit_approval/streamlit_app.py").read_text(encoding="utf-8")
    for view in (
        "V_PIPELINE_REGISTRATION_RUNS",
        "V_PIPELINE_COMMAND_CENTER",
        "V_PIPELINE_SEARCH_COVERAGE",
    ):
        assert f"CREATE OR REPLACE VIEW GOVERNANCE.{view}" in source
        assert view in app
    assert "artifact_uri" not in source
