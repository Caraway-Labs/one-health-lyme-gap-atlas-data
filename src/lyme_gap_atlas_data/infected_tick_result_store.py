"""Bounded DEV staging for consumer-safe infected-tick derived results."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .infected_tick_results import serialize_infected_tick_result

_TABLE = "ANALYTICS.INFECTED_TICK_DERIVED_RESULTS"


def stage_infected_tick_result(
    cursor: Any, result: Mapping[str, Any], *, evidence_basis: str
) -> tuple[str, str]:
    """Stage one immutable safe result using an already validated DEV writer.

    Returns ``(result_id, disposition)``. Replaying identical bytes is a no-op.
    A conflicting payload for one result ID fails closed, including a changed
    presentation or evidence claim. The caller must serialize writers for this
    narrowly scoped table; Snowflake standard-table primary keys are not
    enforced as a concurrency lock.
    """
    document = serialize_infected_tick_result(result, evidence_basis=evidence_basis)
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    checksum = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    result_id = str(document["result_id"])
    site = document["site"]
    event = document["event"]
    if not isinstance(site, Mapping) or not isinstance(event, Mapping):
        raise ValueError("site and event are required")
    cursor.execute(
        f"SELECT payload_sha256 FROM {_TABLE} WHERE result_id=%s",
        (result_id,),
    )
    prior = cursor.fetchall()
    if len(prior) > 1 or (prior and prior[0][0] != checksum):
        raise ValueError("derived result identity has conflicting persisted payload")
    if prior:
        return result_id, "IDENTICAL_REPLAY"
    cursor.execute(
        f"""MERGE INTO {_TABLE} target
        USING (SELECT %s AS result_id, %s AS payload_sha256) source
        ON target.result_id=source.result_id
        WHEN NOT MATCHED THEN INSERT (
            result_id, contract_version, metric_identity, metric_id,
            methodology_version, calculation_version, result_revision,
            result_state, native_grain, source_site_id, source_event_id,
            collection_or_tested_date, payload_sha256, safe_payload
        ) VALUES (
            source.result_id, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            TO_DATE(%s), source.payload_sha256, PARSE_JSON(%s)
        )""",
        (
            result_id,
            checksum,
            document["contract_version"],
            document["metric_identity"],
            document["metric_id"],
            document["methodology_version"],
            document["calculation_version"],
            document["result_revision"],
            document["state"],
            document["native_grain"],
            site["source_site_id"],
            event["source_event_id"],
            document["date"],
            payload,
        ),
    )
    cursor.execute(f"SELECT payload_sha256 FROM {_TABLE} WHERE result_id=%s", (result_id,))
    after = cursor.fetchall()
    if len(after) != 1 or after[0][0] != checksum:
        raise ValueError("derived result write failed immutable read-back")
    return result_id, "STAGED"
