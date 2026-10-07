"""Fixed read-only DEV intelligence metadata preflight; private evidence only."""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from lyme_gap_atlas_data.climate_dev_validation import DEV, ROLE, USER, WAREHOUSE
from lyme_gap_atlas_data.intelligence_items import identity_hash, validate_record
from lyme_gap_atlas_data.intelligence_metadata import NativeMetadataPolicy

SOURCE_ENDPOINTS = {
    "cdc-eid-expedited": "https://wwwnc.cdc.gov/eid/rss/expedited.xml",
    "nih-news-releases": "https://www.nih.gov/news-releases/feed.xml",
}
MAX_SOURCE_BYTES = 65536
RECEIPTS = Path(__file__).parents[1] / "config/intelligence/pilot-policy-receipts.json"
# Exact restricted policy identifiers admitted by independent code review.
# No real identifier has yet been admitted; a runtime receipt cannot approve one.
REVIEWED_RESTRICTED_ARTIFACT_POLICIES: dict[str, str] = {}


def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in pairs:
        if key in result:
            raise ValueError("DUPLICATE_JSON_KEY")
        result[key] = item
    return result


def source_result(
    source_id: str, records: list[dict[str, Any]], receipts: list[dict[str, Any]]
) -> dict[str, Any]:
    """Pure validation: no runtime identity guard, SQL, approval or output of values."""
    result = {"source_id": source_id, "passed": False, "exact_reviewed_source_matches": False}

    def fail(reason: str) -> dict[str, Any]:
        return {**result, "reason": reason}

    if not records:
        return fail("ABSENT")
    if len(records) != 1:
        return fail("DUPLICATE_LATEST")
    row = records[0]
    text = value(row, "source_document_json")
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        return fail("OVERSIZED_OR_MISSING_DOCUMENT")
    try:
        source = json.loads(text, object_pairs_hook=no_duplicate_keys)
        validate_record("source", source)
    except (ValueError, TypeError, AttributeError):
        return fail("INVALID_DOCUMENT")
    if value(row, "source_id") != source_id or source["source_id"] != source_id:
        return fail("SOURCE_ID_MISMATCH")
    version = value(row, "registry_version")
    if type(version) is not int or version != source["registry_version"]:
        return fail("VERSION_MISMATCH")
    checksum = identity_hash(source)
    if value(row, "registry_sha256") != checksum:
        return fail("HASH_MISMATCH")
    if source["fetch_location"] != SOURCE_ENDPOINTS[source_id] or source["transport"] != "rss":
        return fail("ENDPOINT_MISMATCH")
    if source["approved_hosts"] != [SOURCE_ENDPOINTS[source_id].split("/")[2]]:
        return fail("HOST_MISMATCH")
    if (
        source["cadence"]["poll_seconds"] != 86400
        or source["cadence"]["expected_item_seconds"] is not None
    ):
        return fail("CADENCE_MISMATCH")
    expected_limits = {
        "maximum_bytes": 2097152,
        "maximum_items": 250,
        "timeout_seconds": 30,
        "maximum_redirects": 0,
        "maximum_attempts": 1,
    }
    if source["limits"] != expected_limits:
        return fail("LIMITS_MISMATCH")
    if source["geographies"] or source["topics"]:
        return fail("INFERRED_CLASSIFICATION")
    if (
        source["state"] not in {"active", "manual"}
        or source["trust_classification"] != "official_public_health"
        or any(source[key]["status"] != "approved" for key in ("approval", "trust_review"))
    ):
        return fail("REVIEW_REQUIRED")
    access = source["access_use"]
    if (
        access["public_excerpt_permitted"]
        or access["excerpt_max_chars"] != 0
        or not access["availability_verified_at"]
    ):
        return fail("RIGHTS_OR_AVAILABILITY_MISMATCH")
    selected = [r for r in receipts if r.get("source_id") == source_id]
    if len(selected) != 1:
        return fail("REVIEWED_CANDIDATE_REQUIRED")
    receipt = selected[0]
    # Version/hash pins come from privately reviewed owner evidence and normal
    # code review, never fixtures or runtime output. Hash equality binds the full
    # reviewed document (including rights/review references) without publishing it.
    if (
        type(receipt.get("registry_version")) is not int
        or receipt.get("registry_version") != version
        or receipt.get("source_sha256") != checksum
    ):
        return fail("REVIEWED_CANDIDATE_MISMATCH")
    if receipt.get("decision_ref") != source["approval"]["decision_ref"]:
        return fail("REVIEW_REFERENCE_MISMATCH")
    if (
        receipt.get("raw_policy_ref") != "intelligence-raw-30d-v1"
        or not receipt.get("retention_policy_ref")
        or access["content_retention_policy_ref"] != receipt["retention_policy_ref"]
    ):
        return fail("RETENTION_MISMATCH")
    artifact_policy = receipt.get("artifact_policy")
    reviewed_policy = REVIEWED_RESTRICTED_ARTIFACT_POLICIES.get(source_id)
    if (
        not isinstance(reviewed_policy, str)
        or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,199}", reviewed_policy)
        or reviewed_policy == "PUBLIC_SEVEN_YEAR"
    ):
        return fail("ARTIFACT_POLICY_REVIEW_REQUIRED")
    if (
        not isinstance(artifact_policy, str)
        or not artifact_policy
        or artifact_policy != reviewed_policy
    ):
        return fail("ARTIFACT_POLICY_MISMATCH")
    try:
        native_doc = receipt["native_policy"]
        native = NativeMetadataPolicy(
            **{
                **native_doc,
                **{
                    k: frozenset(native_doc[k])
                    for k in ("inventory", "permitted_paths", "required_paths")
                },
            }
        )
        native.validate(source)
        safe_paths = {
            "feed/language",
            "feed/link",
            "feed/title",
            "item/link",
            "item/pubDate",
            "item/title",
        }
        if (
            not native.policy_ref
            or not native.permitted_paths <= safe_paths
            or native.published_path != "item/pubDate"
            or native.published_format != "rfc822"
            or native.updated_path is not None
        ):
            return fail("NATIVE_POLICY_MISMATCH")
    except (KeyError, TypeError, ValueError):
        return fail("NATIVE_POLICY_MISMATCH")
    return {**result, "passed": True, "exact_reviewed_source_matches": True, "reason": "PASS"}


