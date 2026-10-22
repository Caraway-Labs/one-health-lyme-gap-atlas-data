"""Execute the migration's extracted time predicates with a fixed clock.

SQLite is a predicate double, not Snowflake stored-procedure acceptance.
Keeping DATEADD executable makes the former 48-hour regression fail here.
"""

import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


@pytest.mark.parametrize("seconds", [-1, 0, 1, 47 * 3600, 48 * 3600, 49 * 3600])
def test_dev_expiry_and_shared_live_claim_predicates_use_actual_expiry(seconds):
    sql = (
        Path(__file__).parents[1] / "migrations/V166__dev_additional_cdc_feed_cleanup.sql"
    ).read_text()
    expressions = re.findall(
        r"((?:TRY_)?TO_TIMESTAMP_TZ\(l\.DOCUMENT:expires_at::VARCHAR\)(?:<=|>).+?);", sql
    )
    assert len(expressions) == 2
    now = datetime(2026, 10, 1, tzinfo=UTC)
    expiry = (now + timedelta(seconds=seconds)).isoformat()
    with sqlite3.connect(":memory:") as connection:
        connection.create_function("now_value", 0, lambda: now.timestamp())
        connection.create_function(
            "TO_TIMESTAMP_TZ", 1, lambda value: datetime.fromisoformat(value).timestamp()
        )
        connection.create_function(
            "TRY_TO_TIMESTAMP_TZ", 1, lambda value: datetime.fromisoformat(value).timestamp()
        )
        connection.create_function(
            "DATEADD",
            3,
            lambda unit, count, value: value + count * {"hour": 3600, "day": 86400}[unit],
        )
        observed = []
        for expression in expressions:
            while expression.count(")") > expression.count("("):
                expression = expression[:-1]
            expression = expression.replace("l.DOCUMENT:expires_at::VARCHAR", "?")
            expression = expression.replace("CURRENT_TIMESTAMP()", "now_value()")
            expression = expression.replace("DATEADD(hour,", "DATEADD('hour',")
            observed.append(
                bool(connection.execute("SELECT " + expression, (expiry,)).fetchone()[0])
            )
    assert observed == [seconds <= 0, seconds > 0]
