"""Verify and publish only the preserved ML #104 post-merge PROD batch.

Default is offline verification. --publish requires the reviewed V141 migration,
role bootstrap, and a named PAT connection for OH_LYME_PROD_ML_PUBLISHER.
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
    "county-output.json": "217d52dc72182a4eed38c80b8735b8b1d5925f6a4f72682fdca5a59fa1021b0d",
    "manifest.json": "b175613359549c66db4ab3dae695b89ab30da6662ab2ae7f511e63bd75fc1468",
    "lineage.json": "00bf60edc07e310c0ff9ab1fa38c713a3573ae3f892505b1096b88a426d329e5",
}
BATCH_ID = "tier1-review-priority-5536b5caad95cf47"
OUTPUT_SHA256 = "45e711465c2176b5a5b88f7eb23993a4e824a005f03b45e6abdf6171c81aca12"
RELEASE_ID = "governed-2026-09-18-unknown-coverage"
BUNDLE_SHA256 = "038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026"
SOURCE_COMMIT = "024bbbf74a7da8e54566bd60e8e762d85a51e24f"
FIPS_SHA256 = "4a74ab4f8638b4a02a18b0db4abe9597fc2a6bf364a103314de346338015c690"


def canonical_row(row: dict[str, Any]) -> str:
    """Exactly the ML builder's Python JSON encoding for one sorted-key row."""
    return json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)


def verify_artifacts(directory: Path) -> tuple[dict[str, Any], list[str]]:
    """Fail before any Snowflake call on changed handoff bytes or lineage."""
    status = json.loads((directory / "handoff-status.json").read_text(encoding="utf-8"))
    if status.get("artifact_sha256") != {
        **EXPECTED_FILES,
        "prod-features.csv": "84caef339dd87ad85e2b72be4bddfee6ec40412e803cdf926fc3c3e104b98bf2",
    }:
        raise ValueError("Handoff status does not match approved physical hashes")
    if any(
        status.get(key) != value
        for key, value in {
            "batch_id": BATCH_ID,
            "canonical_digest": OUTPUT_SHA256,
            "source_commit": SOURCE_COMMIT,
            "release_id": RELEASE_ID,
            "bundle_sha256": BUNDLE_SHA256,
            "feature_set_version": "tier1-county-features-v2",
            "model_version": "tier1-statistical-reference-v1",
            "evaluation_version": "tier1-selection-evaluation-v1",
            "tier_policy_version": "tier1-review-percentile-v1",
            "row_count": 3144,
            "fips_set_sha256_sorted_lf_no_trailing_lf": FIPS_SHA256,
        }.items()
    ):
        raise ValueError("Handoff status lineage mismatch")
    tiers = {"HIGH": 315, "MEDIUM": 628, "LOW": 2201}
    sufficiency = {"SUFFICIENT": 651, "INSUFFICIENT": 2493}
    if status.get("tier_counts") != tiers or status.get("sufficiency_counts") != sufficiency:
        raise ValueError("Handoff status counts mismatch")
    for name, expected in status["artifact_sha256"].items():
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
    if (
        manifest.get("schema") != "tier1-persisted-output-v1"
        or manifest.get("tier_counts") != tiers
        or manifest.get("sufficiency_counts") != sufficiency
    ):
        raise ValueError("Manifest output contract mismatch")
    if any(lineage.get(key) != value for key, value in expected.items() if key != "batch_id"):
        raise ValueError("Lineage does not match pinned batch")
    if lineage.get("prediction_batch_version") != BATCH_ID:
        raise ValueError("Lineage batch mismatch")
    for key in (
        "feature_set_version",
        "model_version",
        "evaluation_version",
        "tier_policy_version",
    ):
        if lineage.get(key) != status[key]:
            raise ValueError(f"Lineage {key} mismatch")
    if (
        manifest.get("generated_at_utc") != "2026-10-07T02:14:24Z"
        or lineage.get("generated_at_utc") != "2026-10-07T02:14:24Z"
    ):
        raise ValueError("Generated timestamp mismatch")
    for row in rows:
        if any(
            row.get(key) != status[key]
            for key in (
                "model_version",
                "feature_set_version",
                "evaluation_version",
                "tier_policy_version",
            )
        ):
            raise ValueError("County row version mismatch")
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
    if any(row["evidence_sufficiency"] == "NOT_ESTIMABLE" for row in rows):
        raise ValueError("Unexpected non-estimable row")
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
    ) != ("OH_LYME_PROD_ML_PUBLISHER", "ONE_HEALTH_LYME_GAP_ATLAS_PROD"):
        raise ValueError("Publisher connection has wrong role or database")
    if (
        context[0]["USER_NAME"],
        context[0]["WAREHOUSE_NAME"],
    ) != ("OH_LYME_PROD_TIER1_ML_PUBLISHER_SVC", "OH_LYME_PROD_INGEST_XS_WH"):
        raise ValueError("Publisher connection has wrong service user or warehouse")
    prefix = "ONE_HEALTH_LYME_GAP_ATLAS_PROD.FEATURE_STORE."
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
    parser.add_argument("--connection", help="Named PAT connection for the PROD ML publisher")
    args = parser.parse_args()
    manifest, rows = verify_artifacts(args.artifact_dir)
    print(f"Verified preserved batch {BATCH_ID}: {len(rows)} rows, digest {OUTPUT_SHA256}")
    if args.publish:
        if not args.connection:
            parser.error("--publish requires --connection")
        publish(args.connection, manifest, rows)


if __name__ == "__main__":
    main()
