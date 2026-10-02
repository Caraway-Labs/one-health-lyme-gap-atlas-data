"""Private staging and validated reporting for bounded metadata evidence."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from .metadata_snapshots import (
    ROOT,
    collect_dev,
    load_scope,
    render_report,
    report,
    snapshot,
    validate_snapshot,
)

app = typer.Typer(no_args_is_help=True)
PRIVATE = ROOT / ".atlas-metadata-private"


@app.command("snapshot")
def export_snapshot(code_commit: str = typer.Option(...)) -> None:
    """Inspect existing DEV audit authority and stage sanitized evidence privately."""
    try:
        if Path.cwd().resolve() != ROOT:
            raise ValueError
        scope = load_scope()
        # Validate caller-supplied provenance before opening the audit session.
        if len(code_commit) != 40 or any(x not in "0123456789abcdef" for x in code_commit):
            raise ValueError
        head = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
        if head != code_commit or dirty.strip():
            raise ValueError
        facts = collect_dev(scope)
        value = snapshot(
            facts,
            environment="dev",
            code_commit=code_commit,
            generated_at=datetime.now(UTC),
            scope=scope,
        )
        validate_snapshot(value)
        result = report(value, now=datetime.now(UTC))
        PRIVATE.mkdir(exist_ok=True)
        for filename, payload in (("snapshot.json", value), ("drift.json", result)):
            (PRIVATE / filename).write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        (PRIVATE / "drift.txt").write_text(render_report(result), encoding="utf-8")
    except Exception:
        typer.echo("Metadata export blocked; no authority fallback or publication.", err=True)
        raise typer.Exit(1) from None
    typer.echo(
        "Sanitized DEV evidence staged in ignored private directory; review before publication."
    )


@app.command("report")
def metadata_report(
    snapshot_path: Annotated[Path, typer.Option("--snapshot")], baseline: Path | None = None
) -> None:
    """Validate public fields and report freshness/drift without any live connection."""
    try:
        value = json.loads(snapshot_path.read_text(encoding="utf-8"))
        prior = json.loads(baseline.read_text(encoding="utf-8")) if baseline else None
        result = report(value, now=datetime.now(UTC), baseline=prior)
    except Exception:
        typer.echo("UNKNOWN: metadata report rejected; invalid or incomparable evidence.", err=True)
        raise typer.Exit(1) from None
    typer.echo(render_report(result), nl=False)
