"""Freeze the native PROD January capture through existing release/projection code."""
# ruff: noqa: E501

import json
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import climate_prod_binding as binding
from .climate_publication import NOAA_SHA, RESOURCE_KEY, TIGER_SHA, project_verified_partitions
from .climate_release import (
    ROW_COUNT,
    canonical_partitions,
    read_capture_membership,
    validate_extension,
    verify_extension,
)
from .semantic_metadata import metadata_revision_id

PLANNED_RUN = "d0e1e30b-49f1-5400-8345-af0b3e975114"
BASE_RELEASE = "governed-2026-10-06-nlcd-demo-cohort"
BASE_BUNDLE = "603afb135a1a5c958d1d56d48d580d9942c67eb38986caf8b4b3acf69fcde2c9"
RELEASE = "governed-2026-10-15-january-climate-prod"
SPEC = {
    "contract_version": "atlas-january-climate-prod-release-input-v1",
    "release_id": RELEASE,
    "annual_release_id": BASE_RELEASE,
    "annual_bundle_sha256": BASE_BUNDLE,
    "ingestion_run_id": PLANNED_RUN,
    "row_count": ROW_COUNT,
}


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def require_schema(cursor: Any) -> None:
    """Verify the climate pair and leave unrelated intelligence V150 pending."""
    from .migrations import load_migrations, migration_plan

    binding.verify_execution_resource(
        cursor, "OH_LYME_PROD_MIGRATION_DEPLOYER", "OH_LYME_PROD_MIGRATION_DEPLOY_SVC"
    )
    cursor.execute("SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE()")
    require(
        cursor.fetchone()
        == ("OH_LYME_PROD_MIGRATION_DEPLOY_SVC", "OH_LYME_PROD_MIGRATION_DEPLOYER", binding.PROD),
        "JANUARY_PROD_IDENTITY",
    )
    cursor.execute(
        "SELECT version,filename,sha256 FROM GOVERNANCE.SCHEMA_MIGRATIONS ORDER BY version LIMIT 201"
    )
    rows = cursor.fetchall()
    require(len(rows) < 201, "JANUARY_LEDGER_LIMIT")
    canonical = {item.version: item for item in load_migrations()}
    for version in ("V151", "V152"):
        require(
            [row for row in rows if row[0] == version]
            == [(version, canonical[version].filename, canonical[version].sha256)],
            "JANUARY_PROD_SCHEMA",
        )
    applied = {row[0] for row in rows}
    pending = {item["version"] for item in migration_plan(binding.PROD)} - applied
    require(pending <= {"V150"}, "JANUARY_UNEXPECTED_PENDING_MIGRATION")


