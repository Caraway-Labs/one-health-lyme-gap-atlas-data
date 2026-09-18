"""Operator CLI for the MVP Snowflake release."""

import json
import logging
import os
import sys
from contextlib import suppress
from pathlib import Path
from time import monotonic

import typer
from lyme_gap_atlas_shared.observability import configure_logging, configure_tracing
from lyme_gap_atlas_shared.settings import SnowflakeSettings
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .alpha_parity import (
    build_report,
    fetch_current_release_metadata,
    fetch_current_semantic_rows,
    fetch_current_source_metadata,
    write_report,
)
from .catalog_registration import register_completed_discovery, register_latest_completed_discovery
from .cdc import collect_cdc_evidence
from .cdc_operations import check_cdc_metadata, check_cdc_overdue, verify_cdc_ready
from .cdc_publication import bootstrap_publication, rollback_publication
from .cdc_quality import record_cdc_quality
from .database import load as load_release
from .database import provision as provision_database
from .database import status as database_status
from .database import validate_loaded
from .discovery import initial_requests, load_search_configuration
from .ingestion import (
    AdapterKind,
    FileCheckpointStore,
    IngestionOrchestrator,
    SnowflakeCheckpointStore,
    Tier,
    explain_run,
    load_source_definition,
    starter_definition_yaml,
)
from .migrations import (
    apply_migrations,
    migration_plan,
    reconcile_legacy_dev_migrations,
    reconcile_legacy_prod_migrations,
)
from .orchestration import (
    run_cdc_dbt_recovery,
    run_discovery,
    run_production_cdc_dbt_recovery,
    run_production_schedule,
)
from .pathogen_surveillance import (
    capture_and_ingest_restricted_pathogen_dev,
    collect_pathogen_surveillance_evidence,
    ingest_restricted_pathogen,
    ingest_restricted_pathogen_dev,
)
from .pmc_extraction_worker import run_pmc_extraction
from .preflight import run_preflight
from .pubmed_discovery import MAX_BATCH_SIZE, MAX_RECORDS_PER_RUN, discover_pubmed
from .retrieval_corpus import build_retrieval_corpus
from .semantic_release import (
    build_semantic_release,
    publish_semantic_release,
    rollback_semantic_release,
)
from .settings import PipelineSettings
from .streamlit_deploy import deploy_approval_console, deploy_data_explorer
from .tick_surveillance import collect_tick_surveillance_evidence, ingest_restricted_tick

SERVICE_NAME = "one-health-lyme-gap-atlas-data"


def _command_path(arguments: list[str]) -> str:
    """Return only command names, never user-supplied option values."""
    if not arguments:
        return "help"
    if arguments[0] == "pipeline":
        subcommand = arguments[1] if len(arguments) > 1 else "help"
        return "pipeline." + (subcommand if not subcommand.startswith("-") else "help")
    return arguments[0] if not arguments[0].startswith("-") else "help"


def _flush_and_shutdown_tracing() -> None:
    """Finish optional telemetry without allowing exporter failures to affect a command."""
    provider = trace.get_tracer_provider()
    for method_name in ("force_flush", "shutdown"):
        method = getattr(provider, method_name, None)
        if callable(method):
            with suppress(Exception):
                method()


class ObservedTyper(typer.Typer):
    """Typer app with one privacy-safe span around each short-lived CLI invocation."""

    def __call__(self, *args: object, **kwargs: object) -> object:
        configure_logging()
        configure_tracing(SERVICE_NAME)
        command = _command_path(sys.argv[1:])
        started = monotonic()
        try:
            # The current context lets safe, bounded child spans correlate to the
            # command that invoked them without adding command arguments to traces.
            with trace.get_tracer(SERVICE_NAME).start_as_current_span("atlas-data.cli") as span:
                span.set_attribute("atlas.command", command)
                span.set_attribute("atlas.environment", os.getenv("TOPX_ENV", "dev"))
                try:
                    result = super().__call__(*args, **kwargs)
                except BaseException as error:
                    failed = not isinstance(error, SystemExit) or error.code not in (None, 0)
                    span.set_attribute("atlas.outcome", "failure" if failed else "success")
                    if failed:
                        span.set_attribute("error.type", type(error).__name__)
                        span.set_status(Status(StatusCode.ERROR, type(error).__name__))
                    raise
                else:
                    span.set_attribute("atlas.outcome", "success")
                    return result
                finally:
                    span.set_attribute("atlas.duration_ms", int((monotonic() - started) * 1000))
        finally:
            _flush_and_shutdown_tracing()


