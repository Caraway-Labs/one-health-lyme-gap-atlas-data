"""Stage one synthetic #169 result under the DEV runtime identity only."""

from __future__ import annotations

import json
from pathlib import Path

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from lyme_gap_atlas_data.infected_tick_metrics import DENSITY, calculate_infected_tick_metric
from lyme_gap_atlas_data.infected_tick_result_store import stage_infected_tick_result

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
        raise SystemExit("#169 fixture verification requires the DEV runtime role and database")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = calculate_infected_tick_metric(DENSITY, [fixture])
    if result["state"] != "NUMERIC":
        raise SystemExit("synthetic M2 fixture did not calculate")
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
        result_id, first = stage_infected_tick_result(
            cursor, result, evidence_basis="SYNTHETIC_FIXTURE"
        )
        replay_id, replay = stage_infected_tick_result(
            cursor, result, evidence_basis="SYNTHETIC_FIXTURE"
        )
        if (replay_id, replay) != (result_id, "IDENTICAL_REPLAY"):
            raise SystemExit("immutable replay check failed")
        cursor.execute(
            """SELECT COUNT(*), COUNT_IF(safe_payload:state::VARCHAR='NUMERIC'),
                      COUNT_IF(safe_payload:county_relationship:representativeness::VARCHAR
                               ='NOT_COUNTY_REPRESENTATIVE')
               FROM ANALYTICS.INFECTED_TICK_DERIVED_RESULTS WHERE result_id=%s""",
            (result_id,),
        )
        if tuple(cursor.fetchone()) != (1, 1, 1):
            raise SystemExit("DEV persisted result read-back failed")
    print(
        json.dumps(
            {
                "result_id": result_id,
                "first_write": first,
                "replay": replay,
                "fixture_only": True,
                "source_backed_current_code_replay": "EVIDENCE_LIMITED",
                "dev_runtime_readback": "PASS",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
