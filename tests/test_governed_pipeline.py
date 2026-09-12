import base64
import hashlib
import json
import logging
from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from lyme_gap_atlas_data import cdc, cli, orchestration
from lyme_gap_atlas_data.approval import approval_prerequisites_met, validate_decision
from lyme_gap_atlas_data.artifacts import create_artifact
from lyme_gap_atlas_data.assessment import Assessment
from lyme_gap_atlas_data.catalog_registration import (
    CatalogDataset,
    CatalogResource,
    RegistrationDataset,
    RegistrationProgress,
    _cgroup_memory_context,
    _claim_registration_batch,
    _completed_artifacts,
    _execute_registration_merge,
    _log_registration_phase,
    _process_memory_context,
    _write_registration_dataset_batch,
    canonicalize_public_url,
    latest_completed_discovery_config_sha256,
    normalize_catalog_payload,
    register_completed_discovery,
)
from lyme_gap_atlas_data.cdc import build_approved_cdc_models, load_cdc_profile
from lyme_gap_atlas_data.discovery import (
    DiscoveryRequest,
    _retryable_catalog_error,
    initial_requests,
    load_search_configuration,
    next_page_request,
)
from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    LEGACY_DEV_MIGRATION_CHECKSUMS,
    LEGACY_PROD_MIGRATION_CHECKSUMS,
    LEGACY_PROD_MIGRATION_FILENAMES,
    LEGACY_PROD_MIGRATION_ROW_COUNTS,
    PROD_DATABASE,
    is_authorized_legacy_reconciliation,
    is_line_ending_equivalent_checksum,
    legacy_dev_reconciliation_plan,
    legacy_prod_reconciliation_plan,
    load_migrations,
    migration_execution_role,
    migration_plan,
    render_migration,
)
from lyme_gap_atlas_data.orchestration import _resource_key
from lyme_gap_atlas_data.preflight import _required_settings
from lyme_gap_atlas_data.redaction import redact_mapping
from lyme_gap_atlas_data.settings import PipelineSettings


@pytest.fixture(autouse=True)
def isolate_publication_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cdc, "cdc_operation", lambda: nullcontext("lease"))
    monkeypatch.setattr(cdc, "publication_context", lambda _: ("run-1", 0))
    monkeypatch.setattr(cdc, "publish_snapshot", lambda *args, **kwargs: {"status": "PUBLISHED"})


def test_artifact_identity_is_content_addressed() -> None:
    artifact = create_artifact(
        payload=b"source", environment="dev", resource_key="cdc", run_id="run-1"
    )
    assert artifact.sha256 in artifact.object_key
    assert artifact.byte_count == 6


def test_container_uses_cmd_so_app_platform_can_replace_each_job_command() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert 'CMD ["/app/.venv/bin/atlas-data", "pipeline", "discover"]' in dockerfile
    assert "\nENTRYPOINT " not in dockerfile


def test_promotion_runs_registration_from_the_built_virtual_environment() -> None:
    workflow = Path(".github/workflows/promote-prod.yml").read_text(encoding="utf-8")
    assert (
        '"/app/.venv/bin/atlas-data pipeline register-latest-discovery '
        '--max-artifacts 12 --max-datasets 1500"'
    ) in workflow
    assert "range(1; 4)" in workflow
    assert 'test("^catalog-registration-0[1-3]$")' in workflow
    assert '.kind = "SCHEDULED"' in workflow
    assert '" * * * *"' in workflow


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
    assert all(
        request.pagination.get("maximum_offset") == 9900
        for request in initial_requests(config)
        if request.catalog_id in {"HEALTHDATA_GOV", "SOCRATA_ODN"}
    )


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


def test_legacy_rate_limit_check_requires_a_recorded_429() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.query = ""
            self.parameters: tuple[str] = ()

        def execute(self, query: str, parameters: tuple[str]) -> None:
            self.query = query
            self.parameters = parameters

        def fetchone(self) -> tuple[int]:
            return (1,)

    cursor = Cursor()
    assert orchestration._has_legacy_rate_limit_failure(cursor, "prior-run")
    assert "status_code = 429" in cursor.query
    assert cursor.parameters == ("prior-run",)


def test_discovery_runtime_budget_is_bounded_before_platform_timeout() -> None:
    assert PipelineSettings().discovery_max_runtime_seconds == 1500
    assert PipelineSettings().neo4j_runtime_user == "graph_runtime"
    with pytest.raises(ValueError, match="DISCOVERY_MAX_RUNTIME_SECONDS"):
        PipelineSettings(discovery_max_runtime_seconds=1741)


def test_stale_data_gov_run_resumes_from_last_successful_artifact() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, _query: str, _parameters: tuple[str]) -> None:
            self.calls += 1

        def fetchone(self) -> tuple[str, str, str] | None:
            if self.calls == 1:
                return None
            return ("DATA_GOV", "Lyme disease", "s3://bucket/prod/last-page.json")

    class Body:
        def read(self) -> bytes:
            return b'{"after":"next-cursor"}'

    class S3:
        def get_object(self, **_kwargs: str) -> dict[str, Body]:
            return {"Body": Body()}

    request = DiscoveryRequest(
        catalog_id="DATA_GOV",
        term="Lyme disease",
        url="https://example.test/search?per_page=100",
        headers={},
        pagination={
            "strategy": "CURSOR",
            "request_parameter": "after",
            "page_size_parameter": "per_page",
            "page_size": 100,
        },
    )
    resume = orchestration._reconstruct_data_gov_resume(
        Cursor(),
        S3(),
        SimpleNamespace(spaces_bucket="bucket"),
        "prior-run",
        [request],
        require_rate_limit=False,
    )
    assert resume.prior_run_id == "prior-run"
    assert "after=next-cursor" in resume.request.url


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

    capped_socrata = DiscoveryRequest(
        catalog_id="HEALTHDATA_GOV",
        term="catalog window",
        url="https://example.test/catalog?limit=100&offset=9900&q=catalog+window",
        headers={},
        pagination={
            "strategy": "OFFSET_LIMIT",
            "request_parameters": {"limit": 100, "offset": "{{offset}}"},
            "maximum_offset": 9900,
        },
    )
    assert next_page_request(capped_socrata, {"results": [{}] * 100}, 9900) is None

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


def test_production_schedule_checks_metadata_without_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(orchestration, "PipelineSettings", lambda: SimpleNamespace(topx_env="prod"))
    monkeypatch.setattr(
        orchestration,
        "check_cdc_metadata",
        lambda: {"status": "UNCHANGED"},
    )
    monkeypatch.setattr(
        orchestration,
        "build_approved_cdc_models",
        lambda _: pytest.fail("Monthly checks must not run dbt"),
    )
    result = orchestration.run_production_schedule()
    assert result["status"] == "UNCHANGED"


def test_production_dbt_recovery_rejects_dev_before_any_dbt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(orchestration, "PipelineSettings", lambda: SimpleNamespace(topx_env="dev"))
    with pytest.raises(ValueError, match="only in production"):
        orchestration.run_production_cdc_dbt_recovery("version-1")


def test_production_dbt_recovery_uses_retained_raw_without_ingestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(orchestration, "PipelineSettings", lambda: SimpleNamespace(topx_env="prod"))
    monkeypatch.setattr(
        orchestration,
        "run_cdc_dbt_recovery",
        lambda source_version_id: {
            "raw_load": {"source_version_id": source_version_id, "raw_rows": 5_045},
            "promotion": {"source_version_id": source_version_id, "status": "COMPLETED"},
            "status": "COMPLETED",
        },
    )
    assert orchestration.run_production_cdc_dbt_recovery("version-1") == {
        "raw_load": {"source_version_id": "version-1", "raw_rows": 5_045},
        "promotion": {"source_version_id": "version-1", "status": "COMPLETED"},
        "status": "COMPLETED",
    }


