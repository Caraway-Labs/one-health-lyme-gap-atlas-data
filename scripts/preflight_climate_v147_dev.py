"""Protected fixed DEV metadata preflight; never applies a migration."""

import json
import os
import runpy
from pathlib import Path

from lyme_gap_atlas_data import climate_membership_diagnostic as bounds
from lyme_gap_atlas_data.climate_metadata_preflight import (
    Stop,
    inspect,
    inspect_ledger,
    prepare_evidence,
    receipt,
    statements,
)


def main() -> None:
    report = receipt(os.environ.get("GITHUB_SHA", "UNKNOWN"))
    ledger_only = os.environ.get("LEDGER_DIAGNOSTIC_ONLY") == "true"
    if ledger_only:
        report.update(
            mode="V147_DEV_LEDGER_DIAGNOSTIC_ONLY",
            checks=[
                {"ordinal": ordinal, "name": name, "status": "NOT_EXECUTED"}
                for ordinal, name in enumerate(("identity", "warehouse", "migration_ledger"), 1)
            ],
        )
    connection = None
    try:
        statements()  # Scope validation precedes authentication.
        evidence = prepare_evidence(
            os.environ.get("JANUARY_DIAGNOSTIC_BUDGET_EVIDENCE", ""), report
        )
        helpers = runpy.run_path(str(Path(__file__).with_name("verify_climate_dev_views.py")))
        helpers["budget_evidence"] = evidence
        connection = helpers["bounded_connection"]()
        with connection.cursor() as cursor:
            inspector = inspect_ledger if ledger_only else inspect
            report = inspector(cursor, report, helpers)
    except (Exception, KeyboardInterrupt) as error:
        report["failure"] = (
            str(error)
            if isinstance(error, (Stop, bounds.DiagnosticStop))
            else "PRE_CONNECTION_OR_PROCESS_LIMIT"
        )
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
