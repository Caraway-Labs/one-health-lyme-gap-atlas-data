"""Stage one synthetic #172 result under the existing DEV runtime identity."""

from __future__ import annotations

import json
from pathlib import Path

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from lyme_gap_atlas_data.surveillance_coverage import SAMPLING, evaluate_surveillance_coverage
from lyme_gap_atlas_data.surveillance_coverage_results import serialize_surveillance_coverage
from lyme_gap_atlas_data.surveillance_priority import evaluate_surveillance_priority
from lyme_gap_atlas_data.surveillance_priority_result_store import stage_surveillance_priority

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
    coverage = evaluate_surveillance_coverage(
        SAMPLING,
        [fixture],
        source_context={
            "approved": True,
            "available": True,
            "source_dataset_id": "DP1.10093.001",
            "source_version_id": "RELEASE-2026",
            "source_vintage": "RELEASE-2026",
        },
    )
    safe_coverage = serialize_surveillance_coverage(coverage, evidence_basis="SYNTHETIC_FIXTURE")
    result = evaluate_surveillance_priority(safe_coverage)
    if result["disposition"] != "NO_CURRENT_GAP_SIGNAL":
        raise SystemExit("synthetic #172 sampling fixture did not classify")
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
        result_id, first = stage_surveillance_priority(cursor, result)
        replay_id, replay = stage_surveillance_priority(cursor, result)
        if (replay_id, replay) != (result_id, "IDENTICAL_REPLAY"):
            raise SystemExit("immutable surveillance priority replay failed")
        cursor.execute(
            """SELECT COUNT(*),
                      COUNT_IF(safe_payload:disposition::VARCHAR='NO_CURRENT_GAP_SIGNAL'),
                      COUNT_IF(safe_payload:representativeness::VARCHAR
                               ='NOT_COUNTY_REPRESENTATIVE')
               FROM PRESENTATION.SURVEILLANCE_PRIORITY_DERIVED_RESULTS
               WHERE result_id=%s""",
            (result_id,),
        )
        if tuple(cursor.fetchone()) != (1, 1, 1):
            raise SystemExit("DEV surveillance priority read-back failed")
    print(
        json.dumps(
            {
                "result_id": result_id,
                "first_write": first,
                "replay": replay,
                "fixture_only": True,
                "source_backed_current_code_replay": "NOT_PROVEN",
                "dev_runtime_readback": "PASS",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
