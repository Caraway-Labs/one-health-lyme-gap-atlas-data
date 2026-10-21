"""Protected exact-plan approval for the fixed PROD EID source; never raw deletion."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from typing import Any

from lyme_gap_atlas_data.ingestion.intelligence_runtime import pilot_watchdog
from lyme_gap_atlas_data.intelligence_items import TOKEN, canonical_timestamp
from lyme_gap_atlas_data.intelligence_raw_cleanup import ObjectRawDelete, prod_cleanup_scope
from lyme_gap_atlas_data.intelligence_retention import plan_cleanup
from scripts.intelligence_raw_cleanup_prod import (
    APPROVER_ROLE,
    APPROVER_USER,
    approve,
    factory,
    gate_for,
    identity,
)

OTHER_MODES = (
    "retained_human_lineage_only",
    "retained_lineage_only",
    "release_integrity_only",
    "cdc_admission_only",
    "january_climate_only",
    "january_bulk_recovery_only",
    "january_point_query_only",
    "county_context_only",
    "protected_intelligence_prerequisite",
)
MODE = "intelligence-cleanup-approval-only"
BUCKET = "one-health-lyme-gap-atlas-data-prod"


def validate_request(inputs: dict[str, Any], environment: dict[str, str]) -> tuple[str, str, str]:
    """Only an exact green-main workflow request may reach the service factory."""
    commit = inputs.get("reviewed_commit", "")
    checksum = inputs.get("cleanup_plan_sha256", "")
    planned_at = inputs.get("cleanup_planned_at", "")
    ref = inputs.get("cleanup_approval_ref", "")
    if (
        environment.get("GITHUB_ACTIONS") != "true"
        or environment.get("GITHUB_REPOSITORY", "").lower()
        != "caraway-labs/one-health-lyme-gap-atlas-data"
        or environment.get("GITHUB_REF") != "refs/heads/main"
        or not isinstance(commit, str)
        or re.fullmatch(r"[a-f0-9]{40}", commit) is None
        or environment.get("GITHUB_SHA") != commit
        or inputs.get("approve_intelligence_cleanup_only") is not True
        or any(inputs.get(mode, False) is not False for mode in OTHER_MODES)
        or inputs.get("image_digest") != MODE
        or inputs.get("expected_pending_json") != "[]"
        or not isinstance(checksum, str)
        or re.fullmatch(r"[a-f0-9]{64}", checksum) is None
        or not isinstance(planned_at, str)
        or canonical_timestamp(planned_at) != planned_at
        or datetime.fromisoformat(planned_at.replace("Z", "+00:00")) > datetime.now(UTC)
        or not isinstance(ref, str)
        or len(ref) > 128
        or TOKEN.fullmatch(ref) is None
    ):
        raise PermissionError("INTELLIGENCE_RAW_APPROVAL_REQUEST_INVALID")
    return checksum, planned_at, ref


def approve_exact_plan(checksum: str, planned_at: str, ref: str) -> None:
    identity(factory, APPROVER_USER, APPROVER_ROLE)
    gate = gate_for(factory, APPROVER_ROLE)
    with gate.ledger.guard():
        driver = ObjectRawDelete(gate, object(), bucket=BUCKET, prefix="prod")
        plan = plan_cleanup(
            gate,
            environment="PROD",
            source_ids=("cdc-eid-expedited",),
            now=planned_at,
            scope=lambda copy: prod_cleanup_scope(copy, driver),
        )
    if not 1 <= len(plan.copies) <= 1000 or plan.sha256 != checksum:
        raise PermissionError("INTELLIGENCE_RAW_PLAN_CHANGED")
    # Existing approver rechecks the whole inventory, enforces the actual service
    # identity and writes only the canonical approval under the existing guard.
    approve(factory, gate, plan, ref, BUCKET, "prod")
    print(json.dumps({"approved_plan_sha256": plan.sha256, "copy_count": len(plan.copies)}))


def main() -> None:
    inputs = json.loads(os.environ["CLEANUP_APPROVAL_INPUTS"])
    if not isinstance(inputs, dict):
        raise PermissionError("INTELLIGENCE_RAW_APPROVAL_REQUEST_INVALID")
    checksum, planned_at, ref = validate_request(inputs, dict(os.environ))
    with pilot_watchdog(seconds=120):
        approve_exact_plan(checksum, planned_at, ref)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never publish the private canonical plan, locators or provider errors.
        print("INTELLIGENCE_RAW_PLAN_APPROVAL_FAILED", file=sys.stderr)
        raise SystemExit(2) from None
