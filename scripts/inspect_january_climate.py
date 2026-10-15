"""Fixed approved read-only DEV/PROD inspection; no mutation dispatch."""

import hashlib
import json
import os
import runpy
import time
from pathlib import Path

from lyme_gap_atlas_data.climate_inspection import Stop, inspect, statements


def main():
    environment = os.environ.get("INSPECTION_ENVIRONMENT", "")
    report = {"environment": environment, "status": "BLOCKED", "statements_executed": 0}
    connection = None
    try:
        statements(environment)
        suffix = "PROD" if environment == "production" else "DEV"
        expected = (
            f"OH_LYME_{suffix}_MIGRATION_DEPLOY_SVC",
            f"OH_LYME_{suffix}_MIGRATION_DEPLOYER",
            f"ONE_HEALTH_LYME_GAP_ATLAS_{suffix}",
            "OH_LYME_PROD_APPROVAL_XS_WH" if suffix == "PROD" else "OH_LYME_DEV_INGEST_XS_WH",
        )
        configured = tuple(
            os.environ.get(f"SNOWFLAKE_{key}") for key in ("USER", "ROLE", "DATABASE", "WAREHOUSE")
        )
        if configured != expected:
            raise Stop("CONFIGURED_IDENTITY")
        helpers = runpy.run_path(str(Path(__file__).with_name("verify_climate_dev_views.py")))
        connection = helpers["bounded_connection"]()
        with connection.cursor() as cursor:
            report = inspect(cursor, environment, expected, report, time.monotonic())
    except (Exception, KeyboardInterrupt) as error:
        report["failure"] = str(error) if isinstance(error, Stop) else "READ_OR_ACCESS_UNAVAILABLE"
    finally:
        if connection is not None:
            try:
                connection.close(retry=False)
                report["close_state"] = "CLOSED_NO_RETRY"
            except Exception:
                report.update(status="BLOCKED", close_state="UNVERIFIED")
        report["code_sha"] = os.environ.get("GITHUB_SHA", "UNKNOWN")
        report["report_sha256"] = hashlib.sha256(
            json.dumps(report, default=str, sort_keys=True).encode()
        ).hexdigest()
        print(json.dumps(report, default=str, sort_keys=True), flush=True)
    if report["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
