"""Optional session limits for existing canonical Snowflake operations."""

from __future__ import annotations

import os
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect as shared_connect
from lyme_gap_atlas_shared.snowflake import connection_parameters
from snowflake.connector import connect as connector_connect


def connect(settings: SnowflakeSettings, *, include_database: bool = True) -> Any:
    """Apply opt-in limits before returning an existing authenticated connection."""
    if os.environ.get("ATLAS_JANUARY_PROD_SESSION") == "true":
        connection = connector_connect(
            **january_connection_parameters(settings, include_database=include_database)
        )
        require_january_warehouse(connection)
        return connection
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


def january_connection_parameters(
    settings: SnowflakeSettings, *, include_database: bool = True
) -> dict[str, Any]:
    """Request the approved warehouse at login; no session SQL or fallback."""
    if (
        settings.snowflake_warehouse != "OH_LYME_PROD_APPROVAL_XS_WH"
        or settings.snowflake_database != "ONE_HEALTH_LYME_GAP_ATLAS_PROD"
    ):
        raise ValueError("JANUARY_WAREHOUSE_CONFIGURATION")
    parameters = connection_parameters(settings, include_database=include_database)
    parameters.update(
        warehouse=settings.snowflake_warehouse,
        validate_default_parameters=True,
        network_timeout=65,
        socket_timeout=65,
    )
    parameters["session_parameters"].update(
        STATEMENT_TIMEOUT_IN_SECONDS=60,
        STATEMENT_QUEUED_TIMEOUT_IN_SECONDS=10,
        ABORT_DETACHED_QUERY=True,
    )
    return parameters


def require_january_warehouse(connection: Any) -> None:
    """Check server-returned login metadata before any SQL can execute."""
    if connection.warehouse != "OH_LYME_PROD_APPROVAL_XS_WH":
        try:
            connection.close(retry=False)
        finally:
            raise ValueError("JANUARY_WAREHOUSE_NOT_SELECTED")