def prepare(
    cursor: Any, spec: dict[str, Any], packet: dict[str, Any], review: dict[str, str]
) -> dict[str, Any]:
    """Read only; newly generated IDs come from PROD ledgers, never DEV substitution."""
    require(spec == SPEC, "JANUARY_PROD_SPEC")
    cursor.execute("SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE()")
    require(
        cursor.fetchone()
        == ("OH_LYME_PROD_MIGRATION_DEPLOY_SVC", "OH_LYME_PROD_MIGRATION_DEPLOYER", binding.PROD),
        "JANUARY_PROD_IDENTITY",
    )
    cursor.execute(
        "SELECT r.status,r.bundle_sha256,r.source_manifest FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p JOIN PRESENTATION.SEMANTIC_RELEASES r ON r.release_id=p.current_release_id WHERE p.pointer_key='ATLAS' AND r.release_id=%s",
        (BASE_RELEASE,),
    )
    rows = cursor.fetchall()
    require(len(rows) == 1 and rows[0][:2] == ("PUBLISHED", BASE_BUNDLE), "JANUARY_PROD_BASELINE")
    annual = json.loads(rows[0][2]) if isinstance(rows[0][2], str) else rows[0][2]
    # Validate the complete existing release, including its accepted NLCD extension.
    # The older DEV donor exporter intentionally accepts only five annual slots.
    from .semantic_release import load_manifest

    with tempfile.TemporaryDirectory(prefix="january-prod-base-") as directory:
        path = Path(directory) / "base.json"
        path.write_text(json.dumps(annual), encoding="utf-8")
        baseline = load_manifest(path)
    require(
        baseline.release_id == BASE_RELEASE
        and "nlcd_extension" in annual
        and "climate_extension" not in annual,
        "JANUARY_PROD_BASELINE_CONTRACT",
    )
    cursor.execute(
        "SELECT artifact_id,sha256,byte_count FROM GOVERNANCE.RAW_ARTIFACTS WHERE ingestion_run_id=%s ORDER BY sha256",
        (PLANNED_RUN,),
    )
    artifacts = cursor.fetchall()
    require(
        len(artifacts) == 2 and {row[1] for row in artifacts} == {NOAA_SHA, TIGER_SHA},
        "JANUARY_PROD_CAPTURE_ARTIFACTS",
    )
    by_hash = {row[1]: row[0] for row in artifacts}
    require(
        {row[1]: row[2] for row in artifacts} == {NOAA_SHA: 61013299, TIGER_SHA: 83989800},
        "JANUARY_PROD_CAPTURE_BYTES",
    )
    sources, evidence = {}, {}
    for key, resource, checksum in (
        ("noaa", RESOURCE_KEY, NOAA_SHA),
        ("tiger", "census_tiger_2025_us_county_analysis", TIGER_SHA),
    ):
        cursor.execute(
            "SELECT v.data_source_version_id,v.ingestion_run_id,v.artifact_id FROM GOVERNANCE.DATA_SOURCE_VERSIONS v JOIN GOVERNANCE.RAW_ARTIFACTS a ON a.artifact_id=v.artifact_id AND a.ingestion_run_id=v.ingestion_run_id WHERE v.resource_key=%s AND v.status='CONDITIONAL' AND v.retired_at IS NULL AND v.approved_decision_id IS NOT NULL AND a.sha256=%s",
            (resource, checksum),
        )
        versions = cursor.fetchall()
        require(len(versions) == 1, "JANUARY_PROD_ACTIVE_SOURCE")
        version, evidence_run, evidence_artifact = versions[0]
        sources[key] = {
            "source_version_id": version,
            "resource_key": resource,
            "artifact_id": by_hash[checksum],
            "sha256": checksum,
        }
        evidence[key] = {"ingestion_run_id": evidence_run, "artifact_id": evidence_artifact}
    ids, digest = read_capture_membership(
        cursor, run_id=PLANNED_RUN, noaa_artifact_id=by_hash[NOAA_SHA]
    )
    metadata = deepcopy(packet["metadata_candidates"])
    for item in metadata:
        item["provenance"]["source_version_id"] = {
            "state": "KNOWN",
            "value": sources["noaa"]["source_version_id"],
        }
        item["metadata_revision"] = 3
        item["revision_id"] = metadata_revision_id(item)
    with tempfile.TemporaryDirectory(prefix="january-prod-freeze-") as directory:
        candidate = project_verified_partitions(
            cursor,
            canonical_partitions(cursor, run_id=PLANNED_RUN),
            Path(directory) / "candidate.ndjson",
            run_id=PLANNED_RUN,
            noaa_artifact_id=by_hash[NOAA_SHA],
        )
    extension = {
        "contract_version": binding.CONTRACT,
        "target_environment": "prod",
        "source_evidence": evidence,
        "period": "2025-01-01/2025-01-31",
        "ingestion_run_id": PLANNED_RUN,
        "candidate_sha256": candidate["projection_sha256"],
        "capture_membership_sha256": digest,
        "row_count": ROW_COUNT,
        "capture_ids": ids,
        "sources": sources,
        "metadata": metadata,
        "review_evidence": review,
    }
    validate_extension(extension)
    verify_extension(cursor, extension, database=binding.PROD)
    result = dict(annual)
    result.update(
        release_id=RELEASE,
        schema_version="2.0.0",
        methodology_version="semantic-2.0.0",
        generated_at=datetime.now(UTC).isoformat(),
        climate_extension=extension,
    )
    return result


