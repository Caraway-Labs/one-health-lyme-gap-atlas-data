import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from lyme_gap_atlas_data import orchestration
from lyme_gap_atlas_data.approval import approval_prerequisites_met, validate_decision
from lyme_gap_atlas_data.artifacts import create_artifact
from lyme_gap_atlas_data.assessment import Assessment
from lyme_gap_atlas_data.cdc import load_cdc_profile
from lyme_gap_atlas_data.discovery import (
    _retryable_catalog_error,
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
    assert len(initial_requests(config)) == 535
    assert any(request.term == "Lyme economic burden" for request in initial_requests(config))


def test_discovery_requests_have_a_deterministic_term_order() -> None:
    config = load_search_configuration(Path("catalog-search-terms.json"))[0]
    first = initial_requests(config)
    second = initial_requests(config)
    assert [request.term for request in first] == [request.term for request in second]


def test_catalog_specific_term_exclusion_preserves_other_catalog_coverage() -> None:
    config = load_search_configuration(Path("catalog-search-terms.json"))[0]
    requests = initial_requests(config)
    for term in ("case definition", "case surveillance"):
        assert not any(
            request.catalog_id == "DATA_GOV" and request.term.casefold() == term
            for request in requests
        )
        assert any(
            request.catalog_id == "HEALTHDATA_GOV" and request.term.casefold() == term
            for request in requests
        )
        assert any(
            request.catalog_id == "SOCRATA_ODN" and request.term.casefold() == term
            for request in requests
        )


def test_discovery_configuration_rejects_unknown_catalog_exclusion(tmp_path: Path) -> None:
    config = deepcopy(load_search_configuration(Path("catalog-search-terms.json"))[0])
    config["catalogs"][0]["excluded_terms"] = ["not a configured term"]
    path = tmp_path / "catalog-search-terms-invalid.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown excluded terms"):
        load_search_configuration(path)


def test_failed_catalog_request_retains_only_redacted_evidence() -> None:
    request = orchestration.DiscoveryRequest(
        catalog_id="DATA_GOV",
        term="Lyme disease",
        url="https://example.test/search?q=Lyme+disease",
        headers={"X-Api-Key": "secret"},
        pagination={},
    )
    error = HTTPError(request.url, 400, "Bad Request", None, None)
    assert orchestration._failure_status_code(error) == 400
    assert "secret" not in orchestration._redacted_request_details(request)
    assert "[REDACTED]" in orchestration._redacted_request_details(request)


def test_catalog_retries_are_limited_to_transient_errors() -> None:
    assert not _retryable_catalog_error(HTTPError("https://example.test", 403, "", None, None))
    assert _retryable_catalog_error(HTTPError("https://example.test", 429, "", None, None))
    assert _retryable_catalog_error(HTTPError("https://example.test", 503, "", None, None))
    assert not _retryable_catalog_error(HTTPError("https://example.test", 400, "", None, None))


def test_rate_limit_resume_state_excludes_request_headers() -> None:
    request = orchestration.DiscoveryRequest(
        catalog_id="DATA_GOV",
        term="Lyme disease",
        url="https://example.test/search?q=Lyme+disease&after=cursor",
        headers={"X-Api-Key": "secret"},
        pagination={"strategy": "CURSOR"},
    )
    state = orchestration._resume_state(orchestration.DiscoveryResume("prior-run", 3, request, 0))
    assert "secret" not in state
    decoded = orchestration._decode_resume_state("prior-run", state)
    assert decoded.request.url == request.url
    assert decoded.request.headers == {}
    assert decoded.original_request_index == 3


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
    third_cursor_page = next_page_request(cursor_page, {"after": "later-cursor"}, 0)
    assert third_cursor_page is not None
    cursor_parameters = parse_qs(urlsplit(third_cursor_page.url).query)
    assert cursor_parameters["after"] == ["later-cursor"]
    assert cursor_parameters["per_page"] == ["100"]