def test_cdc_dbt_recovery_uses_retained_raw_in_dev_or_prod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Cursor:
        def __enter__(self) -> "Cursor":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def execute(self, *_: object) -> None:
            return None

    class Connection:
        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def cursor(self) -> Cursor:
            return Cursor()

        def commit(self) -> None:
            return None

    monkeypatch.setattr(
        orchestration,
        "confirm_approved_cdc_raw_load",
        lambda source_version_id: {"source_version_id": source_version_id, "raw_rows": 5_045},
    )
    monkeypatch.setattr(
        orchestration,
        "build_approved_cdc_models",
        lambda source_version_id: {"source_version_id": source_version_id, "status": "COMPLETED"},
    )
    completed: list[tuple[str, str, str | None]] = []
    monkeypatch.setattr(orchestration, "uuid", SimpleNamespace(uuid4=lambda: "recovery-1"))
    monkeypatch.setattr(orchestration, "datetime", SimpleNamespace(now=lambda *_: "now"))
    monkeypatch.setattr(
        orchestration,
        "_complete_cdc_dbt_recovery",
        lambda run_id, status, classification: completed.append((run_id, status, classification)),
    )
    monkeypatch.setattr(orchestration, "connect", lambda *_: Connection())
    result = orchestration.run_cdc_dbt_recovery("version-1")
    assert result["raw_load"]["raw_rows"] == 5_045
    assert result["recovery_run_id"] == "recovery-1"
    assert completed == [("recovery-1", "COMPLETED", None)]


def test_production_app_spec_has_separate_gated_jobs() -> None:
    spec = yaml.safe_load(Path(".do/app.prod.yaml").read_text(encoding="utf-8"))
    jobs = {job["name"]: job for job in spec["jobs"]}
    assert jobs["catalog-discovery"]["run_command"] == "uv run atlas-data pipeline discover"
    assert (
        jobs["approved-source-ingestion"]["run_command"]
        == "uv run atlas-data pipeline run-production-schedule"
    )
    registrations = [jobs[f"catalog-registration-{worker:02d}"] for worker in range(1, 4)]
    assert all(job["kind"] == "SCHEDULED" for job in registrations)
    assert [job["schedule"]["cron"] for job in registrations] == [
        f"{minute} * * * *" for minute in range(15, 60, 15)
    ]
    assert all(
        job["run_command"] == "/app/.venv/bin/atlas-data pipeline register-latest-discovery "
        "--max-artifacts 12 --max-datasets 1500"
        for job in registrations
    )
    for job in jobs.values():
        assert any(
            env["key"] == "ENABLE_PRODUCTION_EXECUTION" and env["value"] == "true"
            for env in job["envs"]
        )


def test_dev_image_deployment_updates_every_scheduled_job() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert ".jobs |= map(" in workflow
    assert 'registry: "oh-lyme-data"' in workflow
    fixture = 'doctl apps update "$APP_ID" --spec /tmp/dev-app-fixture.json --wait'
    final = 'doctl apps update "$APP_ID" --spec /tmp/dev-app-image.json --wait'
    assert workflow.index(fixture) < workflow.index(final)
    assert '.kind = "PRE_DEPLOY"' in workflow
    assert "/app/scripts/verify_cdc_policy_dev.py" in workflow
    assert ".jobs[0]" not in workflow


def test_production_promotion_only_updates_an_existing_secret_preserving_app() -> None:
    workflow = Path(".github/workflows/promote-prod.yml").read_text(encoding="utf-8")
    assert 'doctl apps spec get "$PROD_APP_ID" --format json > "$prod_spec"' in workflow
    assert 'doctl apps update "$PROD_APP_ID" --spec "$next_spec" --wait' in workflow
    assert ".image.digest = $image_digest" in workflow
    assert '"catalog-registration"' in workflow
    assert '"SCHEDULED"' in workflow
    assert "register-latest-discovery" in workflow
    assert "provider-encrypted secret values" in workflow
    assert '"cdc-operations-watchdog"' in workflow
    assert '"approved-source-ingestion"' in workflow
    assert "approved six-job baseline" in workflow
    assert 'select(.kind == "SCHEDULED")' in workflow
    assert "pubmed-discovery-surveillance" not in workflow
    assert "approved-paper-extraction" not in workflow
    assert "exit 1" not in workflow


def test_protected_prod_cdc_evidence_workflow_is_one_shot_and_restores_topology() -> None:
    workflow = Path(".github/workflows/capture-prod-cdc-evidence.yml").read_text(encoding="utf-8")
    assert "environment: production" in workflow
    assert "workflow_dispatch:" in workflow
    assert "concurrency:" in workflow
    assert "group: prod-cdc-evidence-capture" in workflow
    assert 'doctl apps spec get "$PROD_APP_ID" --format json > "$baseline_spec"' in workflow
    assert 'test "$(jq -r \'.name\' "$baseline_spec")" = "oh-lyme-data-prod"' in workflow
    assert '"catalog-discovery"' in workflow
    assert '"cdc-evidence-capture"' in workflow
    assert '.kind = "PRE_DEPLOY"' in workflow
    assert "del(.schedule)" in workflow
    assert '"uv run atlas-data pipeline cdc-sample"' in workflow
    assert 'doctl apps update "$PROD_APP_ID" --spec "$baseline_spec" --wait' in workflow
    assert "PRE_DEPLOY job's exit through deployment" in workflow
    assert "list-job-invocations" not in workflow
    assert "provider-encrypted secrets" in workflow
    assert "ingest-approved-cdc" not in workflow
    assert "run-production-schedule" not in workflow
    assert "dbt " not in workflow


def test_protected_prod_historical_evidence_reuses_digest_and_restores_topology() -> None:
    workflow = Path(".github/workflows/capture-prod-cdc-historical.yml").read_text(encoding="utf-8")
    assert "environment: production" in workflow
    assert "group: prod-cdc-historical-evidence-capture" in workflow
    assert "DEV_APP_ID: b33dbae7-e243-4e27-b3ca-1018f5897f87" in workflow
    assert 'select(.name == "catalog-ingestion")' in workflow
    assert 'select(.name == "catalog-discovery")' in workflow
    assert 'select(.name == "catalog-ingestion") | .image.digest' in workflow
    assert 'select(.name == "catalog-discovery") | .image.digest' in workflow
    assert workflow.count('= "$IMAGE_DIGEST"') >= 2
    assert '"cdc-historical-evidence-once"' in workflow
    assert '.kind = "PRE_DEPLOY"' in workflow
    assert "del(.schedule)" in workflow
    assert "cdc-historical-sample --sample-limit 25" in workflow
    assert 'doctl apps update "$PROD_APP_ID" --spec "$baseline_spec" --wait' in workflow
    assert "ingest-approved-cdc-historical" not in workflow
    assert "dbt " not in workflow


def test_protected_prod_historical_ingestion_is_exact_and_restores_topology() -> None:
    workflow = Path(".github/workflows/ingest-prod-cdc-historical.yml").read_text(encoding="utf-8")
    assert "environment: production" in workflow
    assert "group: prod-cdc-historical-ingestion" in workflow
    assert 'select(.name == "approved-source-ingestion")' in workflow
    assert '"cdc-historical-ingest-once"' in workflow
    assert "ingest-approved-cdc-historical --source-version-id" in workflow
    assert '.kind = "PRE_DEPLOY"' in workflow and "del(.schedule)" in workflow
    assert "list-deployments" in workflow and 'test "$dev_verified" = true' in workflow
    assert "test \"$(jq '[.jobs[].image.digest] | unique | length'" in workflow
    assert "catalog-registration-03" in workflow and "cdc-operations-watchdog" in workflow
    assert 'doctl apps update "$PROD_APP_ID" --spec "$baseline_spec" --wait' in workflow
    assert "cdc-historical-sample" not in workflow
    assert "run-production-schedule" in workflow


def test_protected_prod_historical_recovery_reuses_exact_retained_run() -> None:
    workflow = Path(".github/workflows/run-prod-cdc-dbt-recovery.yml").read_text(encoding="utf-8")
    assert "historical-dbt-recovery" in workflow
    assert "recover-approved-cdc-historical --source-version-id" in workflow
    assert "--ingestion-run-id $INGESTION_RUN_ID" in workflow
    assert '[[ "$INGESTION_RUN_ID" =~' in workflow
    assert '.name = "cdc-dbt-recovery-once"' in workflow
    assert '.kind = "PRE_DEPLOY"' in workflow and "del(.schedule)" in workflow
    assert 'doctl apps update "$PROD_APP_ID" --spec "$promoted_spec" --wait' in workflow


