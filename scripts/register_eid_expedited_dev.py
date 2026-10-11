"""Register one reviewed EID source version in DEV; no general SQL interface."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from lyme_gap_atlas_data.ingestion.intelligence_runtime import pilot_watchdog
from lyme_gap_atlas_data.intelligence_items import canonical_json, identity_hash, validate_record
from lyme_gap_atlas_data.intelligence_metadata import NativeMetadataPolicy
from lyme_gap_atlas_data.sql_sessions import connect

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "config/intelligence/cdc-eid-expedited-source-v1.json"
RECEIPTS = ROOT / "config/intelligence/pilot-policy-receipts.json"
IDENTITY = (
    "OH_LYME_DEV_MIGRATION_DEPLOY_SVC",
    "OH_LYME_DEV_MIGRATION_DEPLOYER",
    "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
    "OH_LYME_DEV_INGEST_XS_WH",
)
SOURCE_ID = "cdc-eid-expedited"
DECISION_REF = "DATA-132-135-EID-ADMISSION-2026-10-09"
ARTIFACT_POLICY = "CDC_EID_RESTRICTED_RAW_30D_V1"


def reviewed_package() -> tuple[dict[str, Any], str]:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    receipts = json.loads(RECEIPTS.read_text(encoding="utf-8"))["receipts"]
    validate_record("source", source)
    checksum = identity_hash(source)
    selected = [row for row in receipts if row.get("source_id") == SOURCE_ID]
    if len(selected) != 1:
        raise PermissionError("EID_EXACT_RECEIPT_REQUIRED")
    receipt = selected[0]
    native = NativeMetadataPolicy(
        **{
            **receipt["native_policy"],
            **{
                key: frozenset(receipt["native_policy"][key])
                for key in ("inventory", "permitted_paths", "required_paths")
            },
        }
    )
    native.validate(source)
    if (
        source["source_id"] != SOURCE_ID
        or source["registry_version"] != 1
        or source["fetch_location"] != "https://wwwnc.cdc.gov/eid/rss/expedited.xml"
        or source["approved_hosts"] != ["wwwnc.cdc.gov"]
        or source["state"] != "manual"
        or source["cadence"]["poll_seconds"] != 86400
        or source["limits"]
        != {
            "maximum_bytes": 2097152,
            "timeout_seconds": 30,
            "maximum_items": 250,
            "maximum_redirects": 0,
            "maximum_attempts": 1,
        }
        or any(source[key]["status"] != "approved" for key in ("approval", "trust_review"))
        or any(source[key]["decision_ref"] != DECISION_REF for key in ("approval", "trust_review"))
        or source["access_use"]["public_excerpt_permitted"]
        or source["access_use"]["excerpt_max_chars"] != 0
        or source["access_use"]["content_retention_policy_ref"]
        != "cdc-eid-expedited-metadata-raw-30d-v1"
        or receipt["decision_ref"] != DECISION_REF
        or receipt["registry_version"] != 1
        or receipt["source_sha256"] != checksum
        or receipt["raw_policy_ref"] != "intelligence-raw-30d-v1"
        or receipt["retention_policy_ref"] != source["access_use"]["content_retention_policy_ref"]
        or receipt["artifact_policy"] != ARTIFACT_POLICY
        or native.policy_ref != "cdc-eid-expedited-native-metadata-v1"
        or native.permitted_paths
        != frozenset(
            {
                "feed/language",
                "feed/link",
                "feed/title",
                "item/link",
                "item/pubDate",
                "item/title",
            }
        )
        or native.updated_path is not None
        or native.published_path != "item/pubDate"
        or native.published_format != "rfc822"
    ):
        raise PermissionError("EID_REVIEWED_PACKAGE_MISMATCH")
    return source, checksum


def register(connection: Any, source: dict[str, Any], checksum: str) -> str:
    """Guarded single-source insert; exact existing row is an idempotent retry."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()"
        )
        if cursor.fetchall() != [IDENTITY]:
            raise PermissionError("EID_MIGRATION_SERVICE_IDENTITY_REQUIRED")
        cursor.execute(
            "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=10, "
            "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS=5, ABORT_DETACHED_QUERY=TRUE"
        )
        connection.autocommit(False)
        try:
            cursor.execute("BEGIN TRANSACTION")
            cursor.execute(
                "UPDATE GOVERNANCE.INTELLIGENCE_WRITE_GUARD "
                "SET write_sequence=write_sequence+1 WHERE guard_id=1"
            )
            if cursor.rowcount != 1:
                raise PermissionError("EID_WRITE_GUARD_REQUIRED")
            cursor.execute(
                "SELECT registry_version,registry_sha256,TO_JSON(registry_document) "
                "FROM GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS "
                "WHERE source_id=%s ORDER BY registry_version DESC LIMIT 2",
                (SOURCE_ID,),
            )
            existing = cursor.fetchall()
            expected = (1, checksum, canonical_json(source))
            if existing:
                if (
                    len(existing) != 1
                    or existing[0][:2] != expected[:2]
                    or json.loads(existing[0][2]) != source
                ):
                    raise PermissionError("EID_REGISTRY_STATE_CHANGED")
                connection.rollback()
                return "ALREADY_RECORDED"
            cursor.execute(
                "INSERT INTO GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS "
                "(source_id,registry_version,registry_sha256,registry_document) "
                "SELECT %s,%s,%s,PARSE_JSON(%s)",
                (SOURCE_ID, 1, checksum, canonical_json(source)),
            )
            if cursor.rowcount != 1:
                raise PermissionError("EID_INSERT_CARDINALITY_MISMATCH")
            connection.commit()
            return "RECORDED"
        except Exception:
            connection.rollback()
            raise


def main() -> None:
    os.environ["ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS"] = "10"
    with pilot_watchdog(seconds=120):
        try:
            source, checksum = reviewed_package()
            with connect(SnowflakeSettings()) as connection:
                result = register(connection, source, checksum)
        except Exception:
            raise SystemExit("EID_FIXED_REGISTRATION_FAILED") from None
        print(
            json.dumps(
                {
                    "result": result,
                    "source_id": SOURCE_ID,
                    "registry_version": 1,
                    "sha256": checksum,
                }
            )
        )


if __name__ == "__main__":
    main()
