"""Checksum-enforced, environment-neutral Snowflake migration execution."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect
from snowflake.connector.cursor import SnowflakeCursor
from snowflake.connector.errors import ProgrammingError

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
DATABASE_PATTERN = re.compile(r"^ONE_HEALTH_LYME_GAP_ATLAS_(DEV|PROD)$")
DEV_DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
PROD_DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_PROD"
DEV_ONLY_MIGRATION_VERSIONS = {
    "V034",
    "V037",
    "V038",
    "V044",
    "V045",
    "V046",
    "V047",
    "V048",
    "V053",
    "V054",
    "V055",
    "V056",
    "V057",
    "V058",
}
PROD_ONLY_MIGRATION_VERSIONS = {"V049", "V050", "V051", "V052"}
# V041 creates bounded GOVERNANCE views over RAW and CONFORMED. Its owner
# needs those exact reads, but the normal migration role and Streamlit owner
# must not inherit them.
VIEW_OWNER_MIGRATION_VERSIONS = {"V041", "V047", "V052"}

# These are the exact legacy checksums observed in the DEV ledger on 2026-08-30.
# They are an explicit, DEV-only recovery boundary—not a general checksum bypass.
LEGACY_DEV_MIGRATION_CHECKSUMS = {
    "V028": "a0744172dd021eed2c538a44152c69026a8e3aa7a64ae18a093233f0552d8b85",
    "V029": "86ab0b8f9553ba7dbcc4d0ada34cecf7172a84f8bf1ab23168472ba853a227f5",
    "V033": "ff90ba209e6a525690bbc53b92e015942d8d5590debd3dbd2bf495b7a00a150f",
}
RECONCILIATION_REASON = "Ticket 03 owner authorization, 2026-08-30"
# These exact PROD rows were observed during the protected qtbi-xd4i rollout.
# V022 is the previously applied PROD variant that reconciled duplicate V020
# rows. V028 is duplicated twice with one identical CRLF-source checksum. Both
# conditions require append-only evidence before later migrations may proceed.
LEGACY_PROD_MIGRATION_CHECKSUMS = {
    "V022": "0459687e88d2a5c23bfb730b832d1569a0cb950fab708fbe34b6f1e8379fe8a2",
    "V028": "a0744172dd021eed2c538a44152c69026a8e3aa7a64ae18a093233f0552d8b85",
}
LEGACY_PROD_MIGRATION_FILENAMES = {
    "V022": "V022__reconcile_duplicate_v020_ledger_entry.sql",
    "V028": "V028__resumable_catalog_discovery_registration.sql",
}
LEGACY_PROD_MIGRATION_ROW_COUNTS = {"V022": 1, "V028": 2}
PROD_RECONCILIATION_REASON = "Protected qtbi-xd4i rollout owner authorization, 2026-09-08"
REQUIRED_REGISTRATION_COLUMNS = {
    "ARTIFACT_ID",
    "CONFIG_SHA256",
    "STATUS",
    "REGISTRATION_RUN_ID",
    "ATTEMPT_COUNT",
    "STARTED_AT",
    "LEASE_EXPIRES_AT",
    "COMPLETED_AT",
    "REDACTED_ERROR",
    "NEXT_DATASET_OFFSET",
}


@dataclass(frozen=True)
class Migration:
    version: str
    filename: str
    source: str
    sha256: str


def is_line_ending_equivalent_checksum(source: str, checksum: str) -> bool:
    """Accept only byte hashes that differ by LF versus CRLF serialization."""
    normalized = source.replace("\r\n", "\n")
    variants = {
        hashlib.sha256(normalized.encode()).hexdigest(),
        hashlib.sha256(normalized.replace("\n", "\r\n").encode()).hexdigest(),
    }
    return checksum in variants


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
    match = DATABASE_PATTERN.fullmatch(database)
    if match is None:
        raise ValueError("Migrations may target only ONE_HEALTH_LYME_GAP_ATLAS_DEV or _PROD")
    environment = match.group(1)
    if migration.version in DEV_ONLY_MIGRATION_VERSIONS and database != DEV_DATABASE:
        raise ValueError("This migration is DEV-only")
    if migration.version in PROD_ONLY_MIGRATION_VERSIONS and database != PROD_DATABASE:
        raise ValueError("Historical CDC PROD migration is PROD-only")
    rendered = migration.source.replace("{{ DATABASE }}", database).replace(
        "{{ ENV }}", environment
    )
    if "ONE_HEALTH_LYME_GAP_ATLAS;" in rendered:
        raise ValueError("The Alpha POC database is not a migration target")
    return rendered


def migration_plan(database: str) -> list[dict[str, str]]:
    """Return the non-secret, source-checksummed plan for an allowed target."""
    return [
        {"version": item.version, "filename": item.filename, "sha256": item.sha256}
        for item in load_migrations()
        if (database == DEV_DATABASE or item.version not in DEV_ONLY_MIGRATION_VERSIONS)
        and (database == PROD_DATABASE or item.version not in PROD_ONLY_MIGRATION_VERSIONS)
        and render_migration(item, database)
    ]


def migration_execution_role(migration: Migration, database: str) -> str | None:
    """Return a narrowly-scoped owner role for a migration that needs one."""
    match = DATABASE_PATTERN.fullmatch(database)
    if match is None:
        raise ValueError("Migrations may target only ONE_HEALTH_LYME_GAP_ATLAS_DEV or _PROD")
    if migration.version in {"V044", "V053"}:
        if database != DEV_DATABASE:
            raise ValueError("DEV source-review view migration is DEV-only")
        return "OH_LYME_DEV_STREAMLIT_OWNER"
    if migration.version in {"V056", "V057"}:
        if database != DEV_DATABASE:
            raise ValueError("DEV PMC budget-owner migration is DEV-only")
        return "OH_LYME_DEV_KG_LLM_BUDGET_OWNER"
    if migration.version == "V049":
        if database != PROD_DATABASE:
            raise ValueError("Historical CDC PROD onboarding migration is PROD-only")
        return "OH_LYME_PROD_GOVERNED_VIEW_OWNER"
    if migration.version == "V050":
        if database != PROD_DATABASE:
            raise ValueError("Historical CDC PROD onboarding migration is PROD-only")
        return "OH_LYME_PROD_STREAMLIT_OWNER"
    if migration.version not in VIEW_OWNER_MIGRATION_VERSIONS:
        return None
    return f"OH_LYME_{match.group(1)}_GOVERNED_VIEW_OWNER"


def _migration_settings(
    settings: SnowflakeSettings, migration: Migration, database: str
) -> SnowflakeSettings:
    """Keep the default deployer role except for explicitly bounded migrations."""
    role = migration_execution_role(migration, database)
    return settings if role is None else settings.model_copy(update={"snowflake_role": role})


def legacy_dev_reconciliation_plan(
    applied: dict[str, str], migrations: list[Migration]
) -> list[Migration]:
    """Return the only owner-authorized DEV legacy checksum reconciliations."""
    source_by_version = {migration.version: migration for migration in migrations}
    if set(LEGACY_DEV_MIGRATION_CHECKSUMS) - set(source_by_version):
        raise ValueError("Legacy reconciliation migration source is missing")

    reconciliations: list[Migration] = []
    for version, legacy_checksum in LEGACY_DEV_MIGRATION_CHECKSUMS.items():
        migration = source_by_version[version]
        if applied.get(version) != legacy_checksum:
            raise ValueError(f"Unexpected DEV ledger checksum for {version}")
        if legacy_checksum == migration.sha256:
            raise ValueError(f"Legacy reconciliation is no longer required for {version}")
        reconciliations.append(migration)
    return reconciliations


def legacy_prod_reconciliation_plan(
    applied_rows: list[tuple[str, str, str]], migrations: list[Migration]
) -> list[Migration]:
    """Validate the exact owner-approved PROD variant and duplicate ledger rows."""
    source_by_version = {migration.version: migration for migration in migrations}
    if set(LEGACY_PROD_MIGRATION_CHECKSUMS) - set(source_by_version):
        raise ValueError("Legacy PROD reconciliation migration source is missing")

    rows_by_version: dict[str, list[tuple[str, str]]] = {}
    for version, filename, checksum in applied_rows:
        rows_by_version.setdefault(version, []).append((filename, checksum))

    reconciliations: list[Migration] = []
    for version, legacy_checksum in LEGACY_PROD_MIGRATION_CHECKSUMS.items():
        rows = rows_by_version.get(version, [])
        expected_row = (LEGACY_PROD_MIGRATION_FILENAMES[version], legacy_checksum)
        if len(rows) != LEGACY_PROD_MIGRATION_ROW_COUNTS[version] or any(
            row != expected_row for row in rows
        ):
            raise ValueError(f"Unexpected PROD ledger shape for {version}")
        migration = source_by_version[version]
        if legacy_checksum == migration.sha256:
            raise ValueError(f"Legacy PROD reconciliation is no longer required for {version}")
        reconciliations.append(migration)
    return reconciliations


def reconcile_legacy_dev_migrations(
    settings: SnowflakeSettings, database: str, commit: str | None = None
) -> list[str]:
    """Append immutable DEV evidence for the owner-approved legacy mismatch set."""
    if database != DEV_DATABASE:
        raise ValueError("Legacy migration reconciliation is permitted only in the DEV database")

    migrations = load_migrations()
    with connect(settings, include_database=False) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"USE DATABASE {database}")
            cursor.execute("SELECT version, sha256 FROM GOVERNANCE.SCHEMA_MIGRATIONS")
            applied = dict(cursor.fetchall())
            reconciliations = legacy_dev_reconciliation_plan(applied, migrations)
            cursor.execute(
                """SELECT UPPER(column_name)
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE table_catalog = CURRENT_DATABASE()
                  AND table_schema = 'GOVERNANCE'
                  AND table_name = 'CATALOG_DISCOVERY_REGISTRATIONS'"""
            )
            columns = {row[0] for row in cursor.fetchall()}
            if not columns >= REQUIRED_REGISTRATION_COLUMNS:
                raise ValueError(
                    "DEV registration ledger does not match the required V028/V029 shape"
                )
            cursor.execute(
                """CREATE TABLE IF NOT EXISTS GOVERNANCE.SCHEMA_MIGRATION_RECONCILIATIONS (
                migration_version VARCHAR PRIMARY KEY,
                legacy_sha256 VARCHAR(64) NOT NULL,
                source_sha256 VARCHAR(64) NOT NULL,
                reconciliation_scope VARCHAR NOT NULL,
                rationale VARCHAR NOT NULL,
                approved_by VARCHAR NOT NULL,
                reconciled_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
                deployment_commit VARCHAR
                )"""
            )

            recorded: list[str] = []
            for migration in reconciliations:
                cursor.execute(
                    """SELECT legacy_sha256, source_sha256, reconciliation_scope
                    FROM GOVERNANCE.SCHEMA_MIGRATION_RECONCILIATIONS
                    WHERE migration_version = %s""",
                    (migration.version,),
                )
                existing = cursor.fetchone()
                expected = (
                    LEGACY_DEV_MIGRATION_CHECKSUMS[migration.version],
                    migration.sha256,
                    "DEV",
                )
                if existing is not None:
                    if tuple(existing) != expected:
                        raise ValueError(
                            f"Existing reconciliation does not match {migration.version}"
                        )
                    continue
                cursor.execute(
                    """INSERT INTO GOVERNANCE.SCHEMA_MIGRATION_RECONCILIATIONS
                    (migration_version, legacy_sha256, source_sha256, reconciliation_scope,
                     rationale, approved_by, deployment_commit)
                    VALUES (%s, %s, %s, 'DEV', %s, CURRENT_USER(), %s)""",
                    (
                        migration.version,
                        LEGACY_DEV_MIGRATION_CHECKSUMS[migration.version],
                        migration.sha256,
                        RECONCILIATION_REASON,
                        commit,
                    ),
                )
                recorded.append(migration.version)
        connection.commit()
    return recorded


def reconcile_legacy_prod_migrations(
    settings: SnowflakeSettings, database: str, commit: str | None = None
) -> list[str]:
    """Append immutable PROD evidence for the exact owner-approved legacy rows."""
    if database != PROD_DATABASE:
        raise ValueError("PROD legacy reconciliation is permitted only in the PROD database")

    migrations = load_migrations()
    with connect(settings, include_database=False) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"USE DATABASE {database}")
            cursor.execute("SELECT version, filename, sha256 FROM GOVERNANCE.SCHEMA_MIGRATIONS")
            applied_rows = list(cursor.fetchall())
            reconciliations = legacy_prod_reconciliation_plan(applied_rows, migrations)
            cursor.execute(
                """CREATE TABLE IF NOT EXISTS GOVERNANCE.SCHEMA_MIGRATION_RECONCILIATIONS (
                migration_version VARCHAR PRIMARY KEY,
                legacy_sha256 VARCHAR(64) NOT NULL,
                source_sha256 VARCHAR(64) NOT NULL,
                reconciliation_scope VARCHAR NOT NULL,
                rationale VARCHAR NOT NULL,
                approved_by VARCHAR NOT NULL,
                reconciled_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
                deployment_commit VARCHAR
                )"""
            )

            recorded: list[str] = []
            for migration in reconciliations:
                cursor.execute(
                    """SELECT legacy_sha256, source_sha256, reconciliation_scope
                    FROM GOVERNANCE.SCHEMA_MIGRATION_RECONCILIATIONS
                    WHERE migration_version = %s""",
                    (migration.version,),
                )
                existing = cursor.fetchone()
                expected = (
                    LEGACY_PROD_MIGRATION_CHECKSUMS[migration.version],
                    migration.sha256,
                    "PROD",
                )
                if existing is not None:
                    if tuple(existing) != expected:
                        raise ValueError(
                            f"Existing PROD reconciliation does not match {migration.version}"
                        )
                    continue
                cursor.execute(
                    """INSERT INTO GOVERNANCE.SCHEMA_MIGRATION_RECONCILIATIONS
                    (migration_version, legacy_sha256, source_sha256, reconciliation_scope,
                     rationale, approved_by, deployment_commit)
                    VALUES (%s, %s, %s, 'PROD', %s, CURRENT_USER(), %s)""",
                    (
                        migration.version,
                        LEGACY_PROD_MIGRATION_CHECKSUMS[migration.version],
                        migration.sha256,
                        PROD_RECONCILIATION_REASON,
                        commit,
                    ),
                )
                recorded.append(migration.version)
        connection.commit()
    return recorded


def _reconciled_legacy_migrations(
    cursor: SnowflakeCursor, database: str
) -> dict[str, tuple[str, str]]:
    """Read immutable reconciliation evidence; absent evidence never relaxes checks."""
    scope = "DEV" if database == DEV_DATABASE else "PROD" if database == PROD_DATABASE else None
    if scope is None:
        return {}
    try:
        cursor.execute(
            """SELECT migration_version, legacy_sha256, source_sha256
            FROM GOVERNANCE.SCHEMA_MIGRATION_RECONCILIATIONS
            WHERE reconciliation_scope = %s""",
            (scope,),
        )
        return {version: (legacy, source) for version, legacy, source in cursor.fetchall()}
    except ProgrammingError:
        return {}


def is_authorized_legacy_reconciliation(
    database: str,
    version: str,
    legacy_checksum: str,
    source_checksum: str,
    recorded: dict[str, tuple[str, str]],
) -> bool:
    """Require a pinned environment exception and immutable matching evidence."""
    expected_checksums = (
        LEGACY_DEV_MIGRATION_CHECKSUMS
        if database == DEV_DATABASE
        else LEGACY_PROD_MIGRATION_CHECKSUMS
        if database == PROD_DATABASE
        else {}
    )
    return expected_checksums.get(version) == legacy_checksum and recorded.get(version) == (
        legacy_checksum,
        source_checksum,
    )


def apply_migrations(
    settings: SnowflakeSettings, database: str, commit: str | None = None
) -> list[str]:
    """Apply each missing migration once and reject any checksum mismatch."""
    if not DATABASE_PATTERN.fullmatch(database):
        raise ValueError("Migrations may target only ONE_HEALTH_LYME_GAP_ATLAS_DEV or _PROD")
    plan = [
        migration
        for migration in load_migrations()
        if database == DEV_DATABASE or migration.version not in DEV_ONLY_MIGRATION_VERSIONS
        if database == PROD_DATABASE or migration.version not in PROD_ONLY_MIGRATION_VERSIONS
    ]
    with connect(settings, include_database=False) as connection, connection.cursor() as cursor:
        try:
            cursor.execute(f"USE DATABASE {database}")
            cursor.execute("SELECT version, sha256 FROM GOVERNANCE.SCHEMA_MIGRATIONS")
            applied = dict(cursor.fetchall())
        except ProgrammingError:
            applied = {}
        reconciled = _reconciled_legacy_migrations(cursor, database)
    executed: list[str] = []
    for migration in plan:
        prior_checksum = applied.get(migration.version)
        if prior_checksum == migration.sha256 or (
            prior_checksum is not None
            and is_line_ending_equivalent_checksum(migration.source, prior_checksum)
        ):
            continue
        if prior_checksum is not None:
            if is_authorized_legacy_reconciliation(
                database,
                migration.version,
                prior_checksum,
                migration.sha256,
                reconciled,
            ):
                continue
            raise ValueError(f"Checksum mismatch for already-applied {migration.version}")
        with connect(
            _migration_settings(settings, migration, database), include_database=False
        ) as connection:
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
