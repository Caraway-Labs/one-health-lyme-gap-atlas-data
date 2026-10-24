"""Register one reviewed EID source version in DEV; no general SQL interface."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from lyme_gap_atlas_data.ingestion.intelligence_runtime import (
    DAILY_DECISION,
    ENDPOINTS,
    PROD_DAILY_SOURCE_SHA256,
    PROD_SOURCE_DECISIONS,
    PROD_SOURCE_SHA256,
    pilot_watchdog,
)
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


def reviewed_package(
    source_id: str = SOURCE_ID, registry_version: int = 1
) -> tuple[dict[str, Any], str]:
    if source_id not in PROD_SOURCE_SHA256:
        raise PermissionError("EID_REVIEWED_PACKAGE_MISMATCH")
    if registry_version not in {1, 2}:
        raise PermissionError("EID_REVIEWED_PACKAGE_MISMATCH")
    path = (
        SOURCE
        if source_id == SOURCE_ID and registry_version == 1
        else ROOT / f"config/intelligence/{source_id}-source-v{registry_version}.json"
    )
    source = json.loads(path.read_text(encoding="utf-8"))
    receipt_path = (
        RECEIPTS
        if registry_version == 1
        else ROOT / "config/intelligence/daily-policy-receipts.json"
    )
    receipts = json.loads(receipt_path.read_text(encoding="utf-8"))["receipts"]
    validate_record("source", source)
    checksum = identity_hash(source)
    selected = [row for row in receipts if row.get("source_id") == source_id]
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
        source["source_id"] != source_id
        or checksum
        != (PROD_SOURCE_SHA256 if registry_version == 1 else PROD_DAILY_SOURCE_SHA256)[source_id]
        or source["registry_version"] != registry_version
        or source["fetch_location"] != ENDPOINTS[source_id]
        or source["approved_hosts"] != [urlsplit(ENDPOINTS[source_id]).hostname]
        or source["state"] != ("manual" if registry_version == 1 else "active")
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
        or source["approval"]["decision_ref"]
        != (PROD_SOURCE_DECISIONS[source_id] if registry_version == 1 else DAILY_DECISION)
        or source["trust_review"]["decision_ref"] != PROD_SOURCE_DECISIONS[source_id]
        or source["access_use"]["public_excerpt_permitted"]
        or source["access_use"]["excerpt_max_chars"] != 0
        or source["access_use"]["content_retention_policy_ref"]
        != source_id + "-metadata-raw-30d-v1"
        or receipt["decision_ref"]
        != (PROD_SOURCE_DECISIONS[source_id] if registry_version == 1 else DAILY_DECISION)
        or receipt["registry_version"] != registry_version
        or receipt["source_sha256"] != checksum
        or receipt["raw_policy_ref"] != "intelligence-raw-30d-v1"
        or receipt["retention_policy_ref"] != source["access_use"]["content_retention_policy_ref"]
        or receipt["artifact_policy"] != ARTIFACT_POLICY
        or native.policy_ref != source_id + "-native-metadata-v1"
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


def register(
    connection: Any,
    source: dict[str, Any],
    checksum: str,
    *,
    expected_identity: tuple[str, str, str, str] = IDENTITY,
) -> str:
    """Guarded single-source insert; exact existing row is an idempotent retry."""
    source_id = source["source_id"]
    version = source["registry_version"]
    expected_hashes = PROD_SOURCE_SHA256 if version == 1 else PROD_DAILY_SOURCE_SHA256
    if (
        version not in {1, 2}
        or source_id not in expected_hashes
        or checksum != expected_hashes[source_id]
    ):
        raise PermissionError("EID_REVIEWED_PACKAGE_MISMATCH")
    if identity_hash(source) != checksum:
        raise PermissionError("EID_REVIEWED_PACKAGE_MISMATCH")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()"
        )
        if cursor.fetchall() != [expected_identity]:
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
                (source_id,),
            )
            existing = cursor.fetchall()
            expected = (version, checksum, canonical_json(source))
            if existing:
                if existing[0][:2] == expected[:2] and json.loads(existing[0][2]) == source:
                    if len(existing) != version or (
                        version == 2
                        and (
                            existing[1][:2] != (1, PROD_SOURCE_SHA256[source_id])
                            or json.loads(existing[1][2]) != reviewed_package(source_id, 1)[0]
                        )
                    ):
                        raise PermissionError("EID_REGISTRY_STATE_CHANGED")
                    connection.rollback()
                    return "ALREADY_RECORDED"
                if (
                    version != 2
                    or len(existing) != 1
                    or existing[0][:2] != (1, PROD_SOURCE_SHA256[source_id])
                ):
                    raise PermissionError("EID_REGISTRY_STATE_CHANGED")
                previous, previous_hash = reviewed_package(source_id, 1)
                if (
                    json.loads(existing[0][2]) != previous
                    or identity_hash(previous) != previous_hash
                ):
                    raise PermissionError("EID_REGISTRY_STATE_CHANGED")
            elif version != 1:
                raise PermissionError("EID_RECORDED_V1_REQUIRED")
            cursor.execute(
                "INSERT INTO GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS "
                "(source_id,registry_version,registry_sha256,registry_document) "
                "SELECT %s,%s,%s,PARSE_JSON(%s)",
                (source_id, version, checksum, canonical_json(source)),
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
            source_id = os.environ.get("INTELLIGENCE_SOURCE_ID", SOURCE_ID)
            registry_version = int(os.environ.get("INTELLIGENCE_SOURCE_REGISTRY_VERSION", "1"))
            source, checksum = reviewed_package(source_id, registry_version)
            with connect(SnowflakeSettings()) as connection:
                result = register(connection, source, checksum)
        except PermissionError as error:
            raise SystemExit(str(error) or "EID_FIXED_REGISTRATION_FAILED") from None
        except Exception:
            raise SystemExit("EID_FIXED_REGISTRATION_FAILED") from None
        print(
            json.dumps(
                {
                    "result": result,
                    "source_id": source_id,
                    "registry_version": registry_version,
                    "sha256": checksum,
                }
            )
        )


if __name__ == "__main__":
    main()
