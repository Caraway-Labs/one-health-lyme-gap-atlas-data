"""Bounded CDC batch v1 over the existing private secure authority view.

The caller lends an exclusive request-owned reader query callback. No connection,
session setting, cache, publication, or singleton behavior is changed here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import as_file
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Literal

from .cdc_consumer_admission import RELEASE_BUNDLES, SLICES, TARGET_RELEASE_ID
from .cdc_consumer_runtime import (
    AUTHORITY_SQL,
    IDENTITY_SQL,
    CDCConsumerUnavailable,
    Query,
    _inputs,
    _metadata,
    _resources,
)
from .semantic_source_mappings import load_mapping_registry, map_record
from .surveillance_evidence_mapping import project_surveillance_evidence

MAX_COUNTIES = 50
MAX_ENVELOPE_BYTES = 8 * 1024 * 1024
CONTRACT_VERSION: Literal["atlas-cdc-consumer-batch-v1"] = "atlas-cdc-consumer-batch-v1"
_ERROR = "CDC batch authority unavailable; no partial results or fallback"
# Reuse the singleton's exact column contract rather than a second field model.
_SELECT = AUTHORITY_SQL.split("\n FROM", 1)[0]
_FIELDS = tuple(field.strip() for field in _SELECT.removeprefix("SELECT ").split(","))
_SHARED = {"review_decisions", "attestations"}


@dataclass(frozen=True)
class CDCBatchResultV1:
    """Safe observations in caller order; contains no private authority envelope."""

    measure_id: str
    release_id: str
    county_fips: tuple[str, ...]
    observations: tuple[dict[str, Any], ...]
    contract_version: Literal["atlas-cdc-consumer-batch-v1"] = CONTRACT_VERSION


def _counties(counties: Sequence[str]) -> tuple[str, ...]:
    if (
        isinstance(counties, (str, bytes))
        or not isinstance(counties, Sequence)
        or not 1 <= len(counties) <= MAX_COUNTIES
        or any(not isinstance(c, str) or re.fullmatch(r"[0-9]{5}", c) is None for c in counties)
        or len(set(counties)) != len(counties)
    ):
        raise CDCConsumerUnavailable(_ERROR)
    return tuple(counties)


def _authority_sql(count: int) -> str:
    """Single statement: shared proof and every row have one committed snapshot."""
    if not 1 <= count <= MAX_COUNTIES:
        raise CDCConsumerUnavailable(_ERROR)
    objects = []
    for field in _FIELDS:
        expression = (
            "OBJECT_DELETE(cdc_runtime_authority, 'review_decisions', 'attestations')"
            if field == "cdc_runtime_authority"
            else field
        )
        objects.append(f"'{field}', {expression}")
    return f"""WITH scoped AS (
 {_SELECT}
 FROM LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V
 WHERE release_id=%s AND measure_id=%s AND source_version_id=%s
 AND county_fips IN ({", ".join(["%s"] * count)})
 QUALIFY ROW_NUMBER() OVER (PARTITION BY county_fips ORDER BY observation_id) <= 2
), packed AS (
 SELECT county_fips, observation_id,
 OBJECT_CONSTRUCT_KEEP_NULL({", ".join(objects)}) AS record,
 OBJECT_CONSTRUCT_KEEP_NULL(
   'review_decisions', cdc_runtime_authority:review_decisions,
   'attestations', cdc_runtime_authority:attestations) AS shared
 FROM scoped
), anchored AS (
 SELECT *, FIRST_VALUE(shared) OVER (
   ORDER BY county_fips, observation_id
   ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS shared_anchor
 FROM packed
)
SELECT OBJECT_CONSTRUCT_KEEP_NULL(
 'shared_authority', ANY_VALUE(shared_anchor),
 'shared_consistent', COALESCE(BOOLAND_AGG(COALESCE(shared=shared_anchor, FALSE)), FALSE),
 'records', ARRAY_AGG(record) WITHIN GROUP (ORDER BY county_fips, observation_id)
) AS batch_authority
FROM anchored"""


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_ENVELOPE_BYTES:
            raise CDCConsumerUnavailable(_ERROR)
        value = json.loads(value)
    if not isinstance(value, dict):
        raise CDCConsumerUnavailable(_ERROR)
    return value


def _project_batch(
    query: Query,
    root: Traversable,
    measure: str,
    counties: Sequence[str],
    environment: str,
    release_id: str,
) -> CDCBatchResultV1:
    requested = _counties(counties)
    if measure not in SLICES or environment not in {"dev", "prod"}:
        raise CDCConsumerUnavailable(_ERROR)
    metadata = _metadata(root, measure, release_id)
    identity = query(IDENTITY_SQL, ())
    if len(identity) != 1 or (
        not identity[0].get("USER")
        or not identity[0].get("WAREHOUSE")
        or identity[0].get("ROLE") != f"OH_LYME_{environment.upper()}_READ"
        or identity[0].get("DATABASE") != f"ONE_HEALTH_LYME_GAP_ATLAS_{environment.upper()}"
    ):
        raise CDCConsumerUnavailable(_ERROR)
    params = (release_id, measure, SLICES[measure]["source_version_id"], *requested)
    result = query(_authority_sql(len(requested)), params)
    if len(result) != 1:
        raise CDCConsumerUnavailable(_ERROR)
    envelope = _object({str(k).lower(): v for k, v in result[0].items()}["batch_authority"])
    if len(json.dumps(envelope, ensure_ascii=False).encode("utf-8")) > MAX_ENVELOPE_BYTES:
        raise CDCConsumerUnavailable(_ERROR)
    if set(envelope) != {"shared_authority", "shared_consistent", "records"}:
        raise CDCConsumerUnavailable(_ERROR)
    shared = _object(envelope["shared_authority"])
    rows = envelope["records"]
    if (
        envelope["shared_consistent"] is not True
        or set(shared) != _SHARED
        or any(not isinstance(shared[field], list) for field in _SHARED)
        or not isinstance(rows, list)
        or len(rows) != len(requested)
    ):
        raise CDCConsumerUnavailable(_ERROR)
    by_county = {}
    observations = set()
    for raw in rows:
        row = _object(raw)
        if set(row) != set(_FIELDS):
            raise CDCConsumerUnavailable(_ERROR)
        county, observation = row["county_fips"], row["observation_id"]
        if (
            county not in requested
            or county in by_county
            or not isinstance(observation, str)
            or not observation
            or observation in observations
            or row["release_id"] != release_id
            or row["release_bundle_sha256"] != RELEASE_BUNDLES[release_id]
            or row["measure_id"] != measure
            or row["source_version_id"] != SLICES[measure]["source_version_id"]
        ):
            raise CDCConsumerUnavailable(_ERROR)
        facts = _object(row["cdc_runtime_authority"])
        if _SHARED & facts.keys():
            raise CDCConsumerUnavailable(_ERROR)
        row["cdc_runtime_authority"] = {**facts, **shared}
        by_county[county] = row
        observations.add(observation)
    if set(by_county) != set(requested):
        raise CDCConsumerUnavailable(_ERROR)
    mapping_resource = root.joinpath("atlas-semantic-source-mappings-v1.json")
    if not mapping_resource.is_file() and isinstance(root, Path):
        mapping_resource = root.parent / "atlas-semantic-source-mappings-v1.json"
    with as_file(mapping_resource) as path:
        mappings = load_mapping_registry(path)
    output = []
    for county in requested:
        record, authority = _inputs(by_county[county], metadata)
        map_record(record, metadata, authority, mappings)
        output.append(project_surveillance_evidence(record, metadata, authority, mappings))
    return CDCBatchResultV1(measure, release_id, requested, tuple(output))


def produce_cdc_batch_v1(
    query: Query,
    measure: str,
    counties: Sequence[str],
    *,
    environment: Literal["dev", "prod"] = "prod",
    release_id: str = TARGET_RELEASE_ID,
) -> CDCBatchResultV1:
    """Borrow a request-owned reader; return the complete admitted batch or fail.

    query executes bound SQL and fetches at most two rows (one envelope expected).
    It must use the same exclusive connection for identity and authority reads.
    Private authority and callback errors are never included in this safe error.
    Cancellation/BaseException propagates for the caller's connection cleanup.
    """
    try:
        return _project_batch(query, _resources(), measure, counties, environment, release_id)
    except Exception:
        raise CDCConsumerUnavailable(_ERROR) from None