def test_protected_prod_historical_rollback_is_retained_revision_guarded() -> None:
    workflow = Path(".github/workflows/rollback-prod-cdc-historical.yml").read_text(
        encoding="utf-8"
    )
    assert "environment: production" in workflow
    assert "group: prod-cdc-historical-ingestion" in workflow
    assert '"cdc-historical-rollback-once"' in workflow
    assert "rollback-cdc-historical --source-version-id" in workflow
    assert "--ingestion-run-id" in workflow and "--expected-revision" in workflow
    assert '.kind = "PRE_DEPLOY"' in workflow and "del(.schedule)" in workflow
    assert "list-deployments" in workflow and 'test "$dev_verified" = true' in workflow
    assert 'doctl apps update "$PROD_APP_ID" --spec "$baseline_spec" --wait' in workflow
    assert "DELETE" not in workflow


def test_deployment_fixture_uses_current_historical_environment_guard() -> None:
    fixture = Path("scripts/verify_historical_cdc_dev.py").read_text(encoding="utf-8")
    assert "historical.require_governed_environment()" in fixture
    assert "historical.require_dev()" not in fixture


def test_protected_prod_approved_ingestion_reuses_a_dev_tested_digest() -> None:
    workflow = Path(".github/workflows/run-prod-approved-ingestion.yml").read_text(encoding="utf-8")
    assert "environment: production" in workflow
    assert "group: prod-approved-ingestion" in workflow
    assert "DEV_APP_ID: b33dbae7-e243-4e27-b3ca-1018f5897f87" in workflow
    assert '"approved-source-ingestion"' in workflow
    assert '"approved-source-ingestion-once"' in workflow
    assert '"uv run atlas-data pipeline run-production-schedule"' in workflow
    assert 'doctl apps list-deployments "$DEV_APP_ID"' in workflow
    assert 'test "$dev_verified" = true' in workflow
    assert '.kind = "PRE_DEPLOY"' in workflow
    assert "del(.schedule)" in workflow
    assert 'doctl apps update "$PROD_APP_ID" --spec "$baseline_spec" --wait' in workflow
    assert "cdc-sample" not in workflow
    assert "ingest-approved-cdc" not in workflow
    assert "dbt run" not in workflow


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


def test_data_gov_catalog_registration_preserves_public_resources() -> None:
    datasets = normalize_catalog_payload(
        "DATA_GOV",
        {
            "results": [
                {
                    "identifier": "dataset-1",
                    "title": "Lyme surveillance",
                    "description": "Public metadata",
                    "accessLevel": "public",
                    "dcat": {
                        "identifier": "dataset-1",
                        "landingPage": "https://example.gov/lyme",
                        "describedBy": "https://example.gov/lyme/schema",
                        "distribution": [
                            {
                                "downloadURL": "https://example.gov/lyme.csv",
                                "accessURL": "https://api.example.gov/lyme",
                            }
                        ],
                    },
                }
            ]
        },
    )
    assert datasets[0].dataset_key == "data_gov:dataset-1"
    assert {resource.resource_type for resource in datasets[0].resources} == {
        "API",
        "DATA",
        "DOCUMENTATION",
        "LANDING_PAGE",
    }
    assert all(resource.canonical_source_url for resource in datasets[0].resources)


def test_data_gov_catalog_registration_accepts_null_optional_arrays() -> None:
    datasets = normalize_catalog_payload(
        "DATA_GOV",
        {
            "results": [
                {
                    "identifier": "dataset-null-arrays",
                    "title": "Lyme surveillance",
                    "dcat": {
                        "identifier": "dataset-null-arrays",
                        "distribution": None,
                        "references": None,
                    },
                }
            ]
        },
    )
    assert datasets[0].dataset_key == "data_gov:dataset-null-arrays"
    assert datasets[0].resources == ()


def test_socrata_catalog_registration_creates_api_candidate() -> None:
    datasets = normalize_catalog_payload(
        "HEALTHDATA_GOV",
        {
            "results": [
                {
                    "permalink": "https://data.example.gov/d/abcd-1234",
                    "resource": {
                        "id": "abcd-1234",
                        "name": "Public health dataset",
                        "description": "Metadata only",
                    },
                    "metadata": {"domain": "data.example.gov", "tags": ["lyme"]},
                }
            ]
        },
    )
    api = next(resource for resource in datasets[0].resources if resource.resource_type == "API")
    assert api.api_dataset_id == "abcd-1234"
    assert api.canonical_source_url == "https://data.example.gov/resource/abcd-1234.json"


def test_catalog_registration_canonical_url_removes_secret_query_parameters() -> None:
    assert (
        canonicalize_public_url("HTTPS://Example.gov/data/?token=secret&format=json#ignore")
        == "https://example.gov/data?format=json"
    )


def test_catalog_registration_batches_dataset_resources_into_three_merges() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        def execute(self, query: str, parameters: tuple[object, ...]) -> None:
            self.calls.append((query, parameters))

    cursor = Cursor()
    dataset = CatalogDataset(
        catalog_id="DATA_GOV",
        catalog_record_id="dataset-1",
        dataset_key="data_gov:dataset-1",
        payload={"title": "Example"},
        resources=(
            CatalogResource("API", "https://example.gov/api", "https://example.gov/api", None, {}),
            CatalogResource(
                "DATA", "https://example.gov/data", "https://example.gov/data", None, {}
            ),
        ),
    )

    assert (
        _write_registration_dataset_batch(
            cursor,
            [
                RegistrationDataset(
                    dataset,
                    artifact_id="artifact-id",
                    ingestion_run_id="run-id",
                    ingestion_request_id="request-id",
                    term="lyme",
                )
            ],
            observed_at=datetime(2026, 8, 26, tzinfo=UTC),
        )
        == 2
    )
    assert len(cursor.calls) == 3
    assert all("FLATTEN(input => PARSE_JSON(%s))" in query for query, _ in cursor.calls)
    assert '"catalog_dataset_id"' in str(cursor.calls[0][1][1])
    assert all('"catalog_resource_id"' in str(parameters[1]) for _, parameters in cursor.calls[1:])


def test_catalog_registration_logs_each_merge_statement_without_payloads(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class Cursor:
        sfqid = "safe-query-id"

        def execute(self, _query: str, _parameters: tuple[object, ...]) -> None:
            return None

    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._registration_memory_context",
        lambda: {
            "cgroup_memory_mode": "unavailable",
            "cgroup_memory_current_bytes": None,
            "cgroup_memory_limit_bytes": None,
            "cgroup_memory_events": {},
            "process_rss_bytes": 100,
            "process_peak_rss_bytes": 200,
            "process_virtual_memory_bytes": 300,
            "process_thread_count": 4,
            "process_rusage_maxrss_bytes": 200,
        },
    )
    progress = RegistrationProgress("run-id", artifact_id="artifact-id")
    dataset = CatalogDataset(
        "DATA_GOV",
        "dataset-1",
        "data_gov:dataset-1",
        {"private_payload": "must-not-be-recorded"},
        (CatalogResource("API", "https://example.gov/api?token=secret", None, None, {}),),
    )

    with caplog.at_level(logging.INFO, logger="lyme_gap_atlas_data.catalog_registration"):
        _write_registration_dataset_batch(
            Cursor(),
            [RegistrationDataset(dataset, "artifact-id", "run-id", "request-id", "lyme")],
            observed_at=datetime(2026, 8, 26, tzinfo=UTC),
            progress=progress,
            catalog_id="DATA_GOV",
            dataset_offset=7,
        )

    events = [
        record
        for record in caplog.records
        if record.getMessage().startswith("catalog_registration.merge_operation_")
    ]
    assert [record.getMessage() for record in events] == [
        "catalog_registration.merge_operation_started",
        "catalog_registration.merge_operation_completed",
        "catalog_registration.merge_operation_started",
        "catalog_registration.merge_operation_completed",
        "catalog_registration.merge_operation_started",
        "catalog_registration.merge_operation_completed",
    ]
    assert [record.context["operation"] for record in events[::2]] == [
        "catalog_datasets",
        "catalog_resources",
        "catalog_discovery_observations",
    ]
    assert all(record.context["dataset_offset"] == 7 for record in events)
    assert all(record.context["snowflake_query_id"] == "safe-query-id" for record in events[1::2])
    assert "must-not-be-recorded" not in repr([record.context for record in events])
    assert "token=secret" not in repr([record.context for record in events])


