"""Run fixture-only checks using the already configured protected DEV service."""

import json
import os
from pathlib import Path

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from lyme_gap_atlas_data.climate_dev_validation import verify_dev


def main() -> None:
    sql = (Path(__file__).parents[1] / "sql/january_climate_consumer_views.sql").read_text()
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        report = verify_dev(cursor, sql, os.environ.get("GITHUB_SHA", "UNKNOWN"))
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
