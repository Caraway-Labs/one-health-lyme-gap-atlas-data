"""Operator CLI for the MVP Snowflake release."""

import json

import typer
from lyme_gap_atlas_shared.observability import configure_logging, configure_tracing
from lyme_gap_atlas_shared.settings import SnowflakeSettings

from .database import load as load_release
from .database import provision as provision_database
from .database import status as database_status
from .database import validate_loaded

app = typer.Typer(no_args_is_help=True)


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