def inspect_sources(cursor: Any, report: dict[str, Any], receipts: list[dict[str, Any]]) -> None:
    report["sources"] = []
    report["source_prerequisites_passed"] = False
    for source_id in SOURCE_ENDPOINTS:
        # LIMIT 2 preserves duplicate-latest detection while bounding row count.
        sql = f"""SELECT source_id, registry_version, registry_sha256,
            IFF(OCTET_LENGTH(TO_JSON(registry_document)) <= {MAX_SOURCE_BYTES},
                TO_JSON(registry_document), NULL) AS source_document_json
            FROM {DEV}.GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS
            WHERE source_id = '{source_id}'
            QUALIFY DENSE_RANK() OVER (ORDER BY registry_version DESC) = 1
            LIMIT 2"""
        try:
            cursor.execute(sql, timeout=10)
            result = source_result(source_id, rows(cursor), receipts)
        except Exception:
            result = {
                "source_id": source_id,
                "passed": False,
                "exact_reviewed_source_matches": False,
                "reason": "UNKNOWN_QUERY_FAILED",
            }
        report["sources"].append(result)
        print(json.dumps(report, sort_keys=True), flush=True)
    report["source_prerequisites_passed"] = all(result["passed"] for result in report["sources"])


TARGETS = (
    ("TABLE", "GOVERNANCE", "INTELLIGENCE_RAW_RETENTION_DOCUMENTS"),
    ("TABLE", "GOVERNANCE", "INTELLIGENCE_RAW_RETENTION_AUDIT"),
    ("TABLE", "GOVERNANCE", "INTELLIGENCE_SOURCE_VERSIONS"),
    ("VIEW", "PRESENTATION", "INTELLIGENCE_FEED_V"),
    ("VIEW", "PRESENTATION", "INTELLIGENCE_FEED_V2"),
)


def budget(confirmation: str) -> None:
    # Private dollar/price/request receipts stay outside public Actions inputs/logs.
    # This confirms prior independent reconciliation, not billing measurement.
    if confirmation != "true":
        raise ValueError("FEED_PRIVATE_ACCOUNTING_CONFIRMATION_REQUIRED")


def rows(cursor: Any) -> list[dict[str, Any]]:
    return [
        dict(zip([column[0] for column in cursor.description], row, strict=True))
        for row in cursor.fetchall()
    ]


