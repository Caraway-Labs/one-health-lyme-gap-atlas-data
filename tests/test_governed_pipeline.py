from pathlib import Path

import pytest

from lyme_gap_atlas_data.approval import approval_prerequisites_met, validate_decision
from lyme_gap_atlas_data.artifacts import create_artifact
from lyme_gap_atlas_data.assessment import Assessment
from lyme_gap_atlas_data.cdc import load_cdc_profile
from lyme_gap_atlas_data.discovery import (
    initial_requests,
    load_search_configuration,
    next_page_request,
)
from lyme_gap_atlas_data.migrations import load_migrations, migration_plan, render_migration
from lyme_gap_atlas_data.orchestration import _resource_key
from lyme_gap_atlas_data.preflight import _required_settings
from lyme_gap_atlas_data.redaction import redact_mapping
from lyme_gap_atlas_data.settings import PipelineSettings


def test_artifact_identity_is_content_addressed() -> None:
    artifact = create_artifact(
        payload=b"source", environment="dev", resource_key="cdc", run_id="run-1"
    )
    assert artifact.sha256 in artifact.object_key
    assert artifact.byte_count == 6


def test_assessment_policy_thresholds() -> None:
    assert Assessment(70, 70, 70, 70, 70).recommendation == "APPROVED"
    assert Assessment(50, 50, 50, 50, 50).recommendation == "CONDITIONAL"
    assert Assessment(49, 49, 49, 49, 49).recommendation == "REJECTED"


def test_review_decision_requires_rationale_and_conditions() -> None:
    with pytest.raises(ValueError, match="rationale"):
        validate_decision("APPROVED", "short", [])
    with pytest.raises(ValueError, match="condition"):
        validate_decision("DEFERRED", "A complete explanation", [])
    validate_decision("APPROVED_WITH_CONDITIONS", "A complete explanation", ["Check terms"])
    assert approval_prerequisites_met(
        {
            "document_snapshot_count": 1,
            "schema_snapshot_count": 1,
            "profile_version": 1,
            "assessment_status": "PENDING_REVIEW",
            "has_material_schema_change": False,
            "has_material_document_change": False,
            "has_blocking_issue": False,
        }
    )
    assert not approval_prerequisites_met(
        {
            "document_snapshot_count": 1,
            "schema_snapshot_count": 1,
            "profile_version": 1,
            "assessment_status": "PENDING_REVIEW",
            "has_material_schema_change": False,
            "has_material_document_change": True,
            "has_blocking_issue": True,
        }
    )


def test_redaction_removes_secrets() -> None:
    assert redact_mapping({"X-App-Token": "secret", "limit": 10}) == {
        "X-App-Token": "[REDACTED]",
        "limit": 10,
    }


def test_discovery_configuration_is_valid() -> None:
    config, checksum = load_search_configuration(Path("catalog-search-terms.json"))
    assert len(checksum) == 64
    assert {request.catalog_id for request in initial_requests(config)} == {
        "DATA_GOV",
        "HEALTHDATA_GOV",
        "SOCRATA_ODN",
    }
    assert len(initial_requests(config)) == 537
    assert any(request.term == "Lyme economic burden" for request in initial_requests(config))


def test_discovery_pagination_uses_catalog_strategy() -> None:
    config = load_search_configuration(Path("catalog-search-terms.json"))[0]
    socrata = next(
        request for request in initial_requests(config) if request.catalog_id == "HEALTHDATA_GOV"
    )
    assert "limit=100" in socrata.url
    assert "offset=0" in socrata.url
    second_page = next_page_request(socrata, {"results": [{}] * 100}, 0)
    assert second_page is not None
    assert "limit=100" in second_page.url
    assert "offset=100" in second_page.url

    data_gov = next(
        request for request in initial_requests(config) if request.catalog_id == "DATA_GOV"
    )
    assert "per_page=100" in data_gov.url
    cursor_page = next_page_request(data_gov, {"after": "next-cursor"}, 0)
    assert cursor_page is not None
    assert "after=next-cursor" in cursor_page.url
    assert "per_page=100" in cursor_page.url


