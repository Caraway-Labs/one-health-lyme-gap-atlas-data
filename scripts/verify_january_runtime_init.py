"""Protected January runtime connection smoke; opens one session without SQL."""

from __future__ import annotations

import json
import logging
import os
from contextlib import suppress

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connection_parameters
from snowflake.connector import connect

from lyme_gap_atlas_data.climate_membership_diagnostic import budget_evidence, no_retry_backoff


def main() -> int:
    stage = "BUDGET_EVIDENCE"
    connection = None
    connector_logger = logging.getLogger("snowflake.connector")
    previous_level = connector_logger.level
    connector_logger.setLevel(logging.CRITICAL)
    try:
        evidence = budget_evidence(os.environ["JANUARY_DIAGNOSTIC_BUDGET_EVIDENCE"])
        capability = evidence.get("standard_capability_evidence")
        if capability is None:
            print(json.dumps({"status": "BLOCKED", "stage": "ACCOUNT_BINDING"}))
            return 1
        stage = "SETTINGS"
        settings = SnowflakeSettings()
        stage = "KEY_PARSE"
        parameters = connection_parameters(settings)
        if tuple(parameters.get(key) for key in ("user", "role", "database", "warehouse")) != (
            "OH_LYME_DEV_PIPELINE_SVC",
            "OH_LYME_DEV_RUNTIME",
            "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            "OH_LYME_DEV_INGEST_XS_WH",
        ):
            print(json.dumps({"status": "BLOCKED", "stage": "CONFIGURED_IDENTITY"}))
            return 1
        if not parameters.get("account"):
            print(json.dumps({"status": "BLOCKED", "stage": "CONFIGURED_IDENTITY"}))
            return 1
        parameters.update(
            login_timeout=5,
            network_timeout=5,
            socket_timeout=5,
            backoff_policy=no_retry_backoff,
            session_parameters={
                "QUERY_TAG": "atlas-january-runtime-init",
                "STATEMENT_TIMEOUT_IN_SECONDS": 5,
                "ABORT_DETACHED_QUERY": True,
            },
        )
        stage = "CONNECT"
        connection = connect(**parameters)
        print(json.dumps({"status": "CONNECTED_NO_SQL", "stage": "CONNECT"}))
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "stage": stage,
                    "exception_type": type(error).__name__,
                }
            )
        )
        return 1
    finally:
        if connection is not None:
            with suppress(Exception):
                connection.close(retry=False)
        connector_logger.setLevel(previous_level)


if __name__ == "__main__":
    raise SystemExit(main())