def test_catalog_registration_merge_span_contains_only_safe_correlation_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Span:
        def __init__(self) -> None:
            self.attributes: dict[str, object] = {}

        def __enter__(self) -> object:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def set_attribute(self, name: str, value: object) -> None:
            self.attributes[name] = value

        def set_status(self, _status: object) -> None:
            return None

    class Tracer:
        def __init__(self) -> None:
            self.span = Span()

        def start_as_current_span(self, _name: str) -> Span:
            return self.span

    class Cursor:
        sfqid = "safe-query-id"

        def execute(self, _query: str, _parameters: tuple[object, ...]) -> None:
            return None

    tracer = Tracer()
    monkeypatch.setattr("lyme_gap_atlas_data.catalog_registration._TRACER", tracer)
    _execute_registration_merge(
        Cursor(),
        "private SQL text",
        ("token=must-not-be-recorded",),
        progress=RegistrationProgress("run-id", artifact_id="artifact-id"),
        operation="catalog_resources",
        catalog_id="DATA_GOV",
        dataset_offset=7,
        row_count=100,
    )

    assert {
        key: value for key, value in tracer.span.attributes.items() if key != "atlas.duration_ms"
    } == {
        "atlas.registration.run_id": "run-id",
        "atlas.registration.artifact_id": "artifact-id",
        "atlas.registration.catalog_id": "DATA_GOV",
        "atlas.registration.dataset_offset": 7,
        "atlas.registration.row_count": 100,
        "atlas.registration.merge_operation": "catalog_resources",
        "db.snowflake.query_id": "safe-query-id",
    }
    assert isinstance(tracer.span.attributes["atlas.duration_ms"], int)
    assert "must-not-be-recorded" not in repr(tracer.span.attributes)
    assert "private SQL text" not in repr(tracer.span.attributes)


def test_catalog_registration_chunks_large_resource_merges() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        def execute(self, query: str, parameters: tuple[object, ...]) -> None:
            self.calls.append((query, parameters))

    resources = tuple(
        CatalogResource("DATA", f"https://example.gov/{index}", None, None, {})
        for index in range(1_001)
    )
    dataset = CatalogDataset("DATA_GOV", "dataset-1", "key", {}, resources)
    cursor = Cursor()

    assert (
        _write_registration_dataset_batch(
            cursor,
            [RegistrationDataset(dataset, "artifact", "run", "request", "lyme")],
            observed_at=datetime(2026, 8, 26, tzinfo=UTC),
        )
        == 1_001
    )
    assert len(cursor.calls) == 23
    resource_payload_sizes = [
        len(json.loads(parameters[1]))
        for query, parameters in cursor.calls
        if "CATALOG_RESOURCES" in query or "CATALOG_DISCOVERY_OBSERVATIONS" in query
    ]
    assert resource_payload_sizes == [100] * 20 + [1, 1]


def test_catalog_registration_checkpoints_each_resource_observation_slice() -> None:
    class Cursor:
        def execute(self, _query: str, _parameters: tuple[object, ...]) -> None:
            return None

    class Connection:
        def __init__(self) -> None:
            self.commits = 0

        def commit(self) -> None:
            self.commits += 1

    resources = tuple(
        CatalogResource("DATA", f"https://example.gov/{index}", None, None, {})
        for index in range(201)
    )
    connection = Connection()
    dataset = CatalogDataset("DATA_GOV", "dataset-1", "key", {}, resources)

    assert (
        _write_registration_dataset_batch(
            Cursor(),
            [RegistrationDataset(dataset, "artifact", "run", "request", "lyme")],
            observed_at=datetime(2026, 8, 26, tzinfo=UTC),
            connection=connection,
        )
        == 201
    )
    assert connection.commits == 3


def test_catalog_registration_claims_an_eligible_batch_with_set_based_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Cursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        def execute(self, query: str, parameters: tuple[object, ...]) -> None:
            self.calls.append((query, parameters))

        def fetchall(self) -> list[tuple[str, int]] | list[tuple[str]]:
            if len(self.calls) == 2:
                return [("artifact-a",), ("artifact-b",)]
            return [("artifact-a", 4), ("artifact-b", 0)]

    artifacts = [
        ("artifact-a", "run-a", "request-a", "lyme", "catalog-a", "object-a"),
        ("artifact-b", "run-b", "request-b", "lyme", "catalog-b", "object-b"),
        ("artifact-c", "run-c", "request-c", "lyme", "catalog-c", "object-c"),
    ]
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._completed_artifacts", lambda *_: artifacts
    )
    cursor = Cursor()

    claimed, available = _claim_registration_batch(cursor, "a" * 64, 2, "registration-run")

    assert available == 3
    assert claimed == [(*artifacts[0], 4), (*artifacts[1], 0)]
    assert len(cursor.calls) == 4
    assert "status IN ('PENDING', 'FAILED')" in cursor.calls[1][0]
    assert "lease_expires_at <= CURRENT_TIMESTAMP()" in cursor.calls[1][0]
    assert "WHEN 'PENDING' THEN 0" in cursor.calls[1][0]
    assert all(
        "FLATTEN(input => PARSE_JSON(%s))" in query
        for query, _ in (cursor.calls[0], cursor.calls[2], cursor.calls[3])
    )
    assert '"artifact-c"' not in str(cursor.calls[2][1])


def test_catalog_registration_continues_after_one_artifact_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Cursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        def __enter__(self) -> "Cursor":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, query: str, parameters: tuple[object, ...]) -> None:
            self.calls.append((query, parameters))

        def fetchone(self) -> tuple[int]:
            return (1,)

    class Connection:
        def __init__(self) -> None:
            self.cursor_instance = Cursor()
            self.commits = 0
            self.rollbacks = 0

        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def autocommit(self, _enabled: bool) -> None:
            return None

        def cursor(self) -> Cursor:
            return self.cursor_instance

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            self.rollbacks += 1

    connection = Connection()
    artifacts = [
        ("artifact-failed", "run", "request", "s3://bucket/failed", "DATA_GOV", "term", 0),
        ("artifact-good", "run", "request", "s3://bucket/good", "DATA_GOV", "term", 0),
    ]
    monkeypatch.setattr("lyme_gap_atlas_data.catalog_registration.connect", lambda _: connection)
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._spaces_client", lambda _: object()
    )
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._claim_registration_batch",
        lambda *_: (artifacts, 2),
    )
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._read_artifact_payload",
        lambda _s3, _settings, uri: (
            (_ for _ in ()).throw(OSError("unavailable")) if uri.endswith("failed") else {}
        ),
    )
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration.normalize_catalog_payload", lambda *_: []
    )

    result = register_completed_discovery("a" * 64, maximum_artifacts=2)

    assert result["failed_artifacts"] == 1
    assert result["observed_artifacts"] == 1
    assert connection.rollbacks == 0
    # Claim, artifact outcome, and durable invocation summary commit separately.
    assert connection.commits == 3
    assert any("SET status = 'FAILED'" in query for query, _ in connection.cursor_instance.calls)
    assert any("SET status = 'COMPLETED'" in query for query, _ in connection.cursor_instance.calls)


