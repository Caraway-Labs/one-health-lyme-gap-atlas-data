"""Bounded canonical migration runner entry: only reviewed PROD V151/V152."""

import json
import os
import runpy
from pathlib import Path

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from lyme_gap_atlas_data.migrations import apply_migrations, parse_reviewed_pending_set


def main() -> None:
    if (
        os.environ.get("TOPX_ENV") != "prod"
        or os.environ.get("ENABLE_PRODUCTION_EXECUTION") != "true"
    ):
        raise SystemExit("JANUARY_PROTECTED_PROD_REQUIRED")
    expected = parse_reviewed_pending_set(os.environ["EXPECTED_PENDING_JSON"])
    helper = runpy.run_path(str(Path(__file__).with_name("verify_climate_dev_views.py")))
    connection = helper["bounded_connection"](query_tag="DATA443_JANUARY_PROD_MIGRATIONS")
    try:
        with connection.cursor() as cursor:
            from lyme_gap_atlas_data.climate_prod_binding import verify_execution_resource

            verify_execution_resource(
                cursor, "OH_LYME_PROD_MIGRATION_DEPLOYER", "OH_LYME_PROD_MIGRATION_DEPLOY_SVC"
            )
            cursor.execute("SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE()")
            if cursor.fetchone() != (
                "OH_LYME_PROD_MIGRATION_DEPLOY_SVC",
                "OH_LYME_PROD_MIGRATION_DEPLOYER",
                "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
            ):
                raise SystemExit("JANUARY_PROD_IDENTITY")
    finally:
        connection.close(retry=False)
    applied = apply_migrations(
        SnowflakeSettings(),
        "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        os.environ["GITHUB_SHA"],
        expected_pending=expected,
        january_climate_only=True,
    )
    print(json.dumps({"applied": applied, "excluded": ["V150"]}))


if __name__ == "__main__":
    main()
