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
