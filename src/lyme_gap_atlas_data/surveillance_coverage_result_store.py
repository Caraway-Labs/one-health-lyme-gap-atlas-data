"""Bounded, immutable DEV staging for safe surveillance coverage profiles."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .surveillance_coverage_results import serialize_surveillance_coverage

_TABLE = "PRESENTATION.SURVEILLANCE_COVERAGE_DERIVED_RESULTS"


def stage_surveillance_coverage(
    cursor: Any, result: Mapping[str, Any], *, evidence_basis: str
) -> tuple[str, str]:
    """Stage one safe document using the intended serialized DEV runtime writer.

    The caller is responsible for an approved DEV connection. Identical replay
    is a no-op; a conflicting result ID fails closed before and after MERGE.
    Snowflake standard-table primary keys are informational, not writer locks.
    """
    document = serialize_surveillance_coverage(result, evidence_basis=evidence_basis)
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    checksum = hashlib.sha256(payload.encode()).hexdigest()
    result_id = str(document["result_id"])
    site, event, source = document["site"], document["event"], document["source_scope"]
    if (
        not isinstance(site, Mapping)
        or not isinstance(event, Mapping)
        or not isinstance(source, Mapping)
    ):
        raise ValueError("safe coverage site, event, and source scope are required")
    cursor.execute(f"SELECT payload_sha256 FROM {_TABLE} WHERE result_id=%s", (result_id,))
    prior = cursor.fetchall()
    if len(prior) > 1 or (prior and prior[0][0] != checksum):
        raise ValueError("coverage identity has conflicting persisted payload")
    if prior:
        return result_id, "IDENTICAL_REPLAY"
    cursor.execute(
        f"""MERGE INTO {_TABLE} target
        USING (SELECT %s AS result_id, %s AS payload_sha256) source
        ON target.result_id=source.result_id
        WHEN NOT MATCHED THEN INSERT (
            result_id, contract_version, coverage_identity, construct_id,
            methodology_version, calculation_version, result_revision,
            result_state, native_grain, source_dataset_id, source_version_id,
            county_fips, source_site_id, source_event_id, collection_or_tested_date,
            payload_sha256, safe_payload
        ) VALUES (
            source.result_id, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, TO_DATE(%s), source.payload_sha256, PARSE_JSON(%s)
        )""",
        (
            result_id,
            checksum,
            document["contract_version"],
            document["coverage_identity"],
            document["construct_id"],
            document["methodology_version"],
            document["calculation_version"],
            document["result_revision"],
            document["state"],
            document["native_grain"],
            source["source_dataset_id"],
            source["source_version_id"],
            document["county_fips"],
            site["source_site_id"],
            event["source_event_id"],
            document["date"],
            payload,
        ),
    )
    cursor.execute(f"SELECT payload_sha256 FROM {_TABLE} WHERE result_id=%s", (result_id,))
    after = cursor.fetchall()
    if len(after) != 1 or after[0][0] != checksum:
        raise ValueError("coverage write failed immutable read-back")
    return result_id, "STAGED"
