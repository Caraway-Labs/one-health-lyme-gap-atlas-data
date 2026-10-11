"""Verify and publish only the preserved ML #32 post-merge DEV batch.

Default is offline verification. --publish requires the reviewed V140 migration,
role bootstrap, and a named PAT connection for OH_LYME_DEV_ML_PUBLISHER.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

EXPECTED_FILES = {
    "county-output.json": "944e5dcff37ffd5b8c0883f9f68e1dd4da6aba97cd2c1a76e55b85ccf48b3844",
    "manifest.json": "8b04d9cad4ddfa14eb1f655c73cee0ad10388764b361a4ad2b8a26754093b77c",
    "lineage.json": "7997c262cfca6611b24071473382fb296c33e6abb239f02fba42337cc8bfab90",
}
BATCH_ID = "tier1-review-priority-744b2933bae43718"
OUTPUT_SHA256 = "3c05f9d6e0a150c29be3bcc6a0c20233cc8f1171dd0ec91ad82c8f68e1c35b41"
RELEASE_ID = "governed-2026-09-17-unknown-coverage"
BUNDLE_SHA256 = "55192e53b0b046cfe5148c13ffe5c570f615ec233e2b5c1103247f00b1a51233"
SOURCE_COMMIT = "c6bb8a0f48ede70f332513c1b5843f35988949f1"
FIPS_SHA256 = "4a74ab4f8638b4a02a18b0db4abe9597fc2a6bf364a103314de346338015c690"


def canonical_row(row: dict[str, Any]) -> str:
    """Exactly the ML builder's Python JSON encoding for one sorted-key row."""
    return json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)


def verify_artifacts(directory: Path) -> tuple[dict[str, Any], list[str]]:
    """Fail before any Snowflake call on changed handoff bytes or lineage."""
    for name, expected in EXPECTED_FILES.items():
        actual = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Preserved {name} checksum mismatch")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    lineage = json.loads((directory / "lineage.json").read_text(encoding="utf-8"))
    rows = json.loads((directory / "county-output.json").read_text(encoding="utf-8"))
    if not isinstance(rows, list) or len(rows) != 3144:
        raise ValueError("Wrong county row count")
    fips = [row["county_fips"] for row in rows]
    if fips != sorted(set(fips)):
        raise ValueError("County rows must be strictly FIPS sorted")
    if hashlib.sha256("\n".join(fips).encode()).hexdigest() != FIPS_SHA256:
        raise ValueError("Wrong county FIPS set")
    expected = {
        "batch_id": BATCH_ID,
        "output_sha256": OUTPUT_SHA256,
        "release_id": RELEASE_ID,
        "bundle_sha256": BUNDLE_SHA256,
        "source_commit": SOURCE_COMMIT,
        "row_count": 3144,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("Manifest does not match pinned batch")
    if any(lineage.get(key) != value for key, value in expected.items() if key != "batch_id"):
        raise ValueError("Lineage does not match pinned batch")
    if lineage.get("prediction_batch_version") != BATCH_ID:
        raise ValueError("Lineage batch mismatch")
    if Counter(row["priority_tier"] for row in rows) != {
        "HIGH": 315,
        "MEDIUM": 628,
        "LOW": 2201,
    }:
        raise ValueError("Tier count drift")
    if Counter(row["evidence_sufficiency"] for row in rows) != {
        "SUFFICIENT": 651,
        "INSUFFICIENT": 2493,
    }:
        raise ValueError("Evidence sufficiency drift")
    serialized = [canonical_row(row) for row in rows]
    computed = hashlib.sha256(("[" + ",".join(serialized) + "]").encode()).hexdigest()
    if computed != OUTPUT_SHA256:
        raise ValueError("Canonical output digest mismatch")
    return manifest, serialized


def sql_literal(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def snow_query(connection: str, sql: str) -> list[dict[str, Any]]:
    """Use the installed CLI; the private temporary SQL file is removed on exit."""
    with tempfile.TemporaryDirectory(prefix="atlas-tier1-") as temporary:
        query_path = Path(temporary) / "query.sql"
        query_path.write_text(sql + "\n", encoding="utf-8")
        result = subprocess.run(
            ["snow", "sql", "-c", connection, "--format", "JSON", "-f", str(query_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    return json.loads(result.stdout)


def procedure_state(result: list[dict[str, Any]]) -> str:
    """Normalize the CLI's one-cell VARIANT procedure response."""
    if len(result) != 1 or len(result[0]) != 1:
        raise ValueError("Unexpected publication procedure response")
    value = next(iter(result[0].values()))
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("Unexpected publication procedure response")
    state = value.get("state", value.get("STATE"))
    if state not in {"STAGING", "APPROVED"}:
        raise ValueError("Unexpected publication state")
    return str(state)


def publish(connection: str, manifest: dict[str, Any], rows: list[str]) -> None:
    context = snow_query(
        connection,
        "SELECT CURRENT_USER() AS USER_NAME, CURRENT_ROLE() AS ROLE_NAME, "
        "CURRENT_DATABASE() AS DATABASE_NAME, CURRENT_WAREHOUSE() AS WAREHOUSE_NAME",
    )
    if len(context) != 1 or (
        context[0]["ROLE_NAME"],
        context[0]["DATABASE_NAME"],
    ) != ("OH_LYME_DEV_ML_PUBLISHER", "ONE_HEALTH_LYME_GAP_ATLAS_DEV"):
        raise ValueError("Publisher connection has wrong role or database")
    if not context[0]["USER_NAME"] or not context[0]["WAREHOUSE_NAME"]:
        raise ValueError("Publisher connection lacks user or warehouse")
    prefix = "ONE_HEALTH_LYME_GAP_ATLAS_DEV.FEATURE_STORE."
    begin_result = snow_query(
        connection,
        "CALL " + prefix + "SP_BEGIN_TIER1_REVIEW_BATCH(" + sql_literal(json.dumps(manifest)) + ")",
    )
    if procedure_state(begin_result) == "STAGING":
        for start in range(0, len(rows), 200):
            chunk = json.dumps(rows[start : start + 200], separators=(",", ":"))
            snow_query(
                connection,
                "CALL "
                + prefix
                + "SP_STAGE_TIER1_REVIEW_ROWS("
                + sql_literal(BATCH_ID)
                + ","
                + sql_literal(chunk)
                + ")",
            )
    result = snow_query(
        connection,
        "CALL "
        + prefix
        + "SP_FINALIZE_TIER1_REVIEW_BATCH("
        + sql_literal(BATCH_ID)
        + ","
        + sql_literal(OUTPUT_SHA256)
        + ")",
    )
    print(json.dumps(result, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--connection", help="Named PAT connection for the DEV ML publisher")
    args = parser.parse_args()
    manifest, rows = verify_artifacts(args.artifact_dir)
    print(f"Verified preserved batch {BATCH_ID}: {len(rows)} rows, digest {OUTPUT_SHA256}")
    if args.publish:
        if not args.connection:
            parser.error("--publish requires --connection")
        publish(args.connection, manifest, rows)


if __name__ == "__main__":
    main()
