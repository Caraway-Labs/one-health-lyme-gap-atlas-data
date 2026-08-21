"""Checksum-enforced, environment-neutral Snowflake migration execution."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect
from snowflake.connector.errors import ProgrammingError

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
DATABASE_PATTERN = re.compile(r"^ONE_HEALTH_LYME_GAP_ATLAS_(DEV|PROD)$")


@dataclass(frozen=True)
class Migration:
    version: str
    filename: str
    source: str
    sha256: str


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Load ordered, versioned migrations with source-based checksums."""
    migrations: list[Migration] = []
    for path in sorted(directory.glob("V*__*.sql")):
        source = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=path.stem.split("__", maxsplit=1)[0],
                filename=path.name,
                source=source,
                sha256=hashlib.sha256(source.encode()).hexdigest(),
            )
        )
    if not migrations:
        raise ValueError("No migrations found")
    return migrations


def render_migration(migration: Migration, database: str) -> str:
    """Render one validated database identifier; no arbitrary SQL is accepted."""
    if not DATABASE_PATTERN.fullmatch(database):
        raise ValueError("Migrations may target only ONE_HEALTH_LYME_GAP_ATLAS_DEV or _PROD")
    rendered = migration.source.replace("{{ DATABASE }}", database)
    if "ONE_HEALTH_LYME_GAP_ATLAS;" in rendered:
        raise ValueError("The Alpha POC database is not a migration target")
    return rendered


def migration_plan(database: str) -> list[dict[str, str]]:
    """Return the non-secret, source-checksummed plan for an allowed target."""
    return [
        {"version": item.version, "filename": item.filename, "sha256": item.sha256}
        for item in load_migrations()
        if render_migration(item, database)
    ]


def apply_migrations(
    settings: SnowflakeSettings, database: str, commit: str | None = None
) -> list[str]:
    """Apply each missing migration once and reject any checksum mismatch."""
    if not DATABASE_PATTERN.fullmatch(database):
        raise ValueError("Migrations may target only ONE_HEALTH_LYME_GAP_ATLAS_DEV or _PROD")
    plan = load_migrations()
    with connect(settings, include_database=False) as connection:
        with connection.cursor() as cursor:
            try:
                cursor.execute(f"USE DATABASE {database}")
                cursor.execute("SELECT version, sha256 FROM GOVERNANCE.SCHEMA_MIGRATIONS")
                applied = dict(cursor.fetchall())
            except ProgrammingError:
                applied = {}
        executed: list[str] = []
        for migration in plan:
            prior_checksum = applied.get(migration.version)
            if prior_checksum == migration.sha256:
                continue
            if prior_checksum is not None:
                raise ValueError(f"Checksum mismatch for already-applied {migration.version}")
            connection.execute_string(render_migration(migration, database))
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO GOVERNANCE.SCHEMA_MIGRATIONS
                    (version, filename, sha256, deployment_commit, applied_by)
                    VALUES (%s, %s, %s, %s, CURRENT_USER())""",
                    (migration.version, migration.filename, migration.sha256, commit),
                )
            connection.commit()
            executed.append(migration.version)
    return executed