def test_catalog_registration_releases_unread_artifacts_at_dataset_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Cursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        def __enter__(self) -> "Cursor":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, query: str, parameters: tuple[object, ...]) -> None:
            self.calls.append((query, parameters))

        def fetchone(self) -> tuple[int]:
            return (0,)

    class Connection:
        def __init__(self) -> None:
            self.cursor_instance = Cursor()
            self.commits = 0

        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def autocommit(self, _enabled: bool) -> None:
            return None

        def cursor(self) -> Cursor:
            return self.cursor_instance

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            return None

    connection = Connection()
    artifacts = [
        ("artifact-first", "run", "request", "s3://bucket/first", "DATA_GOV", "term", 0),
        ("artifact-deferred", "run", "request", "s3://bucket/deferred", "DATA_GOV", "term", 0),
    ]
    dataset = CatalogDataset("DATA_GOV", "record", "key", {}, ())
    monkeypatch.setattr("lyme_gap_atlas_data.catalog_registration.connect", lambda _: connection)
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._spaces_client", lambda _: object()
    )
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._claim_registration_batch",
        lambda *_: (artifacts, 2),
    )
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._read_artifact_payload", lambda *_: {}
    )
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration.normalize_catalog_payload", lambda *_: [dataset]
    )

    register_completed_discovery("a" * 64, maximum_artifacts=2, maximum_datasets=1)

    assert any(
        "SET status = 'PENDING', lease_expires_at = NULL" in query
        and parameters[0] == "artifact-deferred"
        for query, parameters in connection.cursor_instance.calls
    )


def test_catalog_registration_commits_each_dataset_chunk_before_a_later_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Cursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...]]] = []

        def __enter__(self) -> "Cursor":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, query: str, parameters: tuple[object, ...]) -> None:
            self.calls.append((query, parameters))

        def fetchone(self) -> tuple[int]:
            return (0,)

    class Connection:
        def __init__(self) -> None:
            self.cursor_instance = Cursor()
            self.commits = 0
            self.rollbacks = 0

        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def autocommit(self, _enabled: bool) -> None:
            return None

        def cursor(self) -> Cursor:
            return self.cursor_instance

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            self.rollbacks += 1

    connection = Connection()
    artifact = ("artifact", "run", "request", "s3://bucket/artifact", "DATA_GOV", "term", 0)
    datasets = [CatalogDataset("DATA_GOV", str(index), str(index), {}, ()) for index in range(51)]
    calls = 0

    def write_chunk(*_args: object, **_kwargs: object) -> int:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("chunk timeout")
        return 0

    monkeypatch.setattr("lyme_gap_atlas_data.catalog_registration.connect", lambda _: connection)
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._spaces_client", lambda _: object()
    )
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._claim_registration_batch",
        lambda *_: ([artifact], 1),
    )
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._read_artifact_payload", lambda *_: {}
    )
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration.normalize_catalog_payload", lambda *_: datasets
    )
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._write_registration_dataset_batch", write_chunk
    )

    with pytest.raises(RuntimeError, match="chunk timeout"):
        register_completed_discovery("a" * 64, maximum_artifacts=1, maximum_datasets=51)

    assert connection.rollbacks == 1
    assert connection.commits >= 3
    assert any(
        "SET next_dataset_offset = %s" in query and parameters[0] == 50
        for query, parameters in connection.cursor_instance.calls
    )
    assert any("SET status = 'FAILED'" in query for query, _ in connection.cursor_instance.calls)


def test_catalog_registration_reads_only_completed_discovery_chains() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def execute(self, query: str, _parameters: tuple[str]) -> None:
            self.queries.append(query)

        def fetchone(self) -> tuple[int]:
            return (1,)

        def fetchall(self) -> list[tuple[str, str, str, str, str, str]]:
            return []

    cursor = Cursor()
    assert _completed_artifacts(cursor, "a" * 64) == []
    assert "status = 'COMPLETED'" in cursor.queries[0]
    assert "WITH RECURSIVE completed_chain" in cursor.queries[1]
    assert "resumed_from_ingestion_run_id" in cursor.queries[1]


def test_latest_completed_discovery_config_requires_a_completed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Cursor:
        def execute(self, query: str) -> None:
            assert "status = 'COMPLETED'" in query

        def fetchone(self) -> None:
            return None

        def __enter__(self) -> "Cursor":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr("lyme_gap_atlas_data.catalog_registration.connect", lambda _: Connection())
    with pytest.raises(ValueError, match="No completed catalog-discovery"):
        latest_completed_discovery_config_sha256()


def test_discover_registers_only_after_a_completed_run(monkeypatch: pytest.MonkeyPatch) -> None:
    emitted: list[str] = []
    monkeypatch.setattr(
        cli,
        "run_discovery",
        lambda **_: {"status": "COMPLETED", "config_sha256": "a" * 64},
    )
    monkeypatch.setattr(
        cli,
        "register_completed_discovery",
        lambda config_sha256: {"status": "COMPLETED", "config_sha256": config_sha256},
    )
    monkeypatch.setattr(cli.typer, "echo", emitted.append)

    cli.discover()

    assert json.loads(emitted[0])["candidate_registration"]["status"] == "COMPLETED"


def test_discover_does_not_register_a_paused_run(monkeypatch: pytest.MonkeyPatch) -> None:
    emitted: list[str] = []
    monkeypatch.setattr(
        cli,
        "run_discovery",
        lambda **_: {"status": "PAUSED", "config_sha256": "a" * 64},
    )
    monkeypatch.setattr(
        cli,
        "register_completed_discovery",
        lambda _: pytest.fail("paused discovery must not register candidates"),
    )
    monkeypatch.setattr(cli.typer, "echo", emitted.append)

    cli.discover()

    assert "candidate_registration" not in json.loads(emitted[0])


def test_registration_command_emits_safe_failure_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[str] = []
    error = RuntimeError("registration failed")
    monkeypatch.setattr(
        cli,
        "register_latest_completed_discovery",
        lambda *_: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(cli.typer, "echo", emitted.append)

    with pytest.raises(RuntimeError, match="registration failed"):
        cli.register_latest_discovery()

    assert json.loads(emitted[0]) == {
        "status": "FAILED",
        "operation": "catalog_registration",
        "error_type": "RuntimeError",
        "error_code": None,
        "sql_state": None,
        "snowflake_query_id": None,
    }


def test_registration_failure_emits_one_safe_terminal_event_after_a_claim(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fail_after_claim(
        _config_sha256: str, _maximum_artifacts: int, _maximum_datasets: int, progress: object
    ) -> dict[str, int | str]:
        progress.phase = "dataset_merge"  # type: ignore[attr-defined]
        progress.artifact_id = "artifact-123"  # type: ignore[attr-defined]
        progress.claimed_artifacts = 12  # type: ignore[attr-defined]
        progress.available_artifacts = 4410  # type: ignore[attr-defined]
        raise RuntimeError("token=must-not-be-recorded")

    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._register_completed_discovery", fail_after_claim
    )

    with pytest.raises(RuntimeError, match="must-not-be-recorded"):
        register_completed_discovery("a" * 64, maximum_artifacts=12, maximum_datasets=1500)

    terminal_events = [
        record for record in caplog.records if record.getMessage() == "catalog_registration.failed"
    ]
    assert len(terminal_events) == 1
    context = terminal_events[0].context
    assert context["phase"] == "dataset_merge"
    assert context["artifact_id"] == "artifact-123"
    assert context["claimed_artifacts"] == 12
    assert context["available_artifacts"] == 4410
    assert context["retryable"] is False
    assert "must-not-be-recorded" not in repr(context)


def test_registration_phase_boundary_records_safe_cgroup_memory(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    values = {
        "memory.current": "419430400",
        "memory.max": "536870912",
        "memory.events": "low 0\nhigh 1\nmax 2\noom 3\noom_kill 4\nunknown 99",
    }
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._read_cgroup_file",
        lambda path: values.get(path.name),
    )
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._process_memory_context",
        lambda: {
            "process_rss_bytes": 1,
            "process_peak_rss_bytes": 2,
            "process_virtual_memory_bytes": 3,
            "process_thread_count": 4,
            "process_rusage_maxrss_bytes": 5,
        },
    )
    progress = RegistrationProgress(
        registration_run_id="run-123",
        artifact_id="artifact-123",
        claimed_artifacts=12,
        available_artifacts=4410,
    )

    with caplog.at_level(logging.INFO, logger="lyme_gap_atlas_data.catalog_registration"):
        _log_registration_phase(progress, "artifact_read", catalog_id="DATA_GOV", dataset_offset=0)

    event = next(
        record
        for record in caplog.records
        if record.getMessage() == "catalog_registration.phase_started"
    )
    assert progress.phase == "artifact_read"
    assert event.context == {
        "registration_run_id": "run-123",
        "phase": "artifact_read",
        "artifact_id": "artifact-123",
        "catalog_id": "DATA_GOV",
        "dataset_offset": 0,
        "dataset_count": None,
        "claimed_artifacts": 12,
        "available_artifacts": 4410,
        "cgroup_memory_mode": "v2",
        "cgroup_memory_current_bytes": 419430400,
        "cgroup_memory_limit_bytes": 536870912,
        "cgroup_memory_events": {"low": 0, "high": 1, "max": 2, "oom": 3, "oom_kill": 4},
        "process_rss_bytes": 1,
        "process_peak_rss_bytes": 2,
        "process_virtual_memory_bytes": 3,
        "process_thread_count": 4,
        "process_rusage_maxrss_bytes": 5,
    }


