"""Optional session limits for existing canonical Snowflake operations."""

from __future__ import annotations

import os
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect as shared_connect


def connect(settings: SnowflakeSettings, *, include_database: bool = True) -> Any:
    """Apply opt-in limits before returning an existing authenticated connection."""
    raw_timeout = os.environ.get("ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS")
    timeout = int(raw_timeout) if raw_timeout else None
    if timeout is not None and not 1 <= timeout <= 60:
        raise ValueError("ATLAS_SQL_STATEMENT_TIMEOUT_SECONDS must be between 1 and 60")
    connection = shared_connect(settings, include_database=include_database)
    if timeout is not None:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS={timeout}, "
                    "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS=10, ABORT_DETACHED_QUERY=TRUE, "
                    "QUERY_TAG='DATA594_BOUNDED_COHORT_DELIVERY'"
                )
        except Exception:
            connection.close()
            raise
    return connection
