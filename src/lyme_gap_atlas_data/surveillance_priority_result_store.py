"""Immutable, DEV-only staging for safe surveillance review dispositions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .surveillance_priority_results import serialize_surveillance_priority

_TABLE = "PRESENTATION.SURVEILLANCE_PRIORITY_DERIVED_RESULTS"


def stage_surveillance_priority(cursor: Any, result: Mapping[str, Any]) -> tuple[str, str]:
    """Stage one result through the intended serial DEV runtime writer."""
    document = serialize_surveillance_priority(result)
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    checksum = hashlib.sha256(payload.encode()).hexdigest()
    result_id = str(document["result_id"])
    source = document["source_scope"]
    if not isinstance(source, Mapping):
        raise ValueError("safe source scope is required")
    cursor.execute(f"SELECT payload_sha256 FROM {_TABLE} WHERE result_id=%s", (result_id,))
    prior = cursor.fetchall()
    if len(prior) > 1 or (prior and prior[0][0] != checksum):
        raise ValueError("surveillance priority result has conflicting persisted payload")
    if prior:
        return result_id, "IDENTICAL_REPLAY"
    cursor.execute(
        f"""MERGE INTO {_TABLE} target
        USING (SELECT %s AS result_id, %s AS payload_sha256) source
        ON target.result_id=source.result_id
        WHEN NOT MATCHED THEN INSERT (
            result_id, contract_version, methodology_version, result_revision,
            coverage_result_id, construct_id, disposition, comparison_cohort_id,
            tie_group_id, source_dataset_id, source_version_id,
            payload_sha256, safe_payload
        ) VALUES (
            source.result_id, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            source.payload_sha256, PARSE_JSON(%s)
        )""",
        (
            result_id,
            checksum,
            document["contract_version"],
            document["methodology_version"],
            document["result_revision"],
            document["coverage_result_id"],
            document["construct_id"],
            document["disposition"],
            document["comparison_cohort_id"],
            document["tie_group_id"],
            source["source_dataset_id"],
            source["source_version_id"],
            payload,
        ),
    )
    cursor.execute(f"SELECT payload_sha256 FROM {_TABLE} WHERE result_id=%s", (result_id,))
    after = cursor.fetchall()
    if len(after) != 1 or after[0][0] != checksum:
        raise ValueError("surveillance priority write failed immutable read-back")
    return result_id, "STAGED"