app = ObservedTyper(no_args_is_help=True)
pipeline_app = typer.Typer(no_args_is_help=True)
source_app = typer.Typer(no_args_is_help=True)
runs_app = typer.Typer(no_args_is_help=True)
app.add_typer(pipeline_app, name="pipeline")
app.add_typer(source_app, name="source")
app.add_typer(runs_app, name="runs")
logger = logging.getLogger(__name__)

_DEFAULT_RUN_STORE = Path(".atlas-ingestion-runs")
_DEFAULT_SOURCE_DIR = "config/sources"
_DEFAULT_X5J9_DEFINITION = "config/sources/cdc_x5j9_wybp.yml"


def _orchestrator(
    fixture_dir: Path | None = None,
    *,
    tier: Tier = Tier.A,
    dry_run: bool = False,
) -> IngestionOrchestrator:
    store = (
        SnowflakeCheckpointStore()
        if tier in {Tier.B, Tier.C} and not dry_run
        else FileCheckpointStore(_DEFAULT_RUN_STORE)
    )
    return IngestionOrchestrator(
        store=store,
        fixture_dir=fixture_dir,
    )


def _orchestrator_for_run(run_id: str, fixture_dir: Path | None = None) -> IngestionOrchestrator:
    local = FileCheckpointStore(_DEFAULT_RUN_STORE)
    if local.load(run_id) is not None:
        return IngestionOrchestrator(store=local, fixture_dir=fixture_dir)
    if os.environ.get("SNOWFLAKE_ACCOUNT"):
        return IngestionOrchestrator(
            store=SnowflakeCheckpointStore(),
            fixture_dir=fixture_dir,
        )
    return IngestionOrchestrator(store=local, fixture_dir=fixture_dir)


def _run_store() -> FileCheckpointStore | SnowflakeCheckpointStore:
    """Use the durable warehouse ledger in worker containers, local files otherwise."""
    if os.environ.get("SNOWFLAKE_ACCOUNT"):
        return SnowflakeCheckpointStore()
    return FileCheckpointStore(_DEFAULT_RUN_STORE)


def _settings() -> SnowflakeSettings:
    return SnowflakeSettings()


def _safe_failure_diagnostics(error: Exception) -> dict[str, object | None]:
    """Return provider correlation fields without serializing exception text."""
    return {
        "error_type": type(error).__name__,
        "error_code": getattr(error, "errno", None),
        "sql_state": getattr(error, "sqlstate", None),
        "snowflake_query_id": getattr(error, "sfqid", None),
    }