def test_cgroup_memory_context_is_safe_when_files_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._read_cgroup_file", lambda _path: None
    )

    assert _cgroup_memory_context() == {
        "cgroup_memory_mode": "unavailable",
        "cgroup_memory_current_bytes": None,
        "cgroup_memory_limit_bytes": None,
        "cgroup_memory_events": {},
    }


def test_cgroup_memory_context_uses_v1_when_v2_files_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "memory.usage_in_bytes": "419430400",
        "memory.limit_in_bytes": "536870912",
        "memory.failcnt": "2",
    }
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._read_cgroup_file",
        lambda path: values.get(path.name),
    )

    assert _cgroup_memory_context() == {
        "cgroup_memory_mode": "v1",
        "cgroup_memory_current_bytes": 419430400,
        "cgroup_memory_limit_bytes": 536870912,
        "cgroup_memory_events": {"failcnt": 2},
    }


def test_process_memory_context_reads_only_numeric_status_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "lyme_gap_atlas_data.catalog_registration._read_process_status",
        lambda: (
            "Name:\tprivate-command\nVmRSS:\t100 kB\nVmHWM:\t200 kB\nVmSize:\t300 kB\nThreads:\t4\n"
        ),
    )

    context = _process_memory_context()

    assert context["process_rss_bytes"] == 102400
    assert context["process_peak_rss_bytes"] == 204800
    assert context["process_virtual_memory_bytes"] == 307200
    assert context["process_thread_count"] == 4
    assert "private-command" not in repr(context)


def test_registration_command_reuses_the_worker_terminal_event(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    emitted: list[str] = []
    error = RuntimeError("private detail")
    diagnostics = {
        "operation": "catalog_registration",
        "registration_run_id": "run-123",
        "phase": "remaining_count",
        "error_type": "RuntimeError",
    }
    setattr(error, "catalog_registration_diagnostics", diagnostics)  # noqa: B010
    setattr(error, "catalog_registration_terminal_emitted", True)  # noqa: B010
    monkeypatch.setattr(
        cli,
        "register_latest_completed_discovery",
        lambda *_: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(cli.typer, "echo", emitted.append)

    with pytest.raises(RuntimeError, match="private detail"):
        cli.register_latest_discovery()

    assert json.loads(emitted[0]) == {"status": "FAILED", **diagnostics}
    assert not [
        record for record in caplog.records if record.getMessage() == "catalog_registration.failed"
    ]


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


def test_dbt_build_uses_an_ephemeral_key_file_for_base64_runtime_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_bytes = b"test-private-key"
    captured: dict[str, str] = {}

    def run_dbt(*_: object, env: dict[str, str], **__: object) -> SimpleNamespace:
        key_path = Path(env["SNOWFLAKE_PRIVATE_KEY_PATH"])
        assert key_path.read_bytes() == key_bytes
        captured["key_path"] = str(key_path)
        return SimpleNamespace(returncode=0)

    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_B64", base64.b64encode(key_bytes).decode())
    monkeypatch.delenv("SNOWFLAKE_PRIVATE_KEY_PATH", raising=False)
    monkeypatch.setattr(cdc.subprocess, "run", run_dbt)
    monkeypatch.setattr(cdc, "record_cdc_quality", lambda *args, **kwargs: {"validation_id": "v"})

    assert build_approved_cdc_models("source-version-1") == {
        "source_version_id": "source-version-1",
        "status": "COMPLETED",
        "publication_status": "PUBLISHED",
    }
    assert not Path(captured["key_path"]).exists()


def test_dbt_failure_logs_only_a_controlled_private_key_classification(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        cdc.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="private key could not be parsed"
        ),
    )
    with pytest.raises(RuntimeError, match=r"CDC dbt build failed \[PRIVATE_KEY_AUTH\]"):
        build_approved_cdc_models("source-version-1")
    assert "CDC_DBT_DIAGNOSTIC=PRIVATE_KEY_AUTH" in caplog.text
    assert "private key could not be parsed" not in caplog.text


@pytest.mark.parametrize(
    "adapter_error",
    [
        "Bad decrypt. Incorrect password?",
        "Could not deserialize key data",
    ],
)
def test_dbt_failure_classifies_encrypted_key_adapter_errors_without_logging_them(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, adapter_error: str
) -> None:
    monkeypatch.setattr(
        cdc.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr=adapter_error),
    )

    with pytest.raises(RuntimeError, match=r"CDC dbt build failed \[PRIVATE_KEY_AUTH\]"):
        build_approved_cdc_models("source-version-1")

    assert "CDC_DBT_DIAGNOSTIC=PRIVATE_KEY_AUTH" in caplog.text
    assert adapter_error not in caplog.text


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
        "V025",
        "V026",
        "V027",
        "V028",
        "V029",
        "V030",
        "V031",
        "V032",
        "V033",
        "V034",
        "V035",
        "V036",
        "V037",
        "V038",
        "V039",
        "V040",
        "V041",
        "V042",
        "V043",
        "V044",
        "V045",
        "V046",
        "V047",
        "V048",
        "V049",
        "V050",
        "V051",
        "V052",
        "V053",
        "V054",
        "V055",
        "V056",
        "V057",
        "V058",
        "V059",
        "V060",
        "V061",
    ]
    assert "ONE_HEALTH_LYME_GAP_ATLAS_DEV" in render_migration(
        migrations[0], "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
    )
    with pytest.raises(ValueError, match="only"):
        render_migration(migrations[0], "ONE_HEALTH_LYME_GAP_ATLAS")
    prod_plan = migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    assert len(prod_plan) == 44
    assert "V034" not in {item["version"] for item in prod_plan}
    operations_console = next(item.source for item in migrations if item.version == "V039")
    assert "CATALOG_REGISTRATION_RUNS" in operations_console
    assert "V_PIPELINE_COMMAND_CENTER" in operations_console
    assert "GRANT SELECT ON TABLE GOVERNANCE.INGESTION_RUNS" not in operations_console
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
    v041 = next(item for item in migrations if item.version == "V041")
    assert migration_execution_role(v041, DEV_DATABASE) == "OH_LYME_DEV_GOVERNED_VIEW_OWNER"
    assert migration_execution_role(v041, "ONE_HEALTH_LYME_GAP_ATLAS_PROD") == (
        "OH_LYME_PROD_GOVERNED_VIEW_OWNER"
    )
    assert migration_execution_role(migrations[0], DEV_DATABASE) is None


