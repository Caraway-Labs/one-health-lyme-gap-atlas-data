"""Compare frozen ML104 features with current PROD through named read-only PAT.

No model inference, output publication, retagging or approval. Per-county source
rows stay in memory; only the aggregate comparison receipt may be saved.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

FEATURE_SHA = "84caef339dd87ad85e2b72be4bddfee6ec40412e803cdf926fc3c3e104b98bf2"
ML_COMMIT = "024bbbf74a7da8e54566bd60e8e762d85a51e24f"
TARGET = "governed-2026-10-15-january-climate-prod"
BUNDLE = "53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d"


def query(connection: str, sql: str):
    statement = (
        "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=60,"
        "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS=10,"
        "QUERY_TAG='DATA698_COMPATIBILITY_READ_ONLY'; " + sql
    )
    result = subprocess.run(
        [
            "snow",
            "sql",
            "-c",
            connection,
            "--warehouse",
            "COMPUTE_WH",
            "--format",
            "JSON",
            "-q",
            statement,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ValueError("Read-only feature capture failed; no compatibility conclusion")
    return json.loads(result.stdout)[-1]


def compare(current: list[dict], original: list[dict], predictors: tuple[str, ...]) -> dict:
    old = {r["county_fips"]: r for r in original}
    new = {r["county_fips"]: r for r in current}
    if (
        len(old) != 3144
        or len(new) != 3144
        or len(original) != 3144
        or len(current) != 3144
        or old.keys() != new.keys()
    ):
        raise ValueError("Canonical county membership differs")
    numeric = (*predictors, "rucc_2023_context")
    evidence = (
        "human_evidence_state",
        "pathogen_evidence_state",
        "vector_evidence_state",
        "feature_evidence_state",
        "feature_set_version",
    )
    changes = {
        name: sum(float(old[fips][name]) != float(new[fips][name]) for fips in old)
        for name in numeric
    }
    changes.update(
        {name: sum(old[fips][name] != new[fips][name] for fips in old) for name in evidence}
    )
    return {
        "county_count": 3144,
        "predictor_cells_compared": 3144 * len(predictors),
        "changed_cells_by_field": changes,
        "model_input_equality": not any(changes.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ml-root", type=Path, required=True)
    parser.add_argument("--original-features", type=Path, required=True)
    parser.add_argument("--connection", default="ATLAS_PROD_READ")
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if hashlib.sha256(args.original_features.read_bytes()).hexdigest() != FEATURE_SHA:
        raise ValueError("Preserved ML104 feature capture checksum differs")
    relative = "src/lyme_gap_atlas_ml/tier1_features.py"
    source = args.ml_root / relative
    frozen = subprocess.run(
        ["git", "-C", str(args.ml_root), "show", f"{ML_COMMIT}:{relative}"],
        check=True,
        capture_output=True,
    ).stdout
    if source.read_bytes().replace(b"\r\n", b"\n") != frozen:
        raise ValueError("Feature projection differs from the approved original ML code")
    spec = importlib.util.spec_from_file_location("frozen_tier1_features", source)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    context = query(
        args.connection,
        "SELECT CURRENT_USER() AS U,CURRENT_ROLE() AS R,"
        "CURRENT_DATABASE() AS D,CURRENT_WAREHOUSE() AS W",
    )
    if len(context) != 1 or (context[0]["R"], context[0]["D"], context[0]["W"]) != (
        "OH_LYME_PROD_READ",
        "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        "COMPUTE_WH",
    ):
        raise ValueError("Expected named read-only PROD context")
    metadata_sql = "SELECT release_id,bundle_sha256 FROM PRESENTATION.CURRENT_RELEASE_V"
    before = query(args.connection, metadata_sql)
    if before != [{"RELEASE_ID": TARGET, "BUNDLE_SHA256": BUNDLE}]:
        raise ValueError("Current PROD release differs from requested comparison")
    sql = (
        "SELECT RELEASE_ID,FIPS,HUMAN_STATUS,CASE_COUNT_FLOOR_2023,TICK_STATUS,"
        "SCAPULARIS_STATUS,PACIFICUS_STATUS,BURGDORFERI_STATUS,SVI_PERCENTILE,RUCC_2023 "
        "FROM PRESENTATION.CURRENT_COUNTY_ATLAS_V ORDER BY FIPS"
    )
    rows = query(args.connection, sql)
    if (
        any(r["RELEASE_ID"] != TARGET for r in rows)
        or query(args.connection, metadata_sql) != before
    ):
        raise ValueError("Release changed during comparison")
    snapshot = replace(module.SNAPSHOTS["prod"], release_id=TARGET, bundle_sha256=BUNDLE)
    current, _ = module.build_matrix(rows, snapshot)
    with args.original_features.open(newline="", encoding="utf-8") as stream:
        original = list(csv.DictReader(stream))
    receipt = compare(current, original, module.FEATURE_COLUMNS)
    receipt.update(
        schema="atlas-tier1-release-input-comparison/v1",
        observed_at=datetime.now(UTC).isoformat(),
        identity=context[0],
        original_feature_sha256=FEATURE_SHA,
        projection_source_commit=ML_COMMIT,
        input_release_id=module.SNAPSHOTS["prod"].release_id,
        input_bundle_sha256=module.SNAPSHOTS["prod"].bundle_sha256,
        target_release_id=TARGET,
        target_bundle_sha256=BUNDLE,
        approval_state="not_an_approval",
        predictions_regenerated=False,
        source_lineage_admission="owner procedure must independently verify source lineage",
    )
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
