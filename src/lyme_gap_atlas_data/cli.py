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

from .catalog_registration import register_completed_discovery, register_latest_completed_discovery
from .cdc import build_approved_cdc_models, collect_cdc_evidence, ingest_approved_cdc
from .database import load as load_release
from .database import provision as provision_database
from .database import status as database_status
from .database import validate_loaded
from .discovery import initial_requests, load_search_configuration
from .migrations import apply_migrations, migration_plan, reconcile_legacy_dev_migrations
from .orchestration import run_discovery, run_production_schedule
from .pmc_extraction_worker import run_pmc_extraction
from .preflight import run_preflight
from .pubmed_discovery import MAX_BATCH_SIZE, MAX_RECORDS_PER_RUN, discover_pubmed
from .settings import PipelineSettings
from .streamlit_deploy import deploy_approval_console

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
        span = trace.get_tracer(SERVICE_NAME).start_span("atlas-data.cli")
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
            span.end()
            _flush_and_shutdown_tracing()


app = ObservedTyper(no_args_is_help=True)
pipeline_app = typer.Typer(no_args_is_help=True)
app.add_typer(pipeline_app, name="pipeline")
logger = logging.getLogger(__name__)


@app.callback()
def configure_runtime_observability() -> None:
    """Initialize redacted JSON logs for every CLI command, including jobs."""
    configure_logging()
    configure_tracing(SERVICE_NAME)


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
        diagnostics = {
            "status": "FAILED",
            "operation": "catalog_registration",
            **_safe_failure_diagnostics(error),
        }
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


@pipeline_app.command("deploy-approval-console")
def deploy_approval_console_command(
    database: str = typer.Option(..., "--database"),
    confirm: bool = typer.Option(False, "--confirm"),
) -> None:
    """Deploy the internal owner-rights Streamlit app from reviewed source files."""
    if not confirm:
        raise typer.BadParameter("Pass --confirm to deploy the approval console")
    typer.echo(json.dumps({"streamlit": deploy_approval_console(_settings(), database)}))


@pipeline_app.command("cdc-sample")
def cdc_sample(sample_limit: int = typer.Option(25, "--sample-limit", min=1, max=100)) -> None:
    """Collect CDC x5j9-wybp metadata and an ordered sample; never full-ingest data."""
    typer.echo(json.dumps(collect_cdc_evidence(sample_limit), default=str))


@pipeline_app.command("ingest-approved-cdc")
def ingest_approved_cdc_command(
    page_size: int = typer.Option(5000, "--page-size", min=1, max=10000),
) -> None:
    """Load CDC x5j9-wybp only when a steward-approved source version is active."""
    typer.echo(json.dumps(ingest_approved_cdc(page_size), default=str))


@pipeline_app.command("promote-approved-cdc")
def promote_approved_cdc_command(
    page_size: int = typer.Option(5000, "--page-size", min=1, max=10000),
) -> None:
    """Run explicit CDC acquisition followed by its dbt promotion path."""
    ingestion = ingest_approved_cdc(page_size)
    typer.echo(json.dumps(build_approved_cdc_models(str(ingestion["source_version_id"]))))


@pipeline_app.command("run-production-schedule")
def run_production_schedule_command() -> None:
    """Run the production scheduled approved-source ingestion and dbt path."""
    typer.echo(json.dumps(run_production_schedule(), default=str))