def test_settings_rejects_poc_database() -> None:
    with pytest.raises(ValueError, match="SNOWFLAKE_DATABASE"):
        PipelineSettings(topx_env="dev", snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS")


def test_settings_require_an_explicit_production_execution_gate() -> None:
    with pytest.raises(ValueError, match="ENABLE_PRODUCTION_EXECUTION"):
        PipelineSettings(topx_env="prod", snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    assert (
        PipelineSettings(
            topx_env="prod",
            snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
            enable_production_execution=True,
        ).topx_env
        == "prod"
    )


def test_production_schedule_rejects_dev_before_any_ingestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(orchestration, "PipelineSettings", lambda: SimpleNamespace(topx_env="dev"))
    with pytest.raises(ValueError, match="only in production"):
        orchestration.run_production_schedule()


def test_production_schedule_requires_approved_ingestion_before_dbt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(orchestration, "PipelineSettings", lambda: SimpleNamespace(topx_env="prod"))
    monkeypatch.setattr(
        orchestration,
        "ingest_approved_cdc",
        lambda **kwargs: {"source_version_id": "version-1", "status": "COMPLETED"},
    )
    monkeypatch.setattr(
        orchestration,
        "build_approved_cdc_models",
        lambda source_version_id: {"source_version_id": source_version_id, "status": "COMPLETED"},
    )
    result = orchestration.run_production_schedule()
    assert result["ingestion"]["source_version_id"] == "version-1"
    assert result["promotion"]["status"] == "COMPLETED"


def test_production_app_spec_has_separate_gated_jobs() -> None:
    spec = yaml.safe_load(Path(".do/app.prod.yaml").read_text(encoding="utf-8"))
    jobs = {job["name"]: job for job in spec["jobs"]}
    assert jobs["catalog-discovery"]["run_command"] == "uv run atlas-data pipeline discover"
    assert (
        jobs["approved-source-ingestion"]["run_command"]
        == "uv run atlas-data pipeline run-production-schedule"
    )
    for job in jobs.values():
        assert any(
            env["key"] == "ENABLE_PRODUCTION_EXECUTION" and env["value"] == "true"
            for env in job["envs"]
        )


def test_production_promotion_only_updates_an_existing_secret_preserving_app() -> None:
    workflow = Path(".github/workflows/promote-prod.yml").read_text(encoding="utf-8")
    assert 'doctl apps spec get "$PROD_APP_ID" --format json > "$prod_spec"' in workflow
    assert 'doctl apps update "$PROD_APP_ID" --spec "$next_spec" --wait' in workflow
    assert ".image.digest = $image_digest" in workflow
    assert "provider-encrypted secret values" in workflow
    assert "exit 1" not in workflow


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


def test_cdc_raw_load_quotes_the_socrata_system_identifier() -> None:
    source = Path("src/lyme_gap_atlas_data/cdc.py").read_text(encoding="utf-8")
    assert '$1:":id"::VARCHAR' in source


def test_dbt_profile_supports_an_encrypted_pipeline_key() -> None:
    profile = Path("dbt/profiles.yml").read_text(encoding="utf-8")
    assert "private_key_passphrase" in profile


def test_dbt_uses_only_migration_provisioned_governed_schemas() -> None:
    macros = Path("dbt/macros/governed_schemas.sql").read_text(encoding="utf-8")
    assert "generate_schema_name" in macros
    assert "snowflake__create_schema" in macros
    assert "STAGING" in macros
    assert "CONFORMED" in macros


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
        "V017",
        "V018",
        "V019",
        "V020",
        "V021",
        "V022",
        "V023",
        "V024",
    ]
    assert "ONE_HEALTH_LYME_GAP_ATLAS_DEV" in render_migration(
        migrations[0], "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
    )
    with pytest.raises(ValueError, match="only"):
        render_migration(migrations[0], "ONE_HEALTH_LYME_GAP_ATLAS")
    prod_plan = migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    assert len(prod_plan) == 24
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
    catalog_repair = migrations[16].source
    assert "CREATE TABLE IF NOT EXISTS GOVERNANCE.CATALOG_DATASETS" in catalog_repair
    assert "RECONSTRUCTED_FROM_PRESERVED_RESOURCE_PAYLOAD" in catalog_repair
    assert "metadata_sha256" in catalog_repair
    assert "GRANT SELECT ON TABLE GOVERNANCE.CATALOG_DATASETS" in catalog_repair
    assert "GRANT SELECT ON TABLE GOVERNANCE.INGESTION_RUNS" in migrations[17].source
    dbt_grants = migrations[18].source
    assert "GRANT SELECT ON TABLE RAW.CDC_LYME_X5J9_WYBP" in dbt_grants
    assert "GRANT CREATE TABLE, CREATE VIEW ON SCHEMA STAGING" in dbt_grants
    reconciliation = migrations[19].source
    assert "Preserve the append-only migration ledger" in reconciliation
    assert "GRANT CREATE TABLE, CREATE VIEW ON SCHEMA CONFORMED" in reconciliation
    runtime_bootstrap = migrations[20].source
    assert "CREATE WAREHOUSE IF NOT EXISTS OH_LYME_{{ ENV }}_INGEST_XS_WH" in runtime_bootstrap
    assert "GRANT USAGE ON DATABASE {{ DATABASE }}" in runtime_bootstrap
    ledger_reconciliation = migrations[21].source
    assert "Preserve both immutable audit records" in ledger_reconciliation
    assert "COUNT(DISTINCT sha256) = 1" in ledger_reconciliation
    service_user = migrations[22].source
    assert "TYPE = SERVICE" in service_user
    assert "GRANT ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME" in service_user
    rate_limit_resume = migrations[23].source
    assert "resumed_from_ingestion_run_id" in rate_limit_resume
    assert "resume_state VARIANT" in rate_limit_resume
    assert "GRANT SELECT ON TABLE GOVERNANCE.INGESTION_REQUESTS" in rate_limit_resume
    assert "GRANT SELECT ON TABLE GOVERNANCE.RAW_ARTIFACTS" in rate_limit_resume
    owner_rights_dependencies = "\n".join(
        migration.source for migration in (migrations[5], migrations[16], migrations[17])
    )
    for table_name in ("CATALOG_DATASETS", "INGESTION_RUNS"):
        assert f"GRANT SELECT ON TABLE GOVERNANCE.{table_name}" in owner_rights_dependencies


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
