"""Proposed operator invocation; not wired to an authenticated workflow."""

import json
import os
from pathlib import Path

from lyme_gap_atlas_data.climate_donor_diagnostic import ARTIFACT_NAME, producer


def main() -> int:
    result = producer(
        Path(os.environ["RUNNER_TEMP"]) / ARTIFACT_NAME,
        os.environ["GITHUB_SHA"],
        os.environ.get("JANUARY_DIAGNOSTIC_BUDGET_EVIDENCE", ""),
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "READ_ONLY_DONOR_EXPORT_SUCCEEDED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
