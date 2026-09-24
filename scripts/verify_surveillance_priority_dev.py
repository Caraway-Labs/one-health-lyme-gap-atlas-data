"""Stage bounded resolved and unresolved synthetic #172 DEV results."""

from __future__ import annotations

import json
from pathlib import Path

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from lyme_gap_atlas_data.surveillance_coverage import SAMPLING, evaluate_surveillance_coverage
from lyme_gap_atlas_data.surveillance_coverage_results import serialize_surveillance_coverage
from lyme_gap_atlas_data.surveillance_priority import evaluate_surveillance_priority
from lyme_gap_atlas_data.surveillance_priority_result_store import stage_surveillance_priority
from lyme_gap_atlas_data.surveillance_priority_results import serialize_surveillance_priority

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/tick_surveillance/infected-tick-derived-result-v1-dev-fixture.json"
)


def main() -> None:
    settings = SnowflakeSettings()
    if (
        settings.snowflake_database != "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
        or settings.snowflake_role != "OH_LYME_DEV_RUNTIME"
    ):
        raise SystemExit("#172 fixture verification requires DEV runtime role and database")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source_context = {
        "approved": True,
        "available": True,
        "source_dataset_id": "DP1.10093.001",
        "source_version_id": "RELEASE-2026",
        "source_vintage": "RELEASE-2026",
    }
    unresolved_fixture = {**fixture, "collection_method": "UNKNOWN"}
    results = []
    for observation in (fixture, unresolved_fixture):
        coverage = evaluate_surveillance_coverage(
            SAMPLING, [observation], source_context=source_context
        )
        safe_coverage = serialize_surveillance_coverage(
            coverage, evidence_basis="SYNTHETIC_FIXTURE"
        )
        result = evaluate_surveillance_priority(safe_coverage)
        results.append(result)
    resolved, unresolved = (serialize_surveillance_priority(result) for result in results)
    if (
        resolved["disposition"] != "NO_CURRENT_GAP_SIGNAL"
        or resolved["comparison_cohort_id"] is None
        or resolved["tie_group_id"] is None
        or unresolved["coverage_state"] != "UNKNOWN"
        or unresolved["disposition"] != "EVIDENCE_VERIFICATION"
        or unresolved["comparison_cohort_id"] is not None
        or unresolved["tie_group_id"] is not None
        or "COLLECTION_METHOD_UNRESOLVED" not in unresolved["reason_codes"]
        or "COMPARISON_COHORT_UNPROVEN" not in unresolved["reason_codes"]
        or resolved["result_id"] == unresolved["result_id"]
    ):
        raise SystemExit("synthetic #172 resolved/unresolved method behavior failed")
    with connect(settings) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()"
        )
        user, role, database, warehouse = cursor.fetchone()
        if (user, role, database, warehouse) != (
            "OH_LYME_DEV_PIPELINE_SVC",
            "OH_LYME_DEV_RUNTIME",
            "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            settings.snowflake_warehouse,
        ):
            raise SystemExit("DEV runtime connection preflight failed")
        states = []
        for result, document in zip(results, (resolved, unresolved), strict=True):
            result_id, first = stage_surveillance_priority(cursor, result)
            replay_id, replay = stage_surveillance_priority(cursor, result)
            if (replay_id, replay) != (result_id, "IDENTICAL_REPLAY"):
                raise SystemExit("immutable surveillance priority replay failed")
            cursor.execute(
                """SELECT safe_payload:coverage_state::VARCHAR,
                          safe_payload:disposition::VARCHAR,
                          safe_payload:comparison_cohort_id::VARCHAR,
                          safe_payload:tie_group_id::VARCHAR,
                          safe_payload:collection_method::VARCHAR,
                          safe_payload:representativeness::VARCHAR,
                          ARRAY_CONTAINS('COLLECTION_METHOD_UNRESOLVED'::VARIANT,
                                         safe_payload:reason_codes),
                          ARRAY_CONTAINS('COMPARISON_COHORT_UNPROVEN'::VARIANT,
                                         safe_payload:reason_codes),
                          safe_payload:artifact_uri::VARCHAR,
                          safe_payload:raw_payload::VARCHAR,
                          safe_payload:credential::VARCHAR
                   FROM PRESENTATION.SURVEILLANCE_PRIORITY_DERIVED_RESULTS
                   WHERE result_id=%s""",
                (result_id,),
            )
            rows = cursor.fetchall()
            expected = (
                document["coverage_state"],
                document["disposition"],
                document["comparison_cohort_id"],
                document["tie_group_id"],
                document["collection_method"],
                "NOT_COUNTY_REPRESENTATIVE",
                "COLLECTION_METHOD_UNRESOLVED" in document["reason_codes"],
                "COMPARISON_COHORT_UNPROVEN" in document["reason_codes"],
                None,
                None,
                None,
            )
            if len(rows) != 1 or tuple(rows[0]) != expected:
                raise SystemExit("DEV surveillance priority read-back failed")
            states.append({"result_id": result_id, "first_write": first, "replay": replay})
    print(
        json.dumps(
            {
                "resolved_method": states[0],
                "unresolved_method": states[1],
                "fixture_only": True,
                "source_backed_current_code_replay": "NOT_PROVEN",
                "dev_runtime_readback": "PASS",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