TABLE_SHAPES = {
    "INTELLIGENCE_RAW_RETENTION_DOCUMENTS": (
        ("DOCUMENT_TYPE", "VARCHAR(32)", False, ""),
        ("DOCUMENT_KEY", "VARCHAR(256)", False, ""),
        ("DOCUMENT_SHA256", "VARCHAR(64)", False, ""),
        ("DOCUMENT", "VARIANT", False, ""),
        ("REGISTERED_AT", "TIMESTAMP_TZ(9)", False, "CURRENT_TIMESTAMP()"),
    ),
    "INTELLIGENCE_RAW_RETENTION_AUDIT": (
        ("RECEIPT_SHA256", "VARCHAR(64)", False, ""),
        ("DOCUMENT", "VARIANT", False, ""),
        ("REGISTERED_AT", "TIMESTAMP_TZ(9)", False, "CURRENT_TIMESTAMP()"),
    ),
    "INTELLIGENCE_SOURCE_VERSIONS": (
        ("SOURCE_ID", "VARCHAR(200)", False, ""),
        ("REGISTRY_VERSION", "NUMBER(38,0)", False, ""),
        ("REGISTRY_SHA256", "VARCHAR(64)", False, ""),
        ("REGISTRY_DOCUMENT", "VARIANT", False, ""),
        ("RECORDED_AT", "TIMESTAMP_LTZ(9)", False, "CURRENT_TIMESTAMP()"),
    ),
}
ROLE_PRIVILEGES = {
    "INTELLIGENCE_RAW_RETENTION_DOCUMENTS": ("OH_LYME_DEV_RUNTIME", {"SELECT", "INSERT"}),
    "INTELLIGENCE_RAW_RETENTION_AUDIT": ("OH_LYME_DEV_RUNTIME", {"INSERT"}),
    "INTELLIGENCE_SOURCE_VERSIONS": ("OH_LYME_DEV_RUNTIME", {"SELECT"}),
    "INTELLIGENCE_FEED_V": ("OH_LYME_DEV_READ", {"SELECT"}),
    "INTELLIGENCE_FEED_V2": ("OH_LYME_DEV_READ", {"SELECT"}),
}


def value(row: dict[str, Any], key: str) -> Any:
    return next((item for name, item in row.items() if name.lower() == key.lower()), None)


def table_matches(name: str, columns: list[dict[str, Any]]) -> bool:
    actual = []
    for row in columns:
        fields = {key.lower(): item for key, item in row.items()}
        required = {"name", "type", "null?", "default", "kind"}
        if not required <= fields.keys():
            return False
        column = fields["name"]
        type_name = fields["type"]
        nullable = fields["null?"]
        default = fields["default"]
        if (
            fields["kind"] != "COLUMN"
            or not isinstance(column, str)
            or not isinstance(type_name, str)
            or not type_name
            or nullable not in ("Y", "N")
            or (default is not None and not isinstance(default, str))
        ):
            return False
        # Snowflake preserves quoted identifier case. Only exact approved names
        # are reusable; lower-case quoted columns are different identifiers.
        # An explicitly returned NULL default means no default. A missing key
        # is unknown metadata and must never be treated as that NULL.
        actual.append(
            (
                column,
                type_name.upper().replace(" ", ""),
                nullable == "Y",
                (default or "").upper().replace(" ", ""),
            )
        )
    return tuple(actual) == TABLE_SHAPES[name]


def privileges_match(name: str, grants: list[dict[str, Any]]) -> dict[str, bool]:
    role, expected = ROLE_PRIVILEGES[name]
    scoped = [
        row
        for row in grants
        if value(row, "grantee_name") == role and value(row, "granted_to") == "ROLE"
    ]
    actual = {str(value(row, "privilege")).upper() for row in scoped}
    options = [value(row, "grant_option") for row in scoped]
    metadata_valid = all(
        option in ("true", "false", True, False) and type(option) in (str, bool)
        for option in options
    )
    return {
        "required_privileges_present": metadata_valid and expected <= actual,
        "target_role_privileges_exact": metadata_valid and actual == expected,
        "unexpected_target_role_privileges": bool(actual - expected),
        "grant_option_metadata_valid": metadata_valid,
        "target_role_grant_option_present": not metadata_valid
        or any(option in ("true", True) for option in options),
    }


def view_matches(name: str, actual: str) -> bool:
    source = (
        Path(__file__).parents[1] / "docs/contracts/intelligence/v2/presentation-projection.sql"
    ).read_text()
    proposals = re.split(r"(?=CREATE (?:OR REPLACE )?VIEW\b)", source)[1:]
    proposal = next(
        part
        for part in proposals
        if re.match(
            r"CREATE (?:OR REPLACE )?VIEW (?:IF NOT EXISTS )?PRESENTATION\." + name + r"\b", part
        )
    )
    proposal = proposal.split(";", 1)[0]

    def tokens(ddl: str) -> list[str]:
        ddl = re.sub(r"--[^\n]*", "", ddl)
        body = re.split(r"\bAS\s+SELECT\b", ddl, maxsplit=1, flags=re.I)[1]
        # Conservative exact token equivalence. Formatting/case of unquoted SQL
        # may vary; literals remain exact. Any qualification/quoting mismatch
        # requires review rather than automatically replacing a live object.
        return [
            part if part.startswith("'") else part.upper()
            for part in re.findall(r"'(?:''|[^'])*'|[A-Za-z_][A-Za-z_0-9]*|[^\s;]", body)
        ]

    return tokens(actual) == tokens(proposal)


