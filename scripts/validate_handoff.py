"""Validate the repository's compact evidence-handoff JSON examples."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

EVIDENCE_STATES = {"PASS", "FAIL", "UNKNOWN"}
WORKLOAD_FIELDS = {
    "requested_sha",
    "workflow_head_sha",
    "tested_artifact",
    "deployed_artifact",
    "semantic_bundle",
    "api_contract",
}
VERIFICATION_FIELDS = {"local_tests", "ci", "deployment", "live_functional"}
REQUIRED_FIELDS = {
    "outcome",
    "starting_commit",
    "date",
    "scope",
    "non_goals",
    "workload",
    "verification",
}


def _validate_evidence(value: Any, path: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{path} must be an object"]
    if value.get("state") not in EVIDENCE_STATES:
        return [f"{path}.state must be PASS, FAIL, or UNKNOWN"]
    if not isinstance(value.get("reference"), str) or not value["reference"].strip():
        return [f"{path}.reference must be a non-empty string"]
    return []


def validate_handoff(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["handoff must be a JSON object"]
    errors = [
        f"missing required field: {field}" for field in sorted(REQUIRED_FIELDS - set(payload))
    ]
    for field in REQUIRED_FIELDS - {"workload", "verification"}:
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            errors.append(f"{field} must be a non-empty string")
    for section, fields in (("workload", WORKLOAD_FIELDS), ("verification", VERIFICATION_FIELDS)):
        value = payload.get(section)
        if not isinstance(value, dict):
            errors.append(f"{section} must be an object")
            continue
        errors.extend(f"missing {section} field: {field}" for field in sorted(fields - set(value)))
        errors.extend(
            _validate_evidence(value[field], f"{section}.{field}") for field in fields & set(value)
        )
    return [
        item for nested in errors for item in (nested if isinstance(nested, list) else [nested])
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", type=Path, nargs="+")
    args = parser.parse_args()
    errors: list[str] = []
    for path in args.handoff:
        errors.extend(
            f"{path}: {error}" for error in validate_handoff(json.loads(path.read_text()))
        )
    if errors:
        print("\n".join(errors))
        return 1
    print("Handoff validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
