"""Register only the reviewed EID version 1 in PROD under the migration owner."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from lyme_gap_atlas_data.ingestion.intelligence_runtime import (
    PROD_DAILY_SOURCE_SHA256,
    PROD_SOURCE_SHA256,
    pilot_watchdog,
)
from lyme_gap_atlas_data.intelligence_items import identity_hash
from lyme_gap_atlas_data.migrations import (
    PROD_FEED_EXPANSION_CLEANUP_MIGRATION,
    PROD_INTELLIGENCE_DAILY_VIEW_MIGRATION,
    pending_migration_plan,
)
from lyme_gap_atlas_data.settings import PipelineSettings
from lyme_gap_atlas_data.sql_sessions import connect

_dev_module_path = Path(__file__).with_name("register_eid_expedited_dev.py")
_dev_spec = importlib.util.spec_from_file_location("eid_reviewed_registration", _dev_module_path)
if _dev_spec is None or _dev_spec.loader is None:
    raise RuntimeError("Reviewed EID registration source unavailable")
_dev_module = importlib.util.module_from_spec(_dev_spec)
_dev_spec.loader.exec_module(_dev_module)
register = _dev_module.register
reviewed_package = _dev_module.reviewed_package

DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_PROD"
IDENTITY = (
    "OH_LYME_PROD_MIGRATION_DEPLOY_SVC",
    "OH_LYME_PROD_MIGRATION_DEPLOYER",
    DATABASE,
    "OH_LYME_PROD_INGEST_XS_WH",
)
SOURCE_SHA256 = "51705ebb4c82d7fc8e992f2e5793c45f79f202578ba487747aa2109e695f33a4"
V146 = (
    "V146__prod_intelligence_retention_and_v2_view.sql",
    "85a2fd022e4024bfb0217bad6cec78bdfcd1da255a662ebd5c48c7a073eb22dc",
)


def registry_document_path(source_id: str, version: int) -> Path:
    return Path(__file__).parents[1] / f"config/intelligence/{source_id}-source-v{version}.json"


def guard_prod_registry_hash(source_id: str, version: int) -> None:
    """Refuse a registry file whose digest is not the pinned one.

    reviewed_package also refuses that file. This guard names the hash failure
    before that broader package check runs.
    """
    expected = (PROD_SOURCE_SHA256 if version == 1 else PROD_DAILY_SOURCE_SHA256).get(source_id)
    path = registry_document_path(source_id, version)
    if expected is None or not path.is_file():
        return
    digest = identity_hash(json.loads(path.read_text(encoding="utf-8")))
    if digest != expected:
        raise PermissionError("EID_PROD_SOURCE_HASH_CHANGED")


def verify_schema(
    connection: Any, source_id: str = "cdc-eid-expedited", registry_version: int = 1
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()"
        )
        if cursor.fetchall() != [IDENTITY]:
            raise PermissionError("EID_PROD_MIGRATION_IDENTITY_REQUIRED")
        cursor.execute(
            "SELECT filename, sha256 FROM GOVERNANCE.SCHEMA_MIGRATIONS WHERE version='V146'"
        )
        if cursor.fetchall() != [V146]:
            raise PermissionError("EID_PROD_V146_REQUIRED")
        if source_id != "cdc-eid-expedited" or registry_version == 2:
            migration = PROD_FEED_EXPANSION_CLEANUP_MIGRATION
            cursor.execute(
                "SELECT filename,sha256 FROM GOVERNANCE.SCHEMA_MIGRATIONS WHERE version='V163'"
            )
            if cursor.fetchall() != [(migration["filename"], migration["sha256"])]:
                raise PermissionError("CDC_PROD_EXPANDED_RETENTION_REQUIRED")
            cursor.execute(
                "SELECT COUNT(*) FROM GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_HANDOFF_ATTESTATIONS a "
                "JOIN GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_EXPECTED_HANDOFF_V e "
                "ON a.MIGRATION_SHA256=e.MIGRATION_SHA256 "
                "AND a.PROCEDURE_BODY_SHA256=e.PROCEDURE_BODY_SHA256 "
                "WHERE a.MIGRATION_SHA256=%s "
                "AND a.OWNER_ROLE='OH_LYME_PROD_INTELLIGENCE_RAW_PURGE_OWNER' "
                "AND LENGTH(a.HANDOFF_REF)>0 AND LENGTH(a.ATTESTED_BY)>0",
                (migration["sha256"],),
            )
            if cursor.fetchall() != [(1,)]:
                raise PermissionError("CDC_PROD_EXPANDED_RETENTION_HANDOFF_REQUIRED")


def main() -> None:
    os.environ["ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS"] = "10"
    with pilot_watchdog(seconds=120):
        try:
            settings = PipelineSettings()
            if settings.topx_env != "prod" or settings.snowflake_database != DATABASE:
                raise PermissionError("EID_PROD_ENVIRONMENT_REQUIRED")
            source_id = os.environ.get("INTELLIGENCE_SOURCE_ID", "cdc-eid-expedited")
            version = int(os.environ.get("INTELLIGENCE_SOURCE_REGISTRY_VERSION", "1"))
            guard_prod_registry_hash(source_id, version)
            source, checksum = reviewed_package(source_id, version)
            if checksum != (PROD_SOURCE_SHA256 if version == 1 else PROD_DAILY_SOURCE_SHA256).get(
                source_id
            ):
                raise PermissionError("EID_PROD_SOURCE_HASH_CHANGED")
            with connect(SnowflakeSettings()) as connection:
                verify_schema(connection, source_id, version)
                if version == 2:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT filename,sha256 FROM GOVERNANCE.SCHEMA_MIGRATIONS "
                            "WHERE version='V164'"
                        )
                        m = PROD_INTELLIGENCE_DAILY_VIEW_MIGRATION
                        if cursor.fetchall() != [(m["filename"], m["sha256"])]:
                            raise PermissionError("INTELLIGENCE_DAILY_VIEW_REQUIRED")
                if pending_migration_plan(SnowflakeSettings(), DATABASE):
                    raise PermissionError("EID_PROD_PENDING_MIGRATIONS")
                result = register(connection, source, checksum, expected_identity=IDENTITY)
        except PermissionError as error:
            message = str(error)
            if message == "EID_PROD_SOURCE_HASH_CHANGED":
                raise SystemExit(message) from None
            raise SystemExit("EID_PROD_FIXED_REGISTRATION_FAILED") from None
        except Exception:
            raise SystemExit("EID_PROD_FIXED_REGISTRATION_FAILED") from None
        print(
            json.dumps(
                {
                    "result": result,
                    "source_id": source_id,
                    "registry_version": version,
                    "sha256": checksum,
                }
            )
        )


if __name__ == "__main__":
    main()