def test_settings_rejects_poc_database() -> None:
    with pytest.raises(ValueError, match="SNOWFLAKE_DATABASE"):
        PipelineSettings(topx_env="dev", snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS")


def test_preflight_identifies_missing_required_configuration() -> None:
    settings = PipelineSettings(
        snowflake_account="",
        snowflake_user="",
        snowflake_private_key_path=None,
        snowflake_private_key_b64=None,
        snowflake_private_key_passphrase=None,
        data_gov_api_key=None,
        spaces_endpoint="",
        spaces_access_key_id=None,
        spaces_secret_access_key=None,
    )
    assert "SNOWFLAKE_ACCOUNT" in _required_settings(settings)
    assert "SPACES_SECRET_ACCESS_KEY" in _required_settings(settings)


def test_catalog_resource_key_is_deterministic_without_exposing_term() -> None:
    request = initial_requests(load_search_configuration(Path("catalog-search-terms.json"))[0])[0]
    assert _resource_key(request) == _resource_key(request)
    assert request.term not in _resource_key(request)


def test_cdc_profile_requires_deterministic_ordering() -> None:
    profile = load_cdc_profile()
    assert profile["resource_key"] == "cdc_lyme_x5j9_wybp"
    assert profile["deterministic_order_clause"] == ":id ASC"


def test_migrations_are_environment_neutral_and_reject_poc() -> None:
    migrations = load_migrations()
    assert [item.version for item in migrations] == [
        "V001",
        "V002",
        "V003",
        "V004",
        "V005",
        "V006",
        "V007",
        "V008",
        "V009",
        "V010",
        "V011",
        "V012",
        "V013",
        "V014",
        "V015",
        "V016",
    ]
    assert "ONE_HEALTH_LYME_GAP_ATLAS_DEV" in render_migration(
        migrations[0], "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
    )
    with pytest.raises(ValueError, match="only"):
        render_migration(migrations[0], "ONE_HEALTH_LYME_GAP_ATLAS")
    prod_plan = migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    assert len(prod_plan) == 16
    rendered_prod = render_migration(migrations[2], "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    assert "OH_LYME_PROD_STREAMLIT_OWNER" in rendered_prod
    safe_variant_insert = "SELECT :decision_id, :RESOURCE_KEY, :DECISION, :RATIONALE, :CONDITIONS"
    assert "GRANT SELECT, INSERT ON TABLE GOVERNANCE.SCHEMA_MIGRATIONS" in migrations[5].source
    assert "GRANT CREATE PROCEDURE ON SCHEMA GOVERNANCE" in migrations[6].source
    assert safe_variant_insert in migrations[7].source
    assert "GRANT SELECT ON TABLE GOVERNANCE.DATA_SOURCE_VERSIONS" in migrations[8].source
    assert "BEGIN TRANSACTION" in migrations[9].source
    assert "WHEN OTHER THEN" in migrations[9].source
    assert "RETIRED" in migrations[10].source
    assert "WHERE r.is_active = TRUE" in migrations[11].source
    assert "GRANT SELECT ON VIEW GOVERNANCE.V_SOURCE_APPROVAL_QUEUE" in migrations[12].source
    assert "ld.manual_review_decision_id IS NULL" in migrations[13].source
    assert "GRANT SELECT ON VIEW GOVERNANCE.V_SOURCE_APPROVAL_QUEUE" in migrations[13].source
    assert "RAW.INGESTION_TRANSIENT_STAGE" in migrations[14].source
    hardening = migrations[15].source
    assert "cdc_lyme_x5j9_wybp" in hardening
    assert "steward_count < 1" in hardening
    assert "metadata_payload IS NOT NULL" in hardening
    assert "has_material_document_change" in hardening
    assert "supersedes_decision_id" in hardening
    assert "eligible_for_full_ingestion" in hardening
    assert "FROM resource r" in hardening


def test_approval_console_refreshes_to_the_next_pending_candidate() -> None:
    source = Path("streamlit_approval/streamlit_app.py").read_text(encoding="utf-8")
    assert 'st.session_state["recorded_decision"]' in source
    assert "st.rerun()" in source
    assert "Review queue is clear" in source
    assert "Queue" in source
    assert "Candidate detail" in source
    assert "Decision history" in source
    assert "available_decisions" in source
    assert 'st.code(_safe_snowflake_error(exc), language="text")' in source
    assert "INSERT INTO GOVERNANCE" not in source
    assert "UPDATE GOVERNANCE" not in source