def test_dev_pmc_budget_repair_preserves_the_fail_closed_runtime_boundary() -> None:
    migrations = {item.version: item for item in load_migrations()}
    repair = migrations["V055"]
    with pytest.raises(ValueError, match="DEV-only"):
        render_migration(repair, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    assert "V055" not in {
        item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    }
    assert "EXECUTE AS OWNER" in repair.source
    assert "GOVERNANCE.LLM_BUDGET_USAGE" in repair.source
    assert "GRANT USAGE ON PROCEDURE GOVERNANCE.SP_RESERVE_KG_LLM_BUDGET" in repair.source
    assert "OH_LYME_{{ ENV }}_PIPELINE_RUNTIME" in repair.source
    assert "OH_LYME_{{ ENV }}_API_RUNTIME" in repair.source
    assert "GRANT SELECT ON TABLE GOVERNANCE.LLM_BUDGET_USAGE" not in repair.source


def test_dev_pmc_budget_owner_is_dedicated_and_fail_closed() -> None:
    owner_migration = next(item for item in load_migrations() if item.version == "V056")
    assert migration_execution_role(owner_migration, DEV_DATABASE) == (
        "OH_LYME_DEV_KG_LLM_BUDGET_OWNER"
    )
    with pytest.raises(ValueError, match="DEV PMC budget-owner migration is DEV-only"):
        migration_execution_role(owner_migration, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    assert "V056" not in {
        item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    }
    assert "EXECUTE AS OWNER" in owner_migration.source
    assert "GOVERNANCE.LLM_BUDGET_USAGE" in owner_migration.source
    assert "OH_LYME_{{ ENV }}_PIPELINE_RUNTIME" in owner_migration.source
    assert "OH_LYME_{{ ENV }}_API_RUNTIME" in owner_migration.source
    assert "GRANT SELECT ON TABLE GOVERNANCE.LLM_BUDGET_USAGE" not in owner_migration.source


def test_dev_pmc_budget_reservation_uses_select_for_generated_identifier() -> None:
    repair = next(item for item in load_migrations() if item.version == "V057")
    assert migration_execution_role(repair, DEV_DATABASE) == "OH_LYME_DEV_KG_LLM_BUDGET_OWNER"
    assert "INSERT INTO GOVERNANCE.LLM_BUDGET_USAGE (" in repair.source
    assert ") SELECT UUID_STRING()" in repair.source
    assert "INSERT INTO GOVERNANCE.LLM_BUDGET_USAGE VALUES" not in repair.source
    assert "V057" not in {
        item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    }


def test_dev_pmc_review_view_grant_preserves_the_streamlit_boundary() -> None:
    repair = next(item for item in load_migrations() if item.version == "V058")
    with pytest.raises(ValueError, match="DEV-only"):
        render_migration(repair, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    assert "V058" not in {
        item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    }
    assert "GRANT SELECT ON VIEW GOVERNANCE.V_KG_PAPER_REVIEW_QUEUE" in repair.source
    assert "OH_LYME_{{ ENV }}_STREAMLIT_OWNER" in repair.source
    assert "KNOWLEDGE_GRAPH.PAPERS" not in repair.source


def test_dev_pmc_review_procedure_uses_unambiguous_parameter_names() -> None:
    repair = next(item for item in load_migrations() if item.version == "V059")
    with pytest.raises(ValueError, match="DEV-only"):
        render_migration(repair, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    assert "P_DECISION VARCHAR" in repair.source
    assert ":P_DECISION" in repair.source
    assert "IF (DECISION NOT IN" not in repair.source
    assert "GRANT USAGE ON PROCEDURE GOVERNANCE.SP_RECORD_PAPER_REVIEW_BATCH" in repair.source


def test_dev_pmc_budget_finalization_is_append_only_and_fail_closed() -> None:
    repair = next(item for item in load_migrations() if item.version == "V061")
    assert migration_execution_role(repair, DEV_DATABASE) == "OH_LYME_DEV_KG_LLM_BUDGET_OWNER"
    with pytest.raises(ValueError, match="DEV-only"):
        render_migration(repair, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    assert "V061" not in {
        item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    }
    assert "CREATE TABLE IF NOT EXISTS GOVERNANCE.LLM_BUDGET_FINALIZATIONS" in repair.source
    assert "SP_FINALIZE_KG_LLM_BUDGET" in repair.source
    assert "f.status = 'failed'" in repair.source
    assert "UPDATE GOVERNANCE.LLM_BUDGET_USAGE" not in repair.source
    assert "DELETE FROM GOVERNANCE.LLM_BUDGET_USAGE" not in repair.source
    assert "GRANT USAGE ON PROCEDURE GOVERNANCE.SP_FINALIZE_KG_LLM_BUDGET" in repair.source
    assert "OH_LYME_DEV_PIPELINE_RUNTIME" in repair.source
    assert "FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS a" in repair.source
    assert "a.status = 'failed'" in repair.source
    assert "OR NOT EXISTS" in repair.source


def test_cdc_evidence_grants_are_limited_to_evidence_writes() -> None:
    evidence_grants = next(item.source for item in load_migrations() if item.version == "V042")
    for table_name in (
        "CATALOG_DATASETS",
        "CATALOG_RESOURCES",
        "SOURCE_ACCESS_PROFILES",
        "SOURCE_DOCUMENT_SNAPSHOTS",
        "SCHEMA_SNAPSHOTS",
        "DATASET_QUALITY_ASSESSMENTS",
    ):
        assert f"GOVERNANCE.{table_name}" in evidence_grants
    assert "MANUAL_REVIEW_DECISIONS" not in evidence_grants
    assert "DATA_SOURCE_VERSIONS" not in evidence_grants
    assert "RAW.CDC_LYME_X5J9_WYBP" not in evidence_grants


def test_legacy_reconciliation_is_pinned_to_the_authorized_dev_mismatch_set() -> None:
    migrations = load_migrations()
    reconciliations = legacy_dev_reconciliation_plan(
        dict(LEGACY_DEV_MIGRATION_CHECKSUMS), migrations
    )
    assert [migration.version for migration in reconciliations] == ["V028", "V029", "V033"]
    assert all(
        migration.sha256 != LEGACY_DEV_MIGRATION_CHECKSUMS[migration.version]
        for migration in reconciliations
    )
    with pytest.raises(ValueError, match="Unexpected DEV ledger checksum"):
        legacy_dev_reconciliation_plan({"V028": "not-authorized"}, migrations)
    v028 = next(migration for migration in migrations if migration.version == "V028")
    assert is_authorized_legacy_reconciliation(
        DEV_DATABASE,
        "V028",
        LEGACY_DEV_MIGRATION_CHECKSUMS["V028"],
        v028.sha256,
        {"V028": (LEGACY_DEV_MIGRATION_CHECKSUMS["V028"], v028.sha256)},
    )
    assert not is_authorized_legacy_reconciliation(
        "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        "V029",
        LEGACY_DEV_MIGRATION_CHECKSUMS["V029"],
        next(migration for migration in migrations if migration.version == "V029").sha256,
        {
            "V029": (
                LEGACY_DEV_MIGRATION_CHECKSUMS["V029"],
                next(migration for migration in migrations if migration.version == "V029").sha256,
            )
        },
    )
    assert not is_authorized_legacy_reconciliation(
        DEV_DATABASE,
        "V001",
        "unapproved",
        "unapproved",
        {"V001": ("unapproved", "unapproved")},
    )
    assert DEV_DATABASE == "ONE_HEALTH_LYME_GAP_ATLAS_DEV"


def test_line_ending_equivalence_accepts_only_lf_or_crlf_serialization() -> None:
    source = "SELECT 1;\nSELECT 2;\n"
    lf_checksum = hashlib.sha256(source.encode()).hexdigest()
    crlf_checksum = hashlib.sha256(source.replace("\n", "\r\n").encode()).hexdigest()
    carriage_return_checksum = hashlib.sha256(source.replace("\n", "\r").encode()).hexdigest()
    changed_checksum = hashlib.sha256(b"SELECT 3;\n").hexdigest()

    assert is_line_ending_equivalent_checksum(source, lf_checksum)
    assert is_line_ending_equivalent_checksum(source, crlf_checksum)
    assert not is_line_ending_equivalent_checksum(source, carriage_return_checksum)
    assert not is_line_ending_equivalent_checksum(source, changed_checksum)


def test_prod_reconciliation_is_pinned_to_exact_variant_and_duplicate_rows() -> None:
    migrations = load_migrations()
    applied_rows = [
        (version, LEGACY_PROD_MIGRATION_FILENAMES[version], checksum)
        for version, checksum in LEGACY_PROD_MIGRATION_CHECKSUMS.items()
        for _ in range(LEGACY_PROD_MIGRATION_ROW_COUNTS[version])
    ]

    reconciliations = legacy_prod_reconciliation_plan(applied_rows, migrations)
    assert [migration.version for migration in reconciliations] == ["V022", "V028"]
    assert is_authorized_legacy_reconciliation(
        PROD_DATABASE,
        "V022",
        LEGACY_PROD_MIGRATION_CHECKSUMS["V022"],
        reconciliations[0].sha256,
        {
            "V022": (
                LEGACY_PROD_MIGRATION_CHECKSUMS["V022"],
                reconciliations[0].sha256,
            )
        },
    )

    with pytest.raises(ValueError, match="Unexpected PROD ledger shape for V028"):
        legacy_prod_reconciliation_plan(applied_rows[:-1], migrations)
    with pytest.raises(ValueError, match="Unexpected PROD ledger shape for V022"):
        legacy_prod_reconciliation_plan(
            [("V022", LEGACY_PROD_MIGRATION_FILENAMES["V022"], "not-authorized")]
            + applied_rows[1:],
            migrations,
        )

    assert not is_authorized_legacy_reconciliation(
        DEV_DATABASE,
        "V022",
        LEGACY_PROD_MIGRATION_CHECKSUMS["V022"],
        reconciliations[0].sha256,
        {
            "V022": (
                LEGACY_PROD_MIGRATION_CHECKSUMS["V022"],
                reconciliations[0].sha256,
            )
        },
    )


def test_prod_reconciliation_command_is_explicit_and_not_in_dev_deploy() -> None:
    cli_source = Path("src/lyme_gap_atlas_data/cli.py").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/deploy-dev.yml").read_text(encoding="utf-8")
    assert '@pipeline_app.command("reconcile-legacy-prod-migrations")' in cli_source
    assert "Pass --confirm to reconcile legacy PROD migrations" in cli_source
    assert "reconcile-legacy-prod-migrations" not in workflow


def test_v034_reasserts_the_redacted_observability_contract_after_legacy_reconciliation() -> None:
    source = next(
        migration.source for migration in load_migrations() if migration.version == "V034"
    )
    for view_name in (
        "V_PIPELINE_OBSERVABILITY_OVERVIEW",
        "V_PIPELINE_ARTIFACT_BACKLOG",
        "V_PIPELINE_DISCOVERY_RUNS",
        "V_PIPELINE_CATALOG_COVERAGE",
        "V_PIPELINE_REGISTRATION_OUTCOMES",
        "V_PIPELINE_SOURCE_GOVERNANCE",
    ):
        assert f"CREATE OR REPLACE VIEW GOVERNANCE.{view_name}" in source
    assert "object_key" not in source
    assert "payload" not in source


def test_dev_workflow_applies_checksum_validated_migrations_with_ephemeral_key() -> None:
    workflow = Path(".github/workflows/deploy-dev.yml").read_text(encoding="utf-8")
    assert "SNOWFLAKE_AUTH_METHOD=key_pair" in workflow
    assert 'SNOWFLAKE_PRIVATE_KEY_B64="$(base64 --wrap=0 "$key_file")"' in workflow
    assert 'SNOWFLAKE_PRIVATE_KEY_B64="$SNOWFLAKE_PRIVATE_KEY_B64"' not in workflow
    assert (
        "SELECT version, filename, sha256, applied_at FROM GOVERNANCE.SCHEMA_MIGRATIONS" in workflow
    )
    assert "reconcile-legacy-dev-migrations" in workflow
    assert "atlas-data pipeline apply-migrations" in workflow
    assert '--database "$SNOWFLAKE_DATABASE" --commit "$GITHUB_SHA" --confirm' in workflow
    assert 'trap \'rm -f "$key_file" "$config_file"\' EXIT' in workflow


def test_knowledge_graph_migrations_keep_runtime_privileges_and_history_access_narrow() -> None:
    migrations = load_migrations()
    migration_sources = {item.version: item.source for item in migrations}
    grants = migration_sources["V030"]
    assert "REVOKE INSERT, UPDATE ON ALL TABLES IN SCHEMA KNOWLEDGE_GRAPH" in grants
    assert "PAPERS" in grants
    assert "PAPER_QUERY_MATCHES" in grants
    assert "PMC_FULL_TEXT_ARTIFACTS" not in grants
    history = migration_sources["V031"]
    assert "EXECUTE AS OWNER" in history
    assert "token_hash = :TOKEN_HASH" in history
    assert "MAX_TURNS < 1 OR MAX_TURNS > 12" in history
    assert "GRANT SELECT ON TABLE GOVERNANCE.KG_CONVERSATION" not in history
    ledger = migration_sources["V032"]
    for field in ("pmid", "pmcid", "artifact_id", "license_url", "jats_sha256", "text_sha256"):
        assert field in ledger
    extraction_lineage = migration_sources["V035"]
    for field in ("lease_expires_at", "method_version", "extraction_attempt_id", "artifact_id"):
        assert field in extraction_lineage
    assert "ONE_HEALTH_LYME_GAP_ATLAS" not in extraction_lineage.replace("{{ DATABASE }}", "")
    paper_review_owner = migration_sources["V036"]
    assert "KG_PAPER_REVIEW_OWNER" in paper_review_owner
    assert (
        "GRANT OWNERSHIP ON PROCEDURE GOVERNANCE.SP_RECORD_PAPER_REVIEW_BATCH" in paper_review_owner
    )
    assert "GRANT SELECT, UPDATE ON TABLE KNOWLEDGE_GRAPH.PAPERS" in paper_review_owner
    assert "TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER" in paper_review_owner
    recovery = migration_sources["V037"]
    assert "GRANT OWNERSHIP ON VIEW GOVERNANCE.V_KG_PAPER_REVIEW_QUEUE" not in recovery
    assert "PAPER_QUERY_MATCHES" in recovery
    assert "DECISION = 'rejected' AND p.state IN ('retry_pending','retry_exhausted')" in recovery
    assert "GRANT OWNERSHIP ON PROCEDURE GOVERNANCE.SP_RECORD_PAPER_REVIEW_BATCH" not in recovery
    assert "GRANT USAGE ON PROCEDURE GOVERNANCE.SP_RECORD_PAPER_REVIEW_BATCH" in recovery
    streamlit_app = Path("streamlit_approval/streamlit_app.py").read_text(encoding="utf-8")
    assert "Recovery states can only be rejected" in streamlit_app
    assert '["rejected"] if recovery_selected' in streamlit_app
    recovery_procedure = migration_sources["V038"]
    assert "SP_REJECT_PMC_RECOVERY_BATCH" in recovery_procedure
    assert "p.state IN ('retry_pending','retry_exhausted')" in recovery_procedure
    assert "pmc_oa_recovery_rejection" in recovery_procedure
    assert "GRANT SELECT ON VIEW GOVERNANCE.V_KG_PAPER_REVIEW_QUEUE" in recovery_procedure
    assert "SP_REJECT_PMC_RECOVERY_BATCH(PARSE_JSON(?)" in streamlit_app
    approval_exception_fix = migration_sources["V040"]
    assert (
        "CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_RECORD_SOURCE_REVIEW_DECISION"
        in approval_exception_fix
    )
    assert "invalid_resource EXCEPTION (-20007" in approval_exception_fix
    assert "EXCEPTION (-20000" not in approval_exception_fix
    assert (
        "GRANT USAGE ON PROCEDURE GOVERNANCE.SP_RECORD_SOURCE_REVIEW_DECISION"
        in approval_exception_fix
    )
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
    registration = migrations[26].source
    assert "CATALOG_DISCOVERY_OBSERVATIONS" in registration
    assert "V_DISCOVERY_CANDIDATES" in registration
    assert "COLLECT_METADATA_AND_SAMPLE" in registration
    resumable_registration = migrations[27].source
    assert "CATALOG_DISCOVERY_REGISTRATIONS" in resumable_registration
    assert "lease_expires_at" in resumable_registration
    dataset_checkpoint = migrations[28].source
    assert "next_dataset_offset" in dataset_checkpoint
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
    assert '"ONE_HEALTH_LYME_GAP_ATLAS_PROD"' in source
    assert '"cdc_lyme_qtbi_xd4i": "CDC Lyme | 2008-2021 | qtbi-xd4i"' in source
