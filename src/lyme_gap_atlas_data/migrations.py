"""Checksum-enforced, environment-neutral Snowflake migration execution."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from snowflake.connector.cursor import SnowflakeCursor
from snowflake.connector.errors import ProgrammingError

from .sql_sessions import connect

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
DATABASE_PATTERN = re.compile(r"^ONE_HEALTH_LYME_GAP_ATLAS_(DEV|PROD)$")
DEV_DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
PROD_DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_PROD"
INTELLIGENCE_PREREQUISITE_MIGRATION = {
    "version": "V142",
    "filename": "V142__dev_intelligence_retention_and_v2_view.sql",
    "sha256": "093017fc1507a67452eb47d1cec4c3c49e7a5881e981feede61bb88246986a15",
}
INTELLIGENCE_CLEANUP_MIGRATION = {
    "version": "V143",
    "filename": "V143__dev_intelligence_raw_cleanup_authority.sql",
    "sha256": "a92157ddac0d7b087b6c93f7fff65c65a081dd1e1aea0b5918a4e604a2a52968",
}
# PROD equivalent is a separate forward migration. It is activated only by the
# exact protected pending-set path and never grants executor procedure USAGE.
PROD_INTELLIGENCE_CLEANUP_MIGRATION = {
    "version": "V150",
    "filename": "V150__prod_intelligence_raw_cleanup_authority.sql",
    "sha256": "883be2e32a84a461bcd20a46216b2a188a443c98ed8d913b443821208c99b4cb",
}
PROD_PROACTIVE_INTELLIGENCE_CLEANUP_MIGRATION = {
    "version": "V162",
    "filename": "V162__prod_intelligence_proactive_cleanup.sql",
    "sha256": "451eda0f76fe21fda15058b59d1868804f7c32a49f87b21d77dd5f3b45c4b557",
}
PROTECTED_INTELLIGENCE_MIGRATIONS = (
    INTELLIGENCE_PREREQUISITE_MIGRATION,
    INTELLIGENCE_CLEANUP_MIGRATION,
    PROD_INTELLIGENCE_CLEANUP_MIGRATION,
    PROD_PROACTIVE_INTELLIGENCE_CLEANUP_MIGRATION,
)
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
    "V059",
    "V060",
    "V061",
    "V062",
    "V064",
    "V065",
    "V074",
    "V075",
    "V076",
    "V077",
    "V078",
    "V079",
    "V080",
    "V081",
    "V082",
    "V083",
    "V084",
    "V085",
    "V100",
    "V101",
    "V102",
    "V114",
    "V115",
    "V116",
    "V117",
    "V119",
    "V120",
    "V121",
    "V122",
    "V125",
    "V136",
    "V140",
    "V142",
    "V143",
    "V144",
    "V145",
    "V147",
}
PROD_ONLY_MIGRATION_VERSIONS = {
    "V049",
    "V050",
    "V051",
    "V052",
    "V086",
    "V087",
    "V088",
    "V089",
    "V090",
    "V091",
    "V092",
    "V093",
    "V094",
    "V095",
    "V096",
    "V097",
    "V098",
    "V099",
    "V126",
    "V129",
    "V130",
    "V131",
    "V132",
    "V133",
    "V139",
    "V141",
    "V146",
    "V148",
    # Extends V148's PROD authority and replaces a PROD-only final-copy procedure.
    "V149",
    "V150",
    "V151",
    "V152",
    "V153",
    "V154",
    "V156",
    "V160",
    "V161",
    "V162",
}
# V041 creates bounded GOVERNANCE views over RAW and CONFORMED. Its owner
# needs those exact reads, but the normal migration role and Streamlit owner
# must not inherit them.
VIEW_OWNER_MIGRATION_VERSIONS = {"V041", "V047", "V052", "V072"}
# Epic #294 consolidated the three role names below before the checksum-locked
# semantic-release migrations could be applied to the live DEV ledger.  Do not
# edit those source files: their source checksum is the ledger contract.  This
# is a deliberately narrow execution-time compatibility rendering for the
# pending V071-V073 transition only.
SEMANTIC_RELEASE_ROLE_COMPATIBILITY_VERSIONS = {"V071", "V072", "V073"}

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
CDC_LEGACY_LEDGER_AUTHORITY_PATH = Path(__file__).with_name("cdc_legacy_ledger_authority.json")
CDC_LEGACY_LEDGER_AUTHORITY_SHA256 = (
    "4e18aa0fb8be26841eeefbf1fc44060aae65be341adaa1abcc9d81a212c00f86"
)
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


def is_intelligence_prerequisite_batch(reviewed: list[dict[str, str]]) -> bool:
    """Route each pinned DEV intelligence migration through the bound envelope."""
    # Initial PROD bootstrap applies the historical authority then its replacement.
    prod_chain = [
        PROD_INTELLIGENCE_CLEANUP_MIGRATION,
        PROD_PROACTIVE_INTELLIGENCE_CLEANUP_MIGRATION,
    ]
    if reviewed == prod_chain:
        chain_metadata = {item.version: _migration_metadata(item) for item in load_migrations()}
        if any(chain_metadata.get(item["version"]) != item for item in prod_chain):
            raise ValueError("The reviewed intelligence prerequisite batch must be exact and alone")
        return True
    for pinned in PROTECTED_INTELLIGENCE_MIGRATIONS:
        selected = any(
            item["version"] == pinned["version"]
            or item["filename"] == pinned["filename"]
            or item["sha256"] == pinned["sha256"]
            for item in reviewed
        )
        if selected:
            actual = next(
                (item for item in load_migrations() if item.version == pinned["version"]), None
            )
            if actual is None or _migration_metadata(actual) != pinned or reviewed != [pinned]:
                raise ValueError(
                    "The reviewed intelligence prerequisite batch must be exact and alone"
                )
            return True
    return False


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
    if migration.version in SEMANTIC_RELEASE_ROLE_COMPATIBILITY_VERSIONS:
        rendered = (
            rendered.replace(
                f"OH_LYME_{environment}_GOVERNED_VIEW_OWNER",
                f"OH_LYME_{environment}_OWNER",
            )
            .replace(
                f"OH_LYME_{environment}_PIPELINE_RUNTIME",
                f"OH_LYME_{environment}_RUNTIME",
            )
            .replace(
                f"OH_LYME_{environment}_API_RUNTIME",
                f"OH_LYME_{environment}_READ",
            )
        )
    if "ONE_HEALTH_LYME_GAP_ATLAS;" in rendered:
        raise ValueError("The Alpha POC database is not a migration target")
    return rendered


def _executable_migration_sql(migration: Migration, database: str) -> str:
    """Avoid a connector-parsed empty statement after trailing SQL comments.

    The migration source and its ledger checksum remain unchanged. Only the
    statement stream handed to the connector drops final comment-only lines.
    """
    lines = render_migration(migration, database).splitlines()
    while lines and (not lines[-1].strip() or lines[-1].lstrip().startswith("--")):
        lines.pop()
    if not lines:
        raise ValueError(f"Migration {migration.version} has no executable SQL")
    return "\n".join(lines) + "\n"


def migration_plan(database: str) -> list[dict[str, str]]:
    """Return the non-secret, source-checksummed plan for an allowed target."""
    return [
        {"version": item.version, "filename": item.filename, "sha256": item.sha256}
        for item in load_migrations()
        if (database == DEV_DATABASE or item.version not in DEV_ONLY_MIGRATION_VERSIONS)
        and (database == PROD_DATABASE or item.version not in PROD_ONLY_MIGRATION_VERSIONS)
        and render_migration(item, database)
    ]


def pending_schema_creation_versions(database: str, applied_versions: set[str]) -> list[str]:
    """Find pending migrations that create an environment-local schema."""
    planned = {item["version"] for item in migration_plan(database)}
    return [
        migration.version
        for migration in load_migrations()
        if migration.version in planned - applied_versions
        and re.search(r"(?im)^\s*CREATE\s+SCHEMA\b", migration.source)
    ]


def migration_authority_preflight(settings: SnowflakeSettings, database: str) -> dict[str, object]:
    """Read-only checks for pending schema DDL and account-owned catalog grants."""
    if not DATABASE_PATTERN.fullmatch(database):
        raise ValueError("Migration preflight requires an isolated DEV or PROD database")
    expected_role = f"OH_LYME_{database.rsplit('_', 1)[1]}_MIGRATION_DEPLOYER"
    with connect(settings, include_database=False) as connection, connection.cursor() as cursor:
        cursor.execute(f"USE DATABASE {database}")
        cursor.execute("SELECT CURRENT_ROLE()")
        role_row = cursor.fetchone()
        if role_row is None:
            raise ValueError("Migration preflight could not read the current role")
        current_role = role_row[0]
        if current_role != expected_role:
            raise ValueError(f"Migration preflight requires {expected_role}; got {current_role}")
        cursor.execute("SELECT version FROM GOVERNANCE.SCHEMA_MIGRATIONS")
        applied = {row[0] for row in cursor.fetchall()}
        required = pending_schema_creation_versions(database, applied)
        create_schema_grant = "not_required"
        if required:
            cursor.execute(f"SHOW GRANTS TO ROLE {expected_role}")
            columns = [column[0].lower() for column in cursor.description]
            grants = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
            has_grant = any(
                grant.get("privilege") == "CREATE SCHEMA"
                and grant.get("granted_on") == "DATABASE"
                and grant.get("name") == database
                for grant in grants
            )
            if not has_grant:
                raise ValueError(
                    f"{expected_role} lacks CREATE SCHEMA on {database}; "
                    f"pending schema migrations: {', '.join(required)}"
                )
            create_schema_grant = "present"

        catalog_grants = "not_required"
        if database == PROD_DATABASE and "V126" not in applied:
            write_owner = "OH_LYME_PROD_DATASET_DISCOVERY_WRITE_OWNER"
            cursor.execute(f"SHOW GRANTS TO ROLE {write_owner}")
            columns = [column[0].lower() for column in cursor.description]
            grants = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
            required_tables = {
                f"{database}.GOVERNANCE.CATALOG_DISCOVERY_OBSERVATIONS",
                f"{database}.GOVERNANCE.CATALOG_RESOURCES",
            }
            granted_tables = {
                str(grant.get("name"))
                for grant in grants
                if grant.get("privilege") == "SELECT" and grant.get("granted_on") == "TABLE"
            }
            missing = required_tables - granted_tables
            if missing:
                raise ValueError(
                    "V126 requires account-owner SELECT grants to "
                    f"{write_owner} before migration DDL: {', '.join(sorted(missing))}"
                )
            catalog_grants = "present"
        return {
            "pending_schema_creation": required,
            "create_schema_grant": create_schema_grant,
            "v126_catalog_grants": catalog_grants,
        }


def migration_execution_role(migration: Migration, database: str) -> str | None:
    """Return a narrowly-scoped owner role for a migration that needs one."""
    match = DATABASE_PATTERN.fullmatch(database)
    if migration.version == "V140":
        if database != DEV_DATABASE:
            raise ValueError("Pinned Tier 1 publication migration is DEV-only")
        return "OH_LYME_DEV_TIER1_PUBLICATION_OWNER"
    if migration.version == "V141":
        if database != PROD_DATABASE:
            raise ValueError("Pinned Tier 1 production publication migration is PROD-only")
        return "OH_LYME_PROD_TIER1_PUBLICATION_OWNER"
    if match is None:
        raise ValueError("Migrations may target only ONE_HEALTH_LYME_GAP_ATLAS_DEV or _PROD")
    if migration.version in {"V044", "V053"}:
        if database != DEV_DATABASE:
            raise ValueError("DEV source-review view migration is DEV-only")
        return "OH_LYME_DEV_STREAMLIT_OWNER"
    if migration.version in {"V056", "V057", "V062"}:
        if database != DEV_DATABASE:
            raise ValueError("DEV PMC budget-owner migration is DEV-only")
        return "OH_LYME_DEV_KG_LLM_BUDGET_OWNER"
    if migration.version in {"V131", "V132", "V133"}:
        if database != PROD_DATABASE:
            raise ValueError("PROD PMC budget-owner migration is PROD-only")
        return "OH_LYME_PROD_KG_LLM_BUDGET_OWNER"
    if migration.version == "V049":
        if database != PROD_DATABASE:
            raise ValueError("Historical CDC PROD onboarding migration is PROD-only")
        return "OH_LYME_PROD_GOVERNED_VIEW_OWNER"
    if migration.version == "V050":
        if database != PROD_DATABASE:
            raise ValueError("Historical CDC PROD onboarding migration is PROD-only")
        return "OH_LYME_PROD_STREAMLIT_OWNER"
    if migration.version in {"V086", "V139", "V151", "V153"}:
        if database != PROD_DATABASE:
            raise ValueError("Production governed source admission is PROD-only")
        return "OH_LYME_PROD_OWNER"
    if migration.version in {"V072", "V117", "V123", "V124", "V127", "V128", "V138", "V155"}:
        if migration.version == "V117" and database != DEV_DATABASE:
            raise ValueError("DEV bulk stage migration is DEV-only")
        return f"OH_LYME_{match.group(1)}_OWNER"
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
    cursor: SnowflakeCursor, database: str, require_unique: bool = False
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
        rows = cursor.fetchall()
        if require_unique and len(rows) != len({version for version, _, _ in rows}):
            raise ValueError("CDC migration reconciliation evidence contains duplicate versions")
        return {version: (legacy, source) for version, legacy, source in rows}
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
    settings: SnowflakeSettings,
    database: str,
    commit: str | None = None,
    *,
    expected_pending: list[dict[str, str]] | None = None,
    protected_intelligence_prerequisite: bool = False,
    january_climate_only: bool = False,
    january_bulk_recovery_only: bool = False,
    january_point_query_only: bool = False,
    county_context_only: bool = False,
    cdc_admission_only: bool = False,
    release_integrity_only: bool = False,
    retained_lineage_only: bool = False,
    retained_lineage_human_only: bool = False,
    execution_receipts: list[dict[str, str]] | None = None,
) -> list[str]:
    """Apply each missing migration once and reject any checksum mismatch."""
    if not DATABASE_PATTERN.fullmatch(database):
        raise ValueError("Migrations may target only ONE_HEALTH_LYME_GAP_ATLAS_DEV or _PROD")
    integrity_versions = {"V157", "V158", "V159"}
    lineage_scope = retained_lineage_only or retained_lineage_human_only
    lineage_version = "V161" if retained_lineage_human_only else "V160"
    if lineage_scope and (
        (retained_lineage_only and retained_lineage_human_only)
        or database != PROD_DATABASE
        or expected_pending is None
        or not commit
        or not re.fullmatch(r"[0-9a-f]{40}", commit)
        or any(
            (
                release_integrity_only,
                cdc_admission_only,
                county_context_only,
                january_climate_only,
                january_bulk_recovery_only,
                january_point_query_only,
                protected_intelligence_prerequisite,
            )
        )
        or {m["version"] for m in expected_pending} not in ({"V150", lineage_version}, {"V150"})
    ):
        raise PermissionError(
            "Retained lineage requires exact protected retained-lineage PROD scope"
        )
    if release_integrity_only and (
        database != PROD_DATABASE
        or expected_pending is None
        or any(
            (
                cdc_admission_only,
                county_context_only,
                january_climate_only,
                january_bulk_recovery_only,
                january_point_query_only,
                protected_intelligence_prerequisite,
            )
        )
        or not commit
        or not re.fullmatch(r"[0-9a-f]{40}", commit)
    ):
        raise PermissionError("Release integrity requires an exact protected reviewed PROD scope")
    # Old bounded operators still review the complete pending metadata, but
    # cannot execute these newer migrations as a side effect.
    scoped_review = [
        item
        for item in expected_pending or []
        if item["version"] not in integrity_versions | {"V160", "V161"}
    ]
    if cdc_admission_only and (
        database != PROD_DATABASE
        or expected_pending is None
        or january_climate_only
        or january_bulk_recovery_only
        or january_point_query_only
        or county_context_only
        or protected_intelligence_prerequisite
        or {item["version"] for item in scoped_review} not in ({"V150"}, {"V150", "V156"})
    ):
        raise PermissionError("CDC admission requires the exact reviewed pending V156 scope")
    if county_context_only and (
        database != PROD_DATABASE
        or expected_pending is None
        or january_climate_only
        or january_bulk_recovery_only
        or january_point_query_only
        or protected_intelligence_prerequisite
        or {item["version"] for item in scoped_review} != {"V150", "V155"}
    ):
        raise PermissionError("County context requires only reviewed pending V150/V155")
    if january_point_query_only and (
        database != PROD_DATABASE
        or expected_pending is None
        or january_climate_only
        or january_bulk_recovery_only
        or protected_intelligence_prerequisite
        or {item["version"] for item in scoped_review} != {"V150", "V154"}
    ):
        raise PermissionError("Point optimization requires only reviewed pending V150/V154")
    if january_bulk_recovery_only and (
        database != PROD_DATABASE
        or expected_pending is None
        or january_climate_only
        or protected_intelligence_prerequisite
        or {item["version"] for item in scoped_review} != {"V150", "V153"}
    ):
        raise PermissionError("Bulk recovery requires only reviewed pending V150/V153")
    if january_climate_only and (
        database != PROD_DATABASE
        or expected_pending is None
        or protected_intelligence_prerequisite
        or not {item["version"] for item in scoped_review} <= {"V150", "V151", "V152"}
    ):
        raise PermissionError("January PROD migrations require the exact reviewed full pending set")
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
            ledger = cursor.fetchall()
            applied = dict(ledger)
        except ProgrammingError:
            if expected_pending is not None:
                raise
            applied = {}
        reconciled = _reconciled_legacy_migrations(
            cursor, database, cdc_admission_only or release_integrity_only or lineage_scope
        )
        if cdc_admission_only or release_integrity_only or lineage_scope:
            duplicate_versions = {
                version for version, count in Counter(v for v, _ in ledger).items() if count > 1
            }
            legacy_versions = set(LEGACY_PROD_MIGRATION_CHECKSUMS)
            if duplicate_versions - {"V020", "V028", "V071"}:
                raise ValueError("CDC migration ledger contains duplicate versions")
            if duplicate_versions or any(
                checksum == LEGACY_PROD_MIGRATION_CHECKSUMS.get(version)
                for version, checksum in ledger
            ):
                # Retain the immutable historical rows. Only the exact existing
                # PROD exception, with retained reconciliation evidence, is valid.
                cursor.execute(
                    "SELECT version, filename, sha256 FROM GOVERNANCE.SCHEMA_MIGRATIONS "
                    "WHERE version IN ('V022', 'V028')"
                )
                legacy_rows = cursor.fetchall()
                for migration in legacy_prod_reconciliation_plan(legacy_rows, plan):
                    if not is_authorized_legacy_reconciliation(
                        database,
                        migration.version,
                        LEGACY_PROD_MIGRATION_CHECKSUMS[migration.version],
                        migration.sha256,
                        reconciled,
                    ):
                        raise ValueError(
                            "CDC historical ledger lacks valid reconciliation evidence"
                        )
                if sorted((v, h) for v, _, h in legacy_rows) != sorted(
                    (v, h) for v, h in ledger if v in legacy_versions
                ):
                    raise ValueError("CDC historical ledger changed during validation")
                # Exact retained rows, not an allowance inferred from equal hashes.
                # V020 authority is the reconciled historical V022; V071 has a
                # new dated owner recognition, not retrospective execution approval.
                try:
                    authority_text = CDC_LEGACY_LEDGER_AUTHORITY_PATH.read_text(encoding="utf-8")
                except OSError as exc:
                    raise ValueError("CDC historical ledger authority is missing") from exc
                if (
                    hashlib.sha256(authority_text.encode()).hexdigest()
                    != CDC_LEGACY_LEDGER_AUTHORITY_SHA256
                ):
                    raise ValueError(
                        "CDC historical ledger authority does not match reviewed evidence"
                    )
                authority = json.loads(authority_text)
                cursor.execute(
                    """SELECT version, filename, sha256, deployment_commit, applied_by,
                    TO_CHAR(CONVERT_TIMEZONE('UTC', applied_at), 'YYYY-MM-DD"T"HH24:MI:SS.FF9')
                    FROM GOVERNANCE.SCHEMA_MIGRATIONS
                    WHERE version IN ('V020', 'V028', 'V071')"""
                )
                identity_rows = cursor.fetchall()
                if sorted(tuple(row) for row in authority["records"]) != sorted(identity_rows):
                    raise ValueError(
                        "CDC historical ledger identities do not match reviewed authority"
                    )
                if sorted((r[0], r[2]) for r in identity_rows) != sorted(
                    (v, h) for v, h in ledger if v in {"V020", "V028", "V071"}
                ):
                    raise ValueError("CDC historical ledger changed during identity validation")
            if set(applied) - {item.version for item in plan}:
                raise ValueError("CDC migration ledger contains unexpected versions")
            if cdc_admission_only:
                target = next(item for item in plan if item.version == "V156")
                if "V150" in applied:
                    raise PermissionError("CDC scope requires V150 to remain pending")
                if "V156" in applied:
                    # A failed image promotion may follow a successful immutable DDL
                    # step. Resume only the same reviewed commit and exact checksum.
                    cursor.execute(
                        "SELECT filename,sha256,deployment_commit "
                        "FROM GOVERNANCE.SCHEMA_MIGRATIONS "
                        "WHERE version=%s",
                        ("V156",),
                    )
                    if (
                        not commit
                        or not re.fullmatch(r"[0-9a-f]{40}", commit)
                        or applied["V156"] != target.sha256
                        or cursor.fetchall() != [(target.filename, target.sha256, commit)]
                    ):
                        raise ValueError(
                            "CDC retry requires the exact reviewed V156 ledger receipt"
                        )
                    reviewed_target = [
                        item for item in expected_pending or [] if item["version"] == "V156"
                    ]
                    if reviewed_target and reviewed_target != [_migration_metadata(target)]:
                        raise ValueError("CDC retry reviewed V156 metadata mismatch")
                    # Original dispatch inputs remain valid on a GitHub run retry;
                    # remove only the independently verified, already-applied V156.
                    expected_pending = [
                        item for item in expected_pending or [] if item["version"] != "V156"
                    ]
            if release_integrity_only or lineage_scope:
                retry_versions = {lineage_version} if lineage_scope else integrity_versions
                for target in (m for m in plan if m.version in retry_versions):
                    if target.version not in applied:
                        continue
                    cursor.execute(
                        "SELECT filename,sha256,deployment_commit "
                        "FROM GOVERNANCE.SCHEMA_MIGRATIONS "
                        "WHERE version=%s",
                        (target.version,),
                    )
                    if applied[target.version] != target.sha256 or cursor.fetchall() != [
                        (target.filename, target.sha256, commit)
                    ]:
                        raise ValueError(
                            "Integrity retry requires exact reviewed migration receipts"
                        )
                    reviewed_target = [
                        m for m in expected_pending or [] if m["version"] == target.version
                    ]
                    if reviewed_target and reviewed_target != [_migration_metadata(target)]:
                        raise ValueError("Integrity retry reviewed metadata differs")
                    expected_pending = [
                        m for m in expected_pending or [] if m["version"] != target.version
                    ]
    if expected_pending is not None:
        require_reviewed_pending_set(
            [_migration_metadata(item) for item in plan if item.version not in applied],
            expected_pending,
        )
    if cdc_admission_only and not {"V149", "V155"} <= set(applied):
        raise PermissionError("CDC predecessor authority and current context must already exist")
    if not cdc_admission_only and any(
        item.version == "V156" and item.version not in applied for item in plan
    ):
        raise PermissionError("V156 requires the protected CDC admission path")
    if release_integrity_only and not {"V141", "V149", "V151", "V152", "V155", "V156"} <= set(
        applied
    ):
        raise PermissionError("Integrity publication prerequisites must already be installed")
    scoped_operation = any(
        (
            lineage_scope,
            release_integrity_only,
            cdc_admission_only,
            county_context_only,
            january_climate_only,
            january_bulk_recovery_only,
            january_point_query_only,
        )
    )
    if (
        database == PROD_DATABASE
        and not scoped_operation
        and any(m.version in integrity_versions and m.version not in applied for m in plan)
    ):
        raise PermissionError("V157/V158/V159 require the protected release integrity path")
    if lineage_scope and not {"V137", "V148", "V157", "V158", "V159"} <= set(applied):
        raise PermissionError("Retained lineage dependencies must already be installed")
    if retained_lineage_human_only and "V160" not in applied:
        raise PermissionError("Human lineage requires the installed restricted V160 surface")
    if not scoped_operation and any(
        m.version in {"V160", "V161"} and m.version not in applied for m in plan
    ):
        raise PermissionError("Retained lineage requires its protected path")
    if january_point_query_only and not {"V151", "V152", "V153"} <= set(applied):
        raise PermissionError("Prior January migrations must already be applied")
    if not (january_point_query_only or release_integrity_only) and any(
        item.version == "V154" and item.version not in applied for item in plan
    ):
        raise PermissionError("V154 requires the protected point optimization path")
    if january_bulk_recovery_only and not {"V151", "V152"} <= set(applied):
        raise PermissionError("Prior January migrations must already be applied")
    if january_bulk_recovery_only and "V117" in applied:
        raise PermissionError("Unexpected DEV-only V117 PROD ledger entry requires reconciliation")
    if not (january_bulk_recovery_only or release_integrity_only) and any(
        item.version == "V153" and item.version not in applied for item in plan
    ):
        raise PermissionError("V153 requires the protected bulk recovery path")
    if not (january_climate_only or release_integrity_only) and any(
        item.version in {"V151", "V152"} and item.version not in applied for item in plan
    ):
        raise PermissionError("January PROD authority/views require the reviewed climate-only path")
    for pinned in PROTECTED_INTELLIGENCE_MIGRATIONS:
        if (
            january_climate_only
            or january_bulk_recovery_only
            or january_point_query_only
            or county_context_only
            or cdc_admission_only
            or release_integrity_only
            or lineage_scope
        ):
            # V150 is deliberately retained as pending, never executed in this scope.
            continue
        prerequisite = next((item for item in plan if item.version == pinned["version"]), None)
        protected_database = (
            DEV_DATABASE if pinned["version"] in {"V142", "V143"} else PROD_DATABASE
        )
        if (
            database == protected_database
            and prerequisite is not None
            and prerequisite.version not in applied
            and (
                not protected_intelligence_prerequisite
                or expected_pending is None
                or not is_intelligence_prerequisite_batch(expected_pending)
                or _migration_metadata(prerequisite) != pinned
            )
        ):
            raise PermissionError(
                f"{pinned['version']} requires the protected intelligence prerequisite path"
            )
    if (
        database == PROD_DATABASE
        and not (county_context_only or release_integrity_only)
        and any(item.version == "V155" and item.version not in applied for item in plan)
    ):
        raise PermissionError("V155 requires the protected county context path")
    if (
        database == PROD_DATABASE
        and any(item.version == "V162" and item.version not in applied for item in plan)
        and "V150" not in applied
        and not any(item.version == "V150" for item in plan)
    ):
        raise PermissionError("V162 requires recorded V150 or the exact reviewed V150/V162 chain")
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
        if lineage_scope and migration.version != lineage_version:
            continue
        if release_integrity_only and migration.version not in integrity_versions:
            continue
        if county_context_only and migration.version != "V155":
            continue
        if cdc_admission_only and migration.version != "V156":
            continue
        if january_point_query_only and migration.version != "V154":
            continue
        if january_bulk_recovery_only and migration.version != "V153":
            continue
        if january_climate_only and migration.version not in {"V151", "V152"}:
            continue
        with connect(
            _migration_settings(settings, migration, database), include_database=False
        ) as connection:
            results = connection.execute_string(_executable_migration_sql(migration, database))
            if execution_receipts is not None:
                for result in results:
                    if result.sfqid:
                        execution_receipts.append(
                            {"version": migration.version, "query_id": result.sfqid}
                        )
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


def _migration_metadata(migration: Migration) -> dict[str, str]:
    return {
        "version": migration.version,
        "filename": migration.filename,
        "sha256": migration.sha256,
    }


def pending_migration_plan(settings: SnowflakeSettings, database: str) -> list[dict[str, str]]:
    """Read the exact pending source set; an unreadable ledger is a stop condition."""
    plan = migration_plan(database)
    with connect(settings, include_database=False) as connection, connection.cursor() as cursor:
        cursor.execute(f"USE DATABASE {database}")
        cursor.execute("SELECT version FROM GOVERNANCE.SCHEMA_MIGRATIONS")
        applied = {row[0] for row in cursor.fetchall()}
    return [item for item in plan if item["version"] not in applied]


def parse_reviewed_pending_set(value: str) -> list[dict[str, str]]:
    """Accept explicit JSON metadata only, including an explicitly reviewed empty set."""
    try:
        reviewed = json.loads(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Reviewed pending migrations must be a JSON array") from error
    if not isinstance(reviewed, list):
        raise ValueError("Reviewed pending migrations must be a JSON array")
    versions: set[str] = set()
    result: list[dict[str, str]] = []
    for item in reviewed:
        if (
            not isinstance(item, dict)
            or set(item) != {"version", "filename", "sha256"}
            or not all(isinstance(field, str) for field in item.values())
            or not re.fullmatch(r"V[0-9]+", item["version"])
            or not re.fullmatch(r"V[0-9]+__[A-Za-z0-9_-]+\.sql", item["filename"])
            or not item["filename"].startswith(item["version"] + "__")
            or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
            or item["version"] in versions
        ):
            raise ValueError("Invalid or duplicate reviewed migration metadata")
        versions.add(item["version"])
        result.append(item)
    return result


def require_reviewed_pending_set(
    actual: list[dict[str, str]], reviewed: list[dict[str, str]]
) -> None:
    """Compare complete metadata sets without accepting additions or omissions."""
    validated = parse_reviewed_pending_set(json.dumps(reviewed))
    if sorted(actual, key=lambda item: item["version"]) != sorted(
        validated, key=lambda item: item["version"]
    ):
        raise ValueError("Actual pending migrations differ from the reviewed pending set")
