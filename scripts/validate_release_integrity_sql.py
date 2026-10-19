"""Read-only DEV engine fixtures; no DDL, source admission or activation.

Compiles and executes the actual V158 SELECTs and Tier1 join builder against
inline CTE fixtures. This does not prove installed procedure/grant acceptance.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from lyme_gap_atlas_data.release_completeness import tier1_eligibility_join

ROOT = Path(__file__).resolve().parents[1]
MODELS = ("surveillance-situation-four-state", "surveillance-situation-tick-pathogen")


def literal(value):
    return "'" + value.replace("'", "''") + "'"


def fixtures(case):
    target = "input" if case in {"exact", "zero"} else "target"
    models = " UNION ALL ".join("SELECT " + literal(m) + " AS model_id" for m in MODELS)
    admissions = " UNION ALL ".join(
        f"SELECT '{m}' AS artifact_id,'surveillance-situation-batch' AS batch_id,"
        "'v1' AS batch_version,'v1' AS model_version,'input' AS input_release_id,"
        "'bundle' AS input_bundle_sha256,'target' AS target_release_id,"
        "'bundle' AS target_bundle_sha256"
        for m in (*MODELS, "tier1")
        for _ in range(2 if case == "duplicate" else 1)
    )
    if case not in {"compatible", "duplicate"}:
        admissions = "SELECT * FROM (" + admissions + ") WHERE FALSE"
    pointer = "NULL" if case == "zero" else "'surveillance-situation-batch'"
    return {
        "PRESENTATION.CURRENT_RELEASE_V": (
            f"SELECT '{target}' AS release_id,'bundle' AS bundle_sha256"
        ),
        "FEATURE_STORE.MODEL_RELEASE_COMPATIBILITY": admissions,
        "FEATURE_STORE.SURVEILLANCE_SITUATION_POINTER": f"""
            SELECT 'CURRENT' AS pointer_key,{pointer}::VARCHAR AS batch_id,'v1' AS batch_version
        """,
        "FEATURE_STORE.SURVEILLANCE_SITUATION_BATCHES": """
            SELECT 'surveillance-situation-batch' AS batch_id,'v1' AS batch_version,
            'APPROVED' AS state,'digest' AS county_sha256,'dictionary' AS dictionary_sha256,
            'attempt' AS staging_attempt,'authority' AS data_authorization_id,
            CURRENT_TIMESTAMP() AS activated_at,
            '{"release_id":"input","bundle_sha256":"bundle"}' AS manifest_json,
            '{}' AS approval_json
        """,
        "FEATURE_STORE.SURVEILLANCE_SITUATION_AUTHORIZATIONS": """
            SELECT 'authority' AS decision_id,'digest' AS county_sha256,
            'input' AS release_id,'bundle' AS bundle_sha256,'owner-fixture' AS approved_by,
            CURRENT_TIMESTAMP() AS approved_at,'fixture-only' AS approval_reference,
            'commit' AS reviewed_code_commit,'image' AS dev_image_digest
        """,
        "FEATURE_STORE.COUNTY_SURVEILLANCE_SITUATIONS": """
            SELECT 'surveillance-situation-batch' AS batch_id,'v1' AS batch_version,
            model_id,'v1' AS model_version,'00001' AS county_fips,'00' AS state_code,
            1 AS population,'class' AS class_id,PARSE_JSON('[]') AS probabilities FROM (
        """
        + models
        + ")",
        "FEATURE_STORE.SURVEILLANCE_SITUATION_CLASSES": """
            SELECT 'surveillance-situation-batch' AS batch_id,'v1' AS batch_version,model_id,
            'class' AS class_id,PARSE_JSON('{}') AS class_metadata FROM (
        """
        + models
        + ")",
        "PRESENTATION.SEMANTIC_DATA_SOURCES": """
            SELECT 'input' AS release_id,'human' AS source_key,'source' AS source_id,
            'dataset' AS dataset_id,'vintage' AS vintage,'https://example.org' AS source_url,
            'limitations' AS note
        """,
        "PRESENTATION.CURRENT_COUNTY_ATLAS_V": "SELECT '00001' AS fips",
        "PRESENTATION.CURRENT_TIER1_COUNTY_REVIEW_V": """
            SELECT 'input' AS release_id,'bundle' AS bundle_sha256,
            'surveillance-situation-batch' AS prediction_batch_version,
            'v1' AS model_version,'00001' AS county_fips
        """,
    }


def statements(case):
    sql = (ROOT / "migrations/V158__surveillance_situation_publication.sql").read_text()
    current = sql.split(
        ("CREATE OR REPLACE VIEW PRESENTATION.CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V AS\n"), 1
    )[1].split(";\nGRANT", 1)[0]
    availability = sql.split(
        ("CREATE OR REPLACE VIEW PRESENTATION.COUNTY_SURVEILLANCE_SITUATION_AVAILABILITY_V AS\n"), 1
    )[1].split(";\nGRANT", 1)[0]
    tables = fixtures(case)
    if case == "zero":
        tables["PRESENTATION.CURRENT_TIER1_COUNTY_REVIEW_V"] += " WHERE FALSE"
    # Tier1 batch_version must match prediction_batch_version in real data.
    tier = (
        "SELECT COUNT(*) AS N FROM PRESENTATION.CURRENT_TIER1_COUNTY_REVIEW_V v"
        + tier1_eligibility_join()
        + (
            " WHERE (v.release_id=r_current.release_id AND v.bundle_"
            "sha256=r_current.bundle_sha256) OR admission.artifact_i"
            "d IS NOT NULL"
        )
    )
    tables["PRESENTATION.MODEL_RELEASE_COMPATIBILITY_V"] = tables[
        "FEATURE_STORE.MODEL_RELEASE_COMPATIBILITY"
    ].replace("'v1' AS batch_version", "'surveillance-situation-batch' AS batch_version")
    tables["PRESENTATION.CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V"] = current
    activation = sql.split(
        "if(one(`SELECT COUNT(*) FROM FEATURE_STORE.SURVEILLANCE_SITUATION_BATCHES b", 1
    )[1].split("`)!==1)throw 'NO_COMPATIBLE_APPROVED_BATCH'", 1)[0]
    activation = (
        "SELECT COUNT(*) AS N FROM FEATURE_STORE.SURVEILLANCE_SITUATION_BATCHES b" + activation
    )
    names = {name: "fixture_" + str(i) for i, name in enumerate(tables)}

    def replace(query):
        for name in sorted(names, key=len, reverse=True):
            query = query.replace(name, names[name])
        return query

    ctes = ",\n".join(names[name] + " AS (" + replace(body) + ")" for name, body in tables.items())
    prefix = "WITH " + ctes + "\n"
    return {
        "situations": prefix
        + "SELECT COUNT(*) AS N FROM "
        + names["PRESENTATION.CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V"],
        "availability": prefix
        + "SELECT COUNT(*) AS N,COUNT_IF(availability='AVAILABLE') AS AVAILABLE FROM ("
        + replace(availability)
        + ")",
        "tier1": prefix + replace(tier),
        "activation": prefix + replace(activation),
    }


def execute(connection, sql):
    process = subprocess.run(
        ["snow", "sql", "-c", connection, "--format", "JSON", "-q", sql],
        capture_output=True,
        text=True,
    )
    if process.returncode:
        raise RuntimeError("DEV SQL failed: " + process.stderr)
    return json.loads(process.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection", default="ATLAS_DEV_READ")
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--query", choices=("situations", "availability", "tier1", "activation"))
    parser.add_argument(
        "--case", choices=("exact", "compatible", "duplicate", "incompatible", "zero")
    )
    args = parser.parse_args()
    context = execute(
        args.connection,
        (
            "SELECT CURRENT_USER() AS U,CURRENT_ROLE() AS R,CURRENT_"
            "DATABASE() AS D,CURRENT_WAREHOUSE() AS W"
        ),
    )[0]
    if (context["R"], context["D"], context["W"]) != (
        "OH_LYME_DEV_READ",
        "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
        "OH_LYME_DEV_INGEST_XS_WH",
    ):
        raise ValueError("Named isolated DEV READ context required")
    receipt = {
        "observed_at": datetime.now(UTC).isoformat(),
        "kind": "read_only_inline_engine_fixtures_not_installed_acceptance",
        "context": context,
        "cases": [],
    }
    for case in ("exact", "compatible", "duplicate", "incompatible", "zero"):
        if args.case and case != args.case:
            continue
        for name, sql in statements(case).items():
            if args.query and name != args.query:
                continue
            result = execute(
                args.connection,
                (
                    "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=30,QUERY"
                    "_TAG='DATA706_INLINE_DEV_SQL'; "
                )
                + sql
                + "; SELECT LAST_QUERY_ID() AS QUERY_ID",
            )
            actual = result[-2][0]
            expected = 2 if name != "tier1" else 1
            if name == "activation":
                expected = 0 if case == "incompatible" else 1
            if name in {"tier1", "situations"} and case in {"incompatible", "zero"}:
                expected = 0
            if actual["N"] != expected:
                raise ValueError(f"{case}/{name} unexpected count {actual}")
            if name == "availability" and actual["AVAILABLE"] != (
                0 if case in {"incompatible", "zero"} else 2
            ):
                raise ValueError("Availability mismatch")
            receipt["cases"].append(
                {
                    "case": case,
                    "query": name,
                    "result": actual,
                    "query_id": result[-1][0]["QUERY_ID"],
                }
            )
            args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"passed": len(receipt["cases"]), "receipt": str(args.receipt)}))


if __name__ == "__main__":
    main()
