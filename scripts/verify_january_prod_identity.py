"""One protected runtime identity SELECT; no source acquisition or extra SQL."""

import json
import os
import runpy
from pathlib import Path

from lyme_gap_atlas_data.climate_prod_binding import execution_identity


def main() -> None:
    if (
        os.environ.get("TOPX_ENV") != "prod"
        or os.environ.get("ENABLE_PRODUCTION_EXECUTION") != "true"
    ):
        raise SystemExit("CLIMATE_PROD_PROTECTED_IDENTITY_REQUIRED")
    report = {"status": "BLOCKED", "category": "READ_OR_ACCESS_UNAVAILABLE"}
    connection = None
    try:
        helpers = runpy.run_path(str(Path(__file__).with_name("verify_climate_dev_views.py")))
        connection = helpers["bounded_connection"](query_tag="DATA443_PROD_RUNTIME_IDENTITY")
        with connection.cursor() as cursor:
            report = execution_identity(cursor, "OH_LYME_PROD_RUNTIME", "OH_LYME_PROD_PIPELINE_SVC")
    except (Exception, KeyboardInterrupt):
        pass
    finally:
        if connection is not None:
            try:
                connection.close(retry=False)
            except Exception:
                report = {"status": "BLOCKED", "category": "CLOSE_UNVERIFIED"}
    print(json.dumps(report), flush=True)
    if report["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