def verify_published(cursor: Any) -> dict[str, Any]:
    """Bounded real observations under the protected Data identity, not API proof."""
    from .climate_inspection import statements

    binding.verify_execution_resource(
        cursor, "OH_LYME_PROD_MIGRATION_DEPLOYER", "OH_LYME_PROD_MIGRATION_DEPLOY_SVC"
    )
    checks = []
    observed_revisions: dict[str, set[str]] = {}
    for index, sql in enumerate(statements("dev")[2:], 1):
        sql = sql.replace("ONE_HEALTH_LYME_GAP_ATLAS_DEV", binding.PROD).replace(
            "governed-2026-10-09-january-climate-dev", RELEASE
        )
        cursor.execute(sql)
        names = [str(column[0]).lower() for column in cursor.description]
        rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        if index == 1:
            require(len(rows) == 8, "JANUARY_PROD_READBACK_COUNT")
            expected = {
                "prcp": 0.0,
                "tmin": -1.992294192037333,
                "tmax": 16.29939307942125,
                "tavg": 7.153611977327104,
            }
            require(
                {(r["county_fips"], r["measure_id"]) for r in rows}
                == {
                    (county, f"nclimgrid_{key}_county_day")
                    for county in ("48277", "02013")
                    for key in expected
                },
                "JANUARY_PROD_READBACK_KEYS",
            )
            for row in rows:
                observed_revisions.setdefault(row["measure_id"], set()).add(
                    row["metadata_revision_id"]
                )
                key = row["measure_id"].split("_")[1]
                require(
                    row["release_id"] == RELEASE
                    and str(row["period_start"]) == "2025-01-17"
                    and str(row["period_end"]) == "2025-01-17",
                    "JANUARY_PROD_READBACK_PERIOD",
                )
                require(
                    row["unit"] == ("mm" if key == "prcp" else "degree_Celsius"),
                    "JANUARY_PROD_READBACK_UNIT",
                )
                if row["county_fips"] == "48277":
                    require(
                        row["coverage_status"] == "COMPLETE"
                        and row["value_state"] == ("ZERO" if key == "prcp" else "OBSERVED")
                        and abs(float(row["value"]) - expected[key]) <= 1e-12,
                        "JANUARY_PROD_READBACK_VALUE",
                    )
                else:
                    require(
                        row["value"] is None
                        and row["coverage_status"] == "OUT_OF_SOURCE_COVERAGE"
                        and row["value_state"] == "UNAVAILABLE",
                        "JANUARY_PROD_READBACK_COVERAGE",
                    )
                require(
                    row["source_published_at"] is None
                    and row["metadata_revision_id"]
                    and row["atlas_acquired_at"] is not None,
                    "JANUARY_PROD_READBACK_PROVENANCE",
                )
        elif index == 2:
            require(
                len(rows) == 4
                and {r["measure_id"] for r in rows}
                == {f"nclimgrid_{key}_county_day" for key in ("prcp", "tmin", "tmax", "tavg")},
                "JANUARY_PROD_READBACK_METADATA",
            )
            require(
                all(
                    r["release_id"] == RELEASE
                    and observed_revisions.get(r["measure_id"]) == {r["metadata_revision_id"]}
                    and r["unit"] == ("mm" if "_prcp_" in r["measure_id"] else "degree_Celsius")
                    for r in rows
                ),
                "JANUARY_PROD_READBACK_METADATA_BINDING",
            )
        else:
            require(
                len(rows) == 1
                and rows[0]["status"] == "PUBLISHED"
                and rows[0]["climate_run"] == PLANNED_RUN,
                "JANUARY_PROD_READBACK_RELEASE",
            )
        checks.append({"ordinal": index, "query_id": getattr(cursor, "sfqid", None), "rows": rows})
    return {
        "status": "PASS",
        "reader_evidence": "PROTECTED_DATA_IDENTITY_ONLY",
        "actual_api_service_read": "UNVERIFIED",
        "checks": checks,
    }


def main() -> None:
    import argparse

    from lyme_gap_atlas_shared.settings import SnowflakeSettings

    from .sql_sessions import connect

    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-published", action="store_true", required=True)
    parser.parse_args()
    try:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            result = verify_published(cursor)
        print(json.dumps(result, default=str), flush=True)
    except Exception:
        raise SystemExit("JANUARY_PROD_READBACK_BLOCKED_NO_RETRY") from None


if __name__ == "__main__":
    main()