@app.command()
def provision(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    """Create idempotent database objects and presentation views."""
    provision_database(_settings(), dry_run=dry_run)


@app.command("load")
def load_command(
    release: str = typer.Option(..., "--release"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Load the packaged immutable release."""
    load_release(_settings(), release, dry_run=dry_run)


@app.command("validate")
def validate_command(
    release: str = typer.Option(..., "--release"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Validate the loaded release."""
    if dry_run:
        typer.echo(f"Would validate the 3,144-county contract for {release}")
        return
    typer.echo(json.dumps(validate_loaded(_settings(), release), default=str, indent=2))


@app.command()
def status(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    """Show Snowflake release status."""
    if dry_run:
        typer.echo("Would read dataset release status from Snowflake")
        return
    typer.echo(json.dumps(database_status(_settings()), default=str, indent=2))


@pipeline_app.command("config-check")
def config_check(path: str = typer.Option("catalog-search-terms.json", "--path")) -> None:
    """Validate discovery input and print only its checksum and request count."""
    config, checksum = load_search_configuration(Path(path))
    typer.echo(json.dumps({"checksum": checksum, "request_count": len(initial_requests(config))}))


@pipeline_app.command("settings-check")
def settings_check() -> None:
    """Validate isolated DEV settings without printing secret values."""
    settings = PipelineSettings()
    typer.echo(
        json.dumps({"environment": settings.topx_env, "database": settings.snowflake_database})
    )


@pipeline_app.command("semantic-release-build")
def semantic_release_build_command(
    manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),  # noqa: B008
) -> None:
    """Build one source-pinned semantic release candidate."""
    typer.echo(json.dumps(build_semantic_release(_settings(), manifest), default=str))


@pipeline_app.command("semantic-release-publish")
def semantic_release_publish_command(
    release_id: str = typer.Option(..., "--release-id"),
    reason: str = typer.Option(..., "--reason"),
    approver: str | None = typer.Option(None, "--approver"),
    confirm: bool = typer.Option(False, "--confirm"),
) -> None:
    """Publish a previously built candidate through the protected workflow."""
    if not confirm:
        raise typer.BadParameter("Pass --confirm after release-candidate review")
    typer.echo(
        json.dumps(
            publish_semantic_release(_settings(), release_id, reason=reason, approver=approver),
            default=str,
        )
    )


@pipeline_app.command("semantic-release-rollback")
def semantic_release_rollback_command(
    release_id: str = typer.Option(..., "--release-id"),
    reason: str = typer.Option(..., "--reason"),
    confirm: bool = typer.Option(False, "--confirm"),
) -> None:
    """Point the API back to a retained governed semantic release."""
    if not confirm:
        raise typer.BadParameter("Pass --confirm after rollback review")
    typer.echo(
        json.dumps(
            rollback_semantic_release(_settings(), release_id, reason=reason),
            default=str,
        )
    )


@pipeline_app.command("alpha-parity-report")
def alpha_parity_report_command(
    release_id: str = typer.Option(..., "--release-id"),
    bundle_sha256: str = typer.Option(..., "--bundle-sha256"),
    methodology_version: str = typer.Option(..., "--methodology-version"),
    snowflake_connection: str = typer.Option("ATLAS_DEV_READ", "--snowflake-connection"),
    candidate: bool = typer.Option(
        False,
        "--candidate",
        help=(
            "Read one non-public candidate through a protected connection; "
            "never exposes it to the API."
        ),
    ),
    candidate_database: str = typer.Option("", "--candidate-database"),
    candidate_warehouse: str = typer.Option("", "--candidate-warehouse"),
    alpha_bundle: Path = typer.Option(..., "--alpha-bundle", exists=True, dir_okay=False),  # noqa: B008
    output: Path = typer.Option(..., "--output"),  # noqa: B008
) -> None:
    """Create a metadata-only full-county Alpha parity report using a read-only connection."""
    if candidate and (not candidate_database or not candidate_warehouse):
        raise typer.BadParameter(
            "Candidate parity requires --candidate-database and --candidate-warehouse"
        )
    report = build_report(
        alpha_bundle,
        fetch_current_semantic_rows(
            snowflake_connection,
            release_id,
            candidate=candidate,
            database=candidate_database or None,
            warehouse=candidate_warehouse or None,
        ),
        release_id=release_id,
        bundle_sha256=bundle_sha256,
        methodology_version=methodology_version,
        source_metadata=fetch_current_source_metadata(
            snowflake_connection,
            release_id if candidate else None,
            database=candidate_database or None,
            warehouse=candidate_warehouse or None,
        ),
        release_metadata=fetch_current_release_metadata(
            snowflake_connection,
            release_id if candidate else None,
            database=candidate_database or None,
            warehouse=candidate_warehouse or None,
        ),
    )
    write_report(output, report)
    typer.echo(json.dumps({"output": str(output), "cutover_eligible": report["cutover_eligible"]}))


@pipeline_app.command("preflight")
def preflight() -> None:
    """Verify DEV configuration and bounded external connectivity safely."""
    typer.echo(json.dumps(run_preflight()))


@pipeline_app.command("discover")
def discover(
    max_requests: int | None = typer.Option(None, "--max-requests", min=1),
) -> None:
    """Persist catalog metadata only; it never ingests a source resource."""
    result = run_discovery(maximum_requests=max_requests)
    if result["status"] == "COMPLETED":
        result["candidate_registration"] = register_completed_discovery(
            str(result["config_sha256"])
        )
    typer.echo(json.dumps(result))


@pipeline_app.command("pubmed-discover")
def pubmed_discover(
    family: str = typer.Option(..., "--family"),
    max_records: int = typer.Option(
        MAX_RECORDS_PER_RUN, "--max-records", min=1, max=MAX_RECORDS_PER_RUN
    ),
    batch_size: int = typer.Option(MAX_BATCH_SIZE, "--batch-size", min=1, max=MAX_BATCH_SIZE),
) -> None:
    """Capture bounded PubMed citation metadata; it cannot approve or fetch full text."""
    typer.echo(
        json.dumps(discover_pubmed(family, maximum_records=max_records, batch_size=batch_size))
    )


@pipeline_app.command("pmc-extract")
def pmc_extract(
    estimated_cost_usd: float = typer.Option(..., "--estimated-cost-usd", min=0.01, max=20.0),
    confirm: bool = typer.Option(False, "--confirm"),
) -> None:
    """Extract at most one steward-approved PMC Open Access paper in DEV."""
    if not confirm:
        raise typer.BadParameter("Pass --confirm after a steward approves one paper")
    typer.echo(
        json.dumps(
            run_pmc_extraction(estimated_cost_usd=estimated_cost_usd, settings=PipelineSettings())
        )
    )


@pipeline_app.command("build-retrieval-corpus")
def build_retrieval_corpus_command(
    confirm: bool = typer.Option(False, "--confirm"),
    pmid: str | None = typer.Option(None, "--pmid"),
) -> None:
    """Rebuild the DEV retrieval corpus from approved PMC artifacts and receipts."""
    if not confirm:
        raise typer.BadParameter("Pass --confirm to rebuild the DEV retrieval corpus")
    typer.echo(json.dumps(build_retrieval_corpus(pmid=pmid, settings=PipelineSettings())))


@pipeline_app.command("register-discovery")
def register_discovery(
    config_sha256: str = typer.Option(..., "--config-sha256"),
    max_artifacts: int = typer.Option(100, "--max-artifacts", min=1, max=100),
    max_datasets: int = typer.Option(10_000, "--max-datasets", min=1, max=10_000),
) -> None:
    """Register one bounded completed-discovery dataset slice; never acquire source data."""
    typer.echo(json.dumps(register_completed_discovery(config_sha256, max_artifacts, max_datasets)))


@pipeline_app.command("register-latest-discovery")
def register_latest_discovery(
    max_artifacts: int = typer.Option(100, "--max-artifacts", min=1, max=100),
    max_datasets: int = typer.Option(10_000, "--max-datasets", min=1, max=10_000),
) -> None:
    """Register a bounded dataset slice from the newest completed discovery chain only."""
    try:
        result = register_latest_completed_discovery(max_artifacts, max_datasets)
    except Exception as error:
        # App Platform can omit traceback output for failed post-deploy jobs.
        # Emit only redacted, correlation-safe diagnostics before retaining the
        # non-zero status for the scheduler.
        emitted = getattr(error, "catalog_registration_diagnostics", None)
        diagnostics = (
            {"status": "FAILED", **emitted}
            if isinstance(emitted, dict)
            else {
                "status": "FAILED",
                "operation": "catalog_registration",
                **_safe_failure_diagnostics(error),
            }
        )
        if not getattr(error, "catalog_registration_terminal_emitted", False):
            logger.error("catalog_registration.failed", extra={"context": diagnostics})
        typer.echo(json.dumps(diagnostics))
        raise
    typer.echo(json.dumps(result))


@pipeline_app.command("migration-plan")
def migration_plan_command(
    database: str = typer.Option(..., "--database"),
) -> None:
    """Show checksummed migration order for the DEV or PROD governed database."""
    typer.echo(json.dumps(migration_plan(database)))


@pipeline_app.command("apply-migrations")
def apply_migrations_command(
    database: str = typer.Option(..., "--database"),
    commit: str | None = typer.Option(None, "--commit"),
    confirm: bool = typer.Option(False, "--confirm"),
) -> None:
    """Apply checksum-validated migrations only after an explicit confirmation."""
    if not confirm:
        raise typer.BadParameter("Pass --confirm to apply migrations")
    typer.echo(json.dumps({"applied": apply_migrations(_settings(), database, commit)}))


@pipeline_app.command("reconcile-legacy-dev-migrations")
def reconcile_legacy_dev_migrations_command(
    database: str = typer.Option(..., "--database"),
    commit: str | None = typer.Option(None, "--commit"),
    confirm: bool = typer.Option(False, "--confirm"),
) -> None:
    """Append the owner-approved DEV-only legacy migration reconciliation evidence."""
    if not confirm:
        raise typer.BadParameter("Pass --confirm to reconcile legacy DEV migrations")
    typer.echo(
        json.dumps({"reconciled": reconcile_legacy_dev_migrations(_settings(), database, commit)})
    )


@pipeline_app.command("reconcile-legacy-prod-migrations")
def reconcile_legacy_prod_migrations_command(
    database: str = typer.Option(..., "--database"),
    commit: str | None = typer.Option(None, "--commit"),
    confirm: bool = typer.Option(False, "--confirm"),
) -> None:
    """Append the separately approved PROD legacy-ledger reconciliation evidence."""
    if not confirm:
        raise typer.BadParameter("Pass --confirm to reconcile legacy PROD migrations")
    typer.echo(
        json.dumps({"reconciled": reconcile_legacy_prod_migrations(_settings(), database, commit)})
    )


@pipeline_app.command("deploy-approval-console")
def deploy_approval_console_command(
    database: str = typer.Option(..., "--database"),
    confirm: bool = typer.Option(False, "--confirm"),
) -> None:
    """Deploy the internal owner-rights Streamlit app from reviewed source files."""
    if not confirm:
        raise typer.BadParameter("Pass --confirm to deploy the approval console")
    typer.echo(json.dumps({"streamlit": deploy_approval_console(_settings(), database)}))


@pipeline_app.command("deploy-data-explorer")
def deploy_data_explorer_command(
    database: str = typer.Option(..., "--database"),
    confirm: bool = typer.Option(False, "--confirm"),
) -> None:
    """Deploy the internal read-only governed data explorer from reviewed source files."""
    if not confirm:
        raise typer.BadParameter("Pass --confirm to deploy the data explorer")
    typer.echo(json.dumps({"streamlit": deploy_data_explorer(_settings(), database)}))


@pipeline_app.command("cdc-sample")
def cdc_sample(sample_limit: int = typer.Option(25, "--sample-limit", min=1, max=100)) -> None:
    """Collect CDC x5j9-wybp metadata and an ordered sample; never full-ingest data."""
    typer.echo(json.dumps(collect_cdc_evidence(sample_limit), default=str))


@pipeline_app.command("cdc-historical-sample")
def cdc_historical_sample(
    sample_limit: int = typer.Option(25, "--sample-limit", min=1, max=100),
) -> None:
    """Capture bounded qtbi-xd4i evidence; never acquire the full dataset."""
    typer.echo(json.dumps(collect_cdc_evidence(sample_limit, dataset_id="qtbi-xd4i"), default=str))


@pipeline_app.command("cdc-tick-surveillance-sample")
def cdc_tick_surveillance_sample(
    sample_limit: int = typer.Option(25, "--sample-limit", min=1, max=100),
    evidence_bundle_dir: str = typer.Option(..., "--evidence-bundle-dir"),
) -> None:
    """Capture bounded CDC Ixodes workbook evidence in DEV; never load RAW data."""
    typer.echo(
        json.dumps(
            collect_tick_surveillance_evidence(
                sample_limit, evidence_bundle_dir=Path(evidence_bundle_dir)
            ),
            default=str,
        )
    )


@pipeline_app.command("cdc-pathogen-surveillance-sample")
def cdc_pathogen_surveillance_sample(
    sample_limit: int = typer.Option(25, "--sample-limit", min=1, max=100),
    evidence_bundle_dir: str = typer.Option(..., "--evidence-bundle-dir"),
) -> None:
    """Capture restricted CDC pathogen evidence in DEV; never load RAW data."""
    typer.echo(
        json.dumps(
            collect_pathogen_surveillance_evidence(
                sample_limit, evidence_bundle_dir=Path(evidence_bundle_dir)
            ),
            default=str,
        )
    )


@pipeline_app.command("cdc-pathogen-restricted-dev-ingest")
def cdc_pathogen_restricted_dev_ingest(
    evidence_run_id: str = typer.Option(..., "--evidence-run-id"),
    evidence_bundle_dir: str = typer.Option(..., "--evidence-bundle-dir"),
) -> None:
    """Derive restricted CDC pathogen county status in DEV; never print source rows."""
    typer.echo(
        json.dumps(
            ingest_restricted_pathogen_dev(
                evidence_bundle_dir=Path(evidence_bundle_dir), evidence_run_id=evidence_run_id
            ),
            default=str,
            sort_keys=True,
        )
    )


@pipeline_app.command("cdc-pathogen-restricted-dev-capture-and-ingest")
def cdc_pathogen_restricted_dev_capture_and_ingest(
    sample_limit: int = typer.Option(25, "--sample-limit", min=1, max=100),
    evidence_bundle_dir: str = typer.Option(..., "--evidence-bundle-dir"),
) -> None:
    """Run private evidence then restricted DEV derivation; never print source rows."""
    typer.echo(
        json.dumps(
            capture_and_ingest_restricted_pathogen_dev(
                sample_limit=sample_limit, evidence_bundle_dir=Path(evidence_bundle_dir)
            ),
            default=str,
            sort_keys=True,
        )
    )


@pipeline_app.command("cdc-restricted-prod-evidence")
def cdc_restricted_prod_evidence(
    source_kind: str = typer.Option(..., "--source-kind"),
    sample_limit: int = typer.Option(25, "--sample-limit", min=1, max=100),
    evidence_bundle_dir: str = typer.Option(..., "--evidence-bundle-dir"),
) -> None:
    """Capture a bounded candidate in the protected production operator envelope."""
    if source_kind == "tick":
        result = collect_tick_surveillance_evidence(
            sample_limit, evidence_bundle_dir=Path(evidence_bundle_dir)
        )
    elif source_kind == "pathogen":
        result = collect_pathogen_surveillance_evidence(
            sample_limit, evidence_bundle_dir=Path(evidence_bundle_dir)
        )
    else:
        raise typer.BadParameter("source-kind must be tick or pathogen")
    typer.echo(json.dumps(result, default=str, sort_keys=True))


@pipeline_app.command("cdc-pathogen-restricted-prod-ingest")
def cdc_pathogen_restricted_prod_ingest(
    evidence_run_id: str = typer.Option(..., "--evidence-run-id"),
    evidence_bundle_dir: str = typer.Option(..., "--evidence-bundle-dir"),
) -> None:
    """Derive restricted pathogen status in the protected production envelope."""
    typer.echo(
        json.dumps(
            ingest_restricted_pathogen(
                evidence_bundle_dir=Path(evidence_bundle_dir), evidence_run_id=evidence_run_id
            ),
            default=str,
            sort_keys=True,
        )
    )


@pipeline_app.command("cdc-tick-restricted-prod-ingest")
def cdc_tick_restricted_prod_ingest(
    evidence_run_id: str = typer.Option(..., "--evidence-run-id"),
    evidence_bundle_dir: str = typer.Option(..., "--evidence-bundle-dir"),
) -> None:
    """Derive restricted tick status in the protected production envelope."""
    typer.echo(
        json.dumps(
            ingest_restricted_tick(
                evidence_bundle_dir=Path(evidence_bundle_dir), evidence_run_id=evidence_run_id
            ),
            default=str,
            sort_keys=True,
        )
    )


@pipeline_app.command("ingest-approved-cdc-historical")
def ingest_historical_command(source_version_id: str = typer.Option(...)) -> None:
    """Explicit DEV-only approved 2008-2021 acquisition, validation and publication."""
    from .cdc_historical_ingestion import refresh_historical

    typer.echo(json.dumps(refresh_historical(source_version_id), default=str))


@pipeline_app.command("rollback-cdc-historical")
def rollback_historical_command(
    source_version_id: str = typer.Option(...),
    ingestion_run_id: str = typer.Option(...),
    expected_revision: int = typer.Option(..., min=1),
) -> None:
    """DEV-only audited rollback to a retained historical snapshot; no acquisition."""
    from .cdc_historical_ingestion import rollback_historical

    typer.echo(
        json.dumps(
            rollback_historical(source_version_id, ingestion_run_id, expected_revision), default=str
        )
    )


@pipeline_app.command("recover-approved-cdc-historical")
def recover_historical_command(
    source_version_id: str = typer.Option(..., "--source-version-id"),
    ingestion_run_id: str = typer.Option(..., "--ingestion-run-id"),
) -> None:
    """Validate and publish retained historical RAW data without acquisition."""
    from .cdc_historical_ingestion import recover_historical

    typer.echo(json.dumps(recover_historical(source_version_id, ingestion_run_id), default=str))


@pipeline_app.command("ingest-approved-cdc")
def ingest_approved_cdc_command(
    check_id: str = typer.Option(..., "--check-id"),
) -> None:
    """Deprecated x5j9 loader; use the generic SourceDefinition workflow."""
    del check_id
    raise typer.BadParameter(
        "Legacy x5j9 loading is unsupported; use run-ingestion.yml with "
        "config/sources/cdc_x5j9_wybp.yml and tier B."
    )


@pipeline_app.command("promote-approved-cdc")
def promote_approved_cdc_command(
    check_id: str = typer.Option(..., "--check-id"),
) -> None:
    """Deprecated x5j9 promoter; use the protected promotion/publication workflow."""
    del check_id
    raise typer.BadParameter(
        "Legacy x5j9 promotion is unsupported; use the generic DEV run and protected "
        "PROD promotion/publication workflow."
    )


@pipeline_app.command("check-cdc-metadata")
def check_cdc_metadata_command() -> None:
    """Check CDC publisher metadata only; never acquire source rows."""
    typer.echo(json.dumps(check_cdc_metadata()))


@pipeline_app.command("bootstrap-cdc-publication")
def bootstrap_cdc_publication_command(
    source_version_id: str = typer.Option(...),
    ingestion_run_id: str = typer.Option(...),
) -> None:
    """Validate the existing snapshot and activate pointer-based publication."""
    typer.echo(json.dumps(bootstrap_publication(source_version_id, ingestion_run_id)))


@pipeline_app.command("check-cdc-overdue")
def check_cdc_overdue_command() -> None:
    """Record a redacted incident when a monthly metadata check is overdue."""
    typer.echo(json.dumps(check_cdc_overdue()))


@pipeline_app.command("verify-cdc-ready")
def verify_cdc_ready_command(source_version_id: str = typer.Option(...)) -> None:
    """Check publication and metadata evidence before routine scheduling."""
    typer.echo(json.dumps(verify_cdc_ready(source_version_id)))


@pipeline_app.command("validate-cdc-quality")
def validate_cdc_quality_command(source_version_id: str = typer.Option(...)) -> None:
    """Validate retained RAW/CONFORMED rows and append aggregate quality evidence."""
    typer.echo(json.dumps(record_cdc_quality(source_version_id)))


@pipeline_app.command("rollback-cdc-publication")
def rollback_cdc_publication_command(
    source_version_id: str = typer.Option(...),
    ingestion_run_id: str = typer.Option(...),
    expected_revision: int = typer.Option(..., min=1),
) -> None:
    """Restore a retained validated snapshot; preserve acquisition evidence."""
    typer.echo(
        json.dumps(
            rollback_publication(
                source_version_id, ingestion_run_id, expected_revision=expected_revision
            )
        )
    )


@pipeline_app.command("run-production-schedule")
def run_production_schedule_command() -> None:
    """Run the production scheduled approved-source ingestion and dbt path."""
    typer.echo(json.dumps(run_production_schedule(), default=str))


@pipeline_app.command("run-production-cdc-dbt-recovery")
def run_production_cdc_dbt_recovery_command(
    source_version_id: str = typer.Option(..., "--source-version-id"),
) -> None:
    """Recover the CDC dbt path for verified PROD RAW data without re-ingestion."""
    typer.echo(json.dumps(run_production_cdc_dbt_recovery(source_version_id), default=str))


@pipeline_app.command("run-cdc-dbt-recovery")
def run_cdc_dbt_recovery_command(
    source_version_id: str = typer.Option(..., "--source-version-id"),
) -> None:
    """Run dbt for an approved source version with retained governed RAW data."""
    typer.echo(json.dumps(run_cdc_dbt_recovery(source_version_id), default=str))


@source_app.command("init")
def source_init(
    resource_key: str = typer.Option(..., "--resource-key"),
    adapter: str = typer.Option("socrata", "--adapter"),
    output_dir: str = typer.Option(_DEFAULT_SOURCE_DIR, "--output-dir"),
) -> None:
    """Scaffold the smallest useful SourceDefinition plus fixture/test skeleton."""
    kind = AdapterKind(adapter)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    definition_path = output / f"{resource_key}.yml"
    if definition_path.exists():
        raise typer.BadParameter(f"Definition already exists: {definition_path}")
    definition_path.write_text(
        starter_definition_yaml(resource_key=resource_key, adapter_kind=kind),
        encoding="utf-8",
    )
    fixture_root = Path("tests/fixtures/sources") / resource_key
    fixture_root.mkdir(parents=True, exist_ok=True)
    (fixture_root / "sample.json").write_text("[]\n", encoding="utf-8")
    (fixture_root / "README.md").write_text(
        f"# Fixtures for `{resource_key}`\n\nReplace sample.json before Tier A runs.\n",
        encoding="utf-8",
    )
    typer.echo(
        json.dumps(
            {
                "definition": str(definition_path),
                "fixture_dir": str(fixture_root),
                "next": f"atlas-data source validate --definition {definition_path}",
            }
        )
    )


@source_app.command("validate")
def source_validate(
    definition: str = typer.Option(..., "--definition"),
) -> None:
    """Validate a SourceDefinition before network or warehouse side effects."""
    loaded = load_source_definition(Path(definition))
    result = _orchestrator().validate(loaded)
    typer.echo(json.dumps(result.to_dict(), indent=2))
    if not result.ok:
        raise typer.Exit(code=1)


@source_app.command("inspect")
def source_inspect(
    definition: str = typer.Option(..., "--definition"),
) -> None:
    """Show normalized SourceDefinition fields used by the orchestrator."""
    loaded = load_source_definition(Path(definition))
    typer.echo(
        json.dumps(
            {
                "resource_key": loaded.resource_key,
                "source_id": loaded.source_id,
                "dataset_id": loaded.dataset_id,
                "definition_version": loaded.definition_version,
                "adapter_kind": loaded.adapter_kind.value,
                "endpoint_template": loaded.endpoint_template,
                "stages": [stage.value for stage in loaded.stages],
                "destination": loaded.destination,
                "quality_rules": [
                    {"rule_id": rule.rule_id, "severity": rule.severity}
                    for rule in loaded.quality_rules
                ],
            },
            indent=2,
        )
    )


@source_app.command("run")
def source_run(
    definition: str = typer.Option(..., "--definition"),
    tier: str = typer.Option("A", "--tier", help="A=local fixture, B=DEV, C=PROD protected"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    fixture_dir: str | None = typer.Option(None, "--fixture-dir"),
    fail_after_stage: str | None = typer.Option(None, "--fail-after-stage"),
) -> None:
    """Run or dry-run ingestion through the shared orchestrator."""
    loaded = load_source_definition(Path(definition))
    selected_tier = Tier(tier.upper())
    resolved_fixture = Path(fixture_dir) if fixture_dir else None
    if selected_tier is Tier.A and resolved_fixture is None:
        candidate = Path("tests/fixtures/sources") / loaded.resource_key
        if candidate.exists():
            resolved_fixture = candidate
    state = _orchestrator(resolved_fixture, tier=selected_tier, dry_run=dry_run).run(
        loaded,
        tier=selected_tier,
        dry_run=dry_run,
        fail_after_stage=fail_after_stage,
    )
    typer.echo(json.dumps(state.to_dict(), indent=2))
    if state.status.value != "SUCCEEDED":
        raise typer.Exit(code=1)


@source_app.command("capture-routine-public-evidence")
def source_capture_routine_public_evidence(
    definition: str = typer.Option(..., "--definition"),
) -> None:
    """Create a PROD review candidate; never creates a source version or loads rows."""
    from .source_evidence import collect_routine_public_source_evidence_from_path

    typer.echo(
        json.dumps(
            collect_routine_public_source_evidence_from_path(definition),
            indent=2,
        )
    )


@source_app.command("dev-smoke")
def source_dev_smoke(
    definition: str = typer.Option(_DEFAULT_X5J9_DEFINITION, "--definition"),
) -> None:
    """Bounded one-source DEV smoke using fixtures (no App Platform topology edits)."""
    loaded = load_source_definition(Path(definition))
    fixture = Path("tests/fixtures/sources") / loaded.resource_key
    state = _orchestrator(fixture if fixture.exists() else None).run(
        loaded,
        tier=Tier.A,
        dry_run=not fixture.exists(),
    )
    typer.echo(
        json.dumps(
            {
                "mode": "bounded_dev_smoke",
                "topology_mutated": False,
                "run": state.to_dict(),
            },
            indent=2,
        )
    )
    if state.status.value != "SUCCEEDED":
        raise typer.Exit(code=1)


@runs_app.command("list")
def runs_list() -> None:
    """List durable ingestion runs from the active runtime store."""
    store = _run_store()
    typer.echo(
        json.dumps(
            [
                {
                    "ingestion_run_id": run.ingestion_run_id,
                    "resource_key": run.resource_key,
                    "status": run.status.value,
                    "next_action": run.next_action,
                }
                for run in store.list_runs()
            ],
            indent=2,
        )
    )


@runs_app.command("show")
def runs_show(run_id: str = typer.Option(..., "--run-id")) -> None:
    """Show one run including stage checkpoints."""
    typer.echo(json.dumps(_orchestrator_for_run(run_id).inspect(run_id).to_dict(), indent=2))


@runs_app.command("explain")
def runs_explain(run_id: str = typer.Option(..., "--run-id")) -> None:
    """Explain failing stage, category, and next action."""
    typer.echo(json.dumps(explain_run(_orchestrator_for_run(run_id).inspect(run_id)), indent=2))


@runs_app.command("resume")
def runs_resume(
    run_id: str = typer.Option(..., "--run-id"),
    definition: str = typer.Option(..., "--definition"),
    fixture_dir: str | None = typer.Option(None, "--fixture-dir"),
) -> None:
    """Resume a failed run at the failed stage without replaying completed work."""
    loaded = load_source_definition(Path(definition))
    resolved_fixture = Path(fixture_dir) if fixture_dir else None
    if resolved_fixture is None:
        candidate = Path("tests/fixtures/sources") / loaded.resource_key
        if candidate.exists():
            resolved_fixture = candidate
    state = _orchestrator_for_run(run_id, resolved_fixture).resume(run_id, definition=loaded)
    typer.echo(json.dumps(state.to_dict(), indent=2))
    if state.status.value != "SUCCEEDED":
        raise typer.Exit(code=1)


@runs_app.command("retry")
def runs_retry(
    run_id: str = typer.Option(..., "--run-id"),
    definition: str = typer.Option(..., "--definition"),
    fixture_dir: str | None = typer.Option(None, "--fixture-dir"),
) -> None:
    """Alias for resume (shared orchestration entry point)."""
    runs_resume(run_id=run_id, definition=definition, fixture_dir=fixture_dir)
