"""Protected fixed DEV metadata preflight; never applies a migration."""

import json
import os
import runpy
from pathlib import Path

from lyme_gap_atlas_data.climate_metadata_preflight import inspect, receipt, statements


def main() -> None:
    report = receipt(os.environ.get("GITHUB_SHA", "UNKNOWN"))
    connection = None
    try:
        statements()  # Scope validation precedes authentication.
        helpers = runpy.run_path(str(Path(__file__).with_name("verify_climate_dev_views.py")))
        connection = helpers["bounded_connection"]()
        with connection.cursor() as cursor:
            report = inspect(cursor, report, helpers)
    except (Exception, KeyboardInterrupt):
        report["failure"] = "PRE_CONNECTION_OR_PROCESS_LIMIT"
    finally:
        if connection is not None:
            try:
                # Avoid connection context-manager COMMIT/ROLLBACK and close retries.
                connection.close(retry=False)
                report["close_state"] = "CLOSED_NO_RETRY"
            except Exception:
                report.update(status="BLOCKED", sole_v147_ready=False, close_state="UNVERIFIED")
        print(json.dumps(report, sort_keys=True), flush=True)
    if report["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