def inspect(
    cursor: Any, report: dict[str, Any], *, receipts: list[dict[str, Any]] | None = None
) -> None:
    cursor.execute(
        "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=10, "
        "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS=2, ABORT_DETACHED_QUERY=TRUE"
    )
    cursor.execute(
        "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()", timeout=10
    )
    if tuple(cursor.fetchone()) != (USER, ROLE, DEV, WAREHOUSE):
        raise ValueError("FEED_PREFLIGHT_IDENTITY")
    report["identity_matches_expected"] = True
    objects: list[dict[str, Any]] = []
    report["objects"] = objects
    # Preserve critical source evidence before an independent object DESCRIBE
    # denial or timeout. Each source result remains safe incremental evidence.
    if receipts is not None:
        inspect_sources(cursor, report, receipts)
    for kind, schema, name in TARGETS:
        qualified = f"{DEV}.{schema}.{name}"
        cursor.execute(f"SHOW {kind}S LIKE '{name}' IN SCHEMA {DEV}.{schema}", timeout=10)
        catalog = [row for row in rows(cursor) if str(row.get("name", row.get("NAME"))) == name]
        entry: dict[str, Any] = {
            "target": name,
            "kind": kind,
            "state": "VISIBLE" if catalog else "NOT_VISIBLE_NOT_PROOF_OF_ABSENCE",
            "inspection_complete": False,
        }
        objects.append(entry)
        print(json.dumps(report, sort_keys=True), flush=True)
        if catalog:
            owner = catalog[0].get("owner", catalog[0].get("OWNER"))
            entry["owner_matches_expected"] = owner == ROLE
            cursor.execute(f"DESCRIBE {kind} {qualified}", timeout=10)
            columns = rows(cursor)
            entry["columns_inspected"] = bool(columns)
            if kind == "TABLE":
                entry["exact_approved_table_shape_matches"] = table_matches(name, columns)
            print(json.dumps(report, sort_keys=True), flush=True)
            cursor.execute(f"SHOW GRANTS ON {kind} {qualified}", timeout=10)
            grants = rows(cursor)
            entry["grants_inspected"] = bool(grants)
            entry.update(privileges_match(name, grants))
            print(json.dumps(report, sort_keys=True), flush=True)
            # Do not expose names, privileges, definitions, source records or hashes.
            if kind == "VIEW":
                cursor.execute(f"SELECT GET_DDL('VIEW','{qualified}')", timeout=10)
                ddl = cursor.fetchone()[0]
                entry["definition_inspected"] = bool(ddl)
                version = "1.0.0" if name == "INTELLIGENCE_FEED_V" else "2.0.0"
                entry["expected_version_literal_present"] = f"'{version}'" in ddl
                entry["exact_reviewed_definition_matches"] = view_matches(name, ddl)
        entry["inspection_complete"] = True
        print(json.dumps(report, sort_keys=True), flush=True)
    report["writes"] = False
    report["source_registration_authorized"] = False
    report["object_prerequisites_passed"] = all(
        entry.get("owner_matches_expected") is True
        and entry.get("required_privileges_present") is True
        and entry.get("target_role_privileges_exact") is True
        and entry.get("target_role_grant_option_present") is False
        and entry.get(
            "exact_approved_table_shape_matches", entry.get("exact_reviewed_definition_matches")
        )
        is True
        for entry in objects
    )
    report["all_prerequisites_passed"] = report["object_prerequisites_passed"] and report.get(
        "source_prerequisites_passed", False
    )


def terminate(report: dict[str, Any]) -> None:
    # Termination performs no evidence I/O. Progress was emitted as it completed.
    # Even a blocked/broken stdout or artifact filesystem cannot prevent exit.
    os._exit(124)


def main() -> None:
    budget(os.environ.get("FEED_PREFLIGHT_ACCOUNTING_CONFIRMED", "false"))
    report: dict[str, Any] = {"state": "FAILED", "objects": [], "writes": False}

    def expire() -> None:
        terminate(report)

    watchdog = threading.Timer(50, expire)
    watchdog.daemon = True
    watchdog.start()
    try:
        if RECEIPTS.stat().st_size > 1024 * 1024:
            raise ValueError("REVIEWED_RECEIPTS_OVERSIZED")
        receipts = json.loads(
            RECEIPTS.read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_keys
        )["receipts"]
        if not isinstance(receipts, list) or any(
            not isinstance(receipt, dict) for receipt in receipts
        ):
            raise ValueError("REVIEWED_RECEIPTS_INVALID")
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            inspect(cursor, report, receipts=receipts)
        report["state"] = "COMPLETE"
    except Exception:
        report["reason"] = "DIAGNOSTIC_FAILED"
        raise SystemExit("FEED_PREFLIGHT_FAILED") from None
    finally:
        print(json.dumps(report, sort_keys=True), flush=True)
        watchdog.cancel()


if __name__ == "__main__":
    main()
