"""Register one reviewed EID source version in DEV; no general SQL interface."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from lyme_gap_atlas_data.ingestion.intelligence_entrez import (
    ENTREZ_PERMITTED_PATHS,
    ESEARCH_URL,
    MAX_RESPONSE_BYTES,
    PUBLISHED_PATH,
    SOURCE_ORDER,
)
from lyme_gap_atlas_data.ingestion.intelligence_runtime import (
    ENDPOINTS,
    PROD_DAILY_SOURCE_SHA256,
    PROD_NATIVE_PATH_SUPERSET,
    PROD_SOURCE_DECISIONS,
    PROD_SOURCE_SHA256,
    PUBMED_ARTIFACT_POLICY,
    PUBMED_DECISION,
    PUBMED_SOURCE_IDS,
    pilot_watchdog,
    reviewed_prod_decision_ref,
    reviewed_prod_source_sha256,
)
from lyme_gap_atlas_data.intelligence_activations import (
    activation_merge_statement,
    rows_for_reviewed_registration,
)
from lyme_gap_atlas_data.intelligence_items import canonical_json, identity_hash, validate_record
from lyme_gap_atlas_data.intelligence_metadata import (
    NativeMetadataPolicy,
    prod_native_published_format_allowed,
)
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


def _reviewed_pubmed_package(source_id: str, registry_version: int) -> tuple[dict[str, Any], str]:
    """Version 1 Entrez document. PubMed has no RSS v2 file and no YAML definition."""
    if source_id not in SOURCE_ORDER or registry_version != 1:
        raise PermissionError("EID_REVIEWED_PACKAGE_MISMATCH")
    path = ROOT / f"config/intelligence/{source_id}-source-v1.json"
    source = json.loads(path.read_text(encoding="utf-8"))
    receipts = json.loads(
        (ROOT / "config/intelligence/pubmed-policy-receipts.json").read_text(encoding="utf-8")
    )["receipts"]
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
    pinned = PROD_DAILY_SOURCE_SHA256[source_id]
    if (
        source["source_id"] != source_id
        or checksum != pinned
        or checksum != PROD_SOURCE_SHA256[source_id]
        or source["registry_version"] != 1
        or source["transport"] != "entrez"
        or source["family"] != "pubmed"
        or source["trust_classification"] != "research_index"
        or source["fetch_location"] != ESEARCH_URL
        or source["approved_hosts"] != [urlsplit(ESEARCH_URL).hostname]
        or source["state"] != "active"
        or source["cadence"]["poll_seconds"] != 86400
        or source["limits"]
        != {
            "maximum_bytes": MAX_RESPONSE_BYTES,
            "timeout_seconds": 30,
            "maximum_items": 200,
            "maximum_redirects": 0,
            "maximum_attempts": 1,
        }
        or any(source[key]["status"] != "approved" for key in ("approval", "trust_review"))
        or source["approval"]["decision_ref"] != PUBMED_DECISION
        or source["trust_review"]["decision_ref"] != PROD_SOURCE_DECISIONS[source_id]
        or source["access_use"]["public_excerpt_permitted"]
        or source["access_use"]["excerpt_max_chars"] != 0
        or source["access_use"]["content_retention_policy_ref"]
        != source_id + "-metadata-raw-30d-v1"
        or receipt["decision_ref"] != PUBMED_DECISION
        or receipt["registry_version"] != 1
        or receipt["source_sha256"] != checksum
        or receipt["native_policy"]["source_sha256"] != checksum
        or receipt["raw_policy_ref"] != "intelligence-raw-30d-v1"
        or receipt["retention_policy_ref"] != source["access_use"]["content_retention_policy_ref"]
        or receipt["artifact_policy"] != PUBMED_ARTIFACT_POLICY
        or native.policy_ref != source_id + "-native-metadata-v1"
        or native.permitted_paths != ENTREZ_PERMITTED_PATHS
        or native.published_path != PUBLISHED_PATH
        or native.published_format != "iso8601"
        or source_id in ENDPOINTS
    ):
        raise PermissionError("EID_REVIEWED_PACKAGE_MISMATCH")
    return source, checksum


def reviewed_package(
    source_id: str = SOURCE_ID, registry_version: int = 1
) -> tuple[dict[str, Any], str]:
    if source_id in PUBMED_SOURCE_IDS:
        return _reviewed_pubmed_package(source_id, registry_version)
    if source_id not in PROD_SOURCE_SHA256 or registry_version not in {1, 2, 3}:
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
    selected = [
        row
        for row in receipts
        if row.get("source_id") == source_id and row.get("registry_version") == registry_version
    ]
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
        or checksum != reviewed_prod_source_sha256(source_id, registry_version)
        or source["registry_version"] != registry_version
        or source["fetch_location"]
        != ENDPOINTS[source_id]
        + ("?max=250" if registry_version == 3 and source_id == "cdc-mmwr" else "")
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
        != reviewed_prod_decision_ref(source_id, registry_version)
        or source["trust_review"]["decision_ref"] != PROD_SOURCE_DECISIONS[source_id]
        or source["access_use"]["public_excerpt_permitted"]
        or source["access_use"]["excerpt_max_chars"] != 0
        or source["access_use"]["content_retention_policy_ref"]
        != source_id + "-metadata-raw-30d-v1"
        or receipt["decision_ref"] != reviewed_prod_decision_ref(source_id, registry_version)
        or receipt["registry_version"] != registry_version
        or receipt["source_sha256"] != checksum
        or receipt["raw_policy_ref"] != "intelligence-raw-30d-v1"
        or receipt["retention_policy_ref"] != source["access_use"]["content_retention_policy_ref"]
        or receipt["artifact_policy"] != ARTIFACT_POLICY
        or native.policy_ref != source_id + "-native-metadata-v1"
        or (
            registry_version < 3
            and native.permitted_paths
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
        )
        or (
            registry_version == 3
            and (
                "item/description" not in native.permitted_paths
                or not native.permitted_paths <= PROD_NATIVE_PATH_SUPERSET
                or any(
                    "enclosure" in path or "mrss" in path or "copyright" in path
                    for path in native.permitted_paths
                )
            )
        )
        or native.updated_path is not None
        or native.published_path != "item/pubDate"
        or not prod_native_published_format_allowed(source_id, native)
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
    try:
        expected_hash = reviewed_prod_source_sha256(source_id, version)
    except PermissionError:
        raise PermissionError("EID_REVIEWED_PACKAGE_MISMATCH") from None
    if checksum != expected_hash:
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
                    if version == 1:
                        unchanged = len(existing) == 1
                    else:
                        prior_version = version - 1
                        prior_document, prior_hash = reviewed_package(source_id, prior_version)
                        unchanged = (
                            len(existing) == 2
                            and existing[1][:2] == (prior_version, prior_hash)
                            and json.loads(existing[1][2]) == prior_document
                        )
                    if not unchanged:
                        raise PermissionError("EID_REGISTRY_STATE_CHANGED")
                    connection.rollback()
                    return "ALREADY_RECORDED"
                if version == 2:
                    prior_version = 1
                    if len(existing) != 1:
                        raise PermissionError("EID_REGISTRY_STATE_CHANGED")
                elif version == 3:
                    prior_version = 2
                else:
                    raise PermissionError("EID_REGISTRY_STATE_CHANGED")
                previous, previous_hash = reviewed_package(source_id, prior_version)
                if (
                    existing[0][:2] != (prior_version, previous_hash)
                    or json.loads(existing[0][2]) != previous
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
            previous = None
            if version in {2, 3}:
                previous, _previous_hash = reviewed_package(source_id, version - 1)
            merge_sql, merge_params = activation_merge_statement(
                rows_for_reviewed_registration(source, previous, database=expected_identity[2])
            )
            cursor.execute(merge_sql, merge_params)
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
