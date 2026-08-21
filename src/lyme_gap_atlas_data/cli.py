"""Operator CLI for the MVP Snowflake release."""

import json
from pathlib import Path

import typer
from lyme_gap_atlas_shared.observability import configure_logging, configure_tracing
from lyme_gap_atlas_shared.settings import SnowflakeSettings

from .cdc import collect_cdc_evidence
from .database import load as load_release
from .database import provision as provision_database
from .database import status as database_status
from .database import validate_loaded
from .discovery import initial_requests, load_search_configuration
from .migrations import apply_migrations, migration_plan
from .orchestration import run_discovery
from .preflight import run_preflight
from .settings import PipelineSettings
from .streamlit_deploy import deploy_approval_console

app = typer.Typer(no_args_is_help=True)
pipeline_app = typer.Typer(no_args_is_help=True)
app.add_typer(pipeline_app, name="pipeline")


def _settings() -> SnowflakeSettings:
    configure_logging()
    configure_tracing("one-health-lyme-gap-atlas-data")
    return SnowflakeSettings()


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
    typer.echo(json.dumps(run_discovery(maximum_requests=max_requests)))


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
