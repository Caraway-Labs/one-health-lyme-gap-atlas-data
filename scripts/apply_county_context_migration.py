"""Protected V155-only entry point; immutable release and existing grants stay fixed."""

import json
import os
import runpy
from pathlib import Path
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from lyme_gap_atlas_data.migrations import apply_migrations, parse_reviewed_pending_set

ROOT = Path(__file__).parents[1]
VIEW = "PRESENTATION.CURRENT_COUNTY_OBSERVATIONS_V"
RELEASE = "governed-2026-10-15-january-climate-prod"
BUNDLE = "53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d"
LEGACY_COLUMNS = (
    "observation_id,measure_id,geography_id,geography_type,county_fips,period_start,"
    "period_end,temporal_grain,value,value_state,unit,denominator,supported_stratifications,"
    "semantic_contract_version,release_version,source_key,source_label,source_vintage,"
    "source_url,retrieved_at,transformation_version,methodology,release_methodology_version,"
    "observation_limitations,measure_limitation,release_limitations,source_id,dataset_id,"
    "methodology_id"
)


def candidate() -> str:
    sql = (ROOT / "migrations/V155__county_context_consumer_observations.sql").read_text()
    return sql.split("WITH context AS (\n", 1)[1].split("\n), existing AS (", 1)[0]


def snapshot(cursor: Any, *, deployed: bool) -> dict[str, Any]:
    cursor.execute("SELECT RELEASE_ID,BUNDLE_SHA256 FROM PRESENTATION.CURRENT_RELEASE_V LIMIT 2")
    if cursor.fetchall() != [(RELEASE, BUNDLE)]:
        raise ValueError("CONTEXT_RELEASE_BINDING")
    cursor.execute(f"SHOW GRANTS ON VIEW {VIEW}")
    columns = [column[0].lower() for column in cursor.description]
    grants = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    stable_grants = sorted(
        (g["privilege"], g["granted_to"], g["grantee_name"], g["grant_option"]) for g in grants
    )
    if not any(
        g["privilege"] == "OWNERSHIP" and g["grantee_name"] == "OH_LYME_PROD_OWNER" for g in grants
    ) or not any(
        g["privilege"] == "SELECT" and g["grantee_name"] == "OH_LYME_PROD_READ" for g in grants
    ):
        raise ValueError("CONTEXT_OWNER_OR_READER_GRANT")
    cursor.execute(
        f"SELECT {LEGACY_COLUMNS} FROM {VIEW} "
        "WHERE county_fips IN ('01001','09110','51013') "
        "AND measure_id NOT IN ('population_2022','svi_percentile_2022','rucc_2023',"
        "'uninsured_percent_2022','uninsured_percentile_2022') "
        "ORDER BY measure_id,county_fips,observation_id LIMIT 30"
    )
    legacy = cursor.fetchall()
    if len(legacy) != 23:
        raise ValueError("CONTEXT_LEGACY_BASELINE")
    source = VIEW if deployed else f"({candidate()})"
    cursor.execute(
        f"SELECT measure_id,county_fips,value,value_state,period_start,period_end,"
        f"temporal_grain,vintage_year,metadata_revision_id,context_limitations FROM {source} "
        "WHERE county_fips IN ('01001','08001') ORDER BY measure_id,county_fips LIMIT 11"
    )
    observations = cursor.fetchall()
    if len(observations) != 10 or len({(r[0], r[1]) for r in observations}) != 10:
        raise ValueError("CONTEXT_TEN_OBSERVATIONS")
    cursor.execute(
        "SELECT fips,population,svi_percentile,uninsured_percent,uninsured_percentile,rucc_2023 "
        "FROM PRESENTATION.CURRENT_COUNTY_ATLAS_V WHERE fips IN ('01001','08001') ORDER BY fips"
    )
    summary = cursor.fetchall()
    if len(summary) != 2:
        raise ValueError("CONTEXT_SUMMARY")
    indices = {
        "population_2022": 1,
        "svi_percentile_2022": 2,
        "uninsured_percent_2022": 3,
        "uninsured_percentile_2022": 4,
        "rucc_2023": 5,
    }
    expected = {row[0]: row for row in summary}
    for row in observations:
        if json.loads(row[2]) != expected[row[1]][indices[row[0]]] or row[3] != "OBSERVED":
            raise ValueError("CONTEXT_SUMMARY_PARITY")
        if not row[8] or not json.loads(row[9]):
            raise ValueError("CONTEXT_METADATA")
        if row[0] == "rucc_2023" and row[4:8] != (None, None, "VINTAGE_YEAR", 2023):
            raise ValueError("CONTEXT_RUCC_TIME")
        if row[0] != "rucc_2023" and tuple(map(str, row[4:8])) != (
            "2018-01-01",
            "2022-12-31",
            "PERIOD",
            "2022",
        ):
            raise ValueError("CONTEXT_ACS_TIME")
    return {"grants": stable_grants, "legacy": legacy, "observations": observations}


def main() -> None:
    if (
        os.environ.get("TOPX_ENV") != "prod"
        or os.environ.get("ENABLE_PRODUCTION_EXECUTION") != "true"
        or os.environ.get("COUNTY_CONTEXT_ONLY") != "true"
    ):
        raise SystemExit("CONTEXT_PROTECTED_PROD_REQUIRED")
    expected = parse_reviewed_pending_set(os.environ["EXPECTED_PENDING_JSON"])
    helper = runpy.run_path(str(ROOT / "scripts/verify_climate_dev_views.py"))

    def inspect(deployed: bool) -> dict[str, Any]:
        connection = helper["bounded_connection"](query_tag="API212_V155_VERIFICATION")
        try:
            with connection.cursor() as cursor:
                from lyme_gap_atlas_data.climate_prod_binding import verify_execution_resource

                verify_execution_resource(
                    cursor, "OH_LYME_PROD_MIGRATION_DEPLOYER", "OH_LYME_PROD_MIGRATION_DEPLOY_SVC"
                )
                cursor.execute("USE ROLE OH_LYME_PROD_OWNER")
                cursor.execute(
                    "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()"
                )
                if cursor.fetchone() != (
                    "OH_LYME_PROD_MIGRATION_DEPLOY_SVC",
                    "OH_LYME_PROD_OWNER",
                    "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
                    "OH_LYME_PROD_APPROVAL_XS_WH",
                ):
                    raise ValueError("CONTEXT_OWNER_IDENTITY")
                return snapshot(cursor, deployed=deployed)
        finally:
            connection.close(retry=False)

    before = inspect(False)
    applied = apply_migrations(
        SnowflakeSettings(),
        "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        os.environ["GITHUB_SHA"],
        expected_pending=expected,
        county_context_only=True,
    )
    after = inspect(True)
    if before != after:
        raise SystemExit("CONTEXT_PRE_POST_PARITY")
    print(
        json.dumps(
            {
                "applied": applied,
                "excluded": ["V150"],
                "representative_rows": 10,
                "legacy_rows_unchanged": 23,
                "grants_unchanged": True,
            }
        )
    )


if __name__ == "__main__":
    main()
