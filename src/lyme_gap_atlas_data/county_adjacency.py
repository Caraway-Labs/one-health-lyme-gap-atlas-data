"""Governed Census 2025 county adjacency pairs for issue #872.

The loader keeps published pipe-delimited rows, including areas outside the
Atlas county set, and writes one undirected pair per in-scope neighbor
relationship. Islands stay in the quality result and are not stored as pairs.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from importlib.resources import files
from typing import Any

RESOURCE_KEY = "census_county_adjacency_2025"
SOURCE_URL = "https://www2.census.gov/geo/docs/reference/county_adjacency/county_adjacency2025.txt"
SOURCE_FILE_NAME = "county_adjacency2025.txt"
SOURCE_VINTAGE = "2025"
LICENSE_BASIS = (
    "U.S. federal government work, public domain. Cite the U.S. Census Bureau. "
    "Same basis as ADR 0036."
)
PINNED_SHA256 = "8233d2aed342f62eb02bae9f9002ad1d8fc6bd82d739185eba8bad832bf8fc87"
RELEASE_ID = f"census-county-adjacency-{SOURCE_VINTAGE}-{PINNED_SHA256[:8]}"
REQUIRED_COLUMNS = (
    "County Name",
    "County GEOID",
    "Neighbor Name",
    "Neighbor GEOID",
    "Length",
)
QUALITY_RULE_IDS = (
    "census_adjacency_required_fields",
    "census_adjacency_identity",
    "census_adjacency_symmetry",
    "census_adjacency_scope",
    "census_adjacency_checksum",
    "census_adjacency_islands",
)
EXPECTED_UNDIRECTED_PAIRS = 9286
EXPECTED_EDGE_PAIRS = 8938
EXPECTED_POINT_PAIRS = 348
EXPECTED_ISLANDS = frozenset({"15001", "15003", "15007"})
CT_PLANNING_REGIONS = (
    "09110",
    "09120",
    "09130",
    "09140",
    "09150",
    "09160",
    "09170",
    "09180",
    "09190",
)
AK_SPLIT = ("02063", "02066")
_EXCLUDED_STATEFP = frozenset({"60", "66", "69", "72", "78"})
_FIPS = re.compile(r"^[0-9]{5}\Z")
_LENGTH = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?\Z")
_RUN_ID = re.compile(r"^[A-Za-z0-9:._-]{1,200}\Z")
_MERGE_BATCH = 200
_CODE_RULE = {
    "EMPTY_FILE": "census_adjacency_required_fields",
    "MISSING_COLUMNS": "census_adjacency_required_fields",
    "PARTIAL_NEIGHBOR": "census_adjacency_required_fields",
    "LENGTH_TEXT": "census_adjacency_required_fields",
    "FIPS_SHAPE": "census_adjacency_identity",
    "SELF_PAIR": "census_adjacency_identity",
    "DUPLICATE_DIRECTED": "census_adjacency_identity",
    "ASYMMETRIC_PAIR": "census_adjacency_symmetry",
    "LENGTH_MISMATCH": "census_adjacency_symmetry",
    "CROSS_SCOPE": "census_adjacency_scope",
    "MISSING_COUNTY": "census_adjacency_scope",
    "PAIR_COUNT": "census_adjacency_scope",
    "CONTACT_COUNT": "census_adjacency_scope",
    "STATE_DEGREE": "census_adjacency_scope",
    "COUNTY_REFERENCE": "census_adjacency_scope",
    "ISLAND_SET": "census_adjacency_islands",
    "SHA256_MISMATCH": "census_adjacency_checksum",
    "ENVIRONMENT": "census_adjacency_checksum",
    "RETRIEVED_AT": "census_adjacency_checksum",
    "RUN_ID": "census_adjacency_checksum",
    "LEDGER_SHAPE": "census_adjacency_checksum",
}
_ENVIRONMENTS = {
    "DEV": "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
    "PROD": "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
}


class CountyAdjacencyError(ValueError):
    """Fail-closed adjacency rejection. The message is a stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PublishedRow:
    county_name: str
    county_geoid: str
    neighbor_name: str
    neighbor_geoid: str
    length_text: str


@dataclass(frozen=True)
class GovernedPair:
    fips_a: str
    fips_b: str
    shared_boundary_m: str
    contact_type: str


@dataclass(frozen=True)
class ConformResult:
    published: tuple[PublishedRow, ...]
    pairs: tuple[GovernedPair, ...]
    islands: tuple[str, ...]
    edge_count: int
    point_count: int


@dataclass(frozen=True)
class PreparedLoad:
    result: ConformResult
    artifact_sha256: str
    ingestion_run_id: str
    retrieved_at: datetime


@dataclass(frozen=True)
class MergeReceipt:
    inserted: int
    updated: int
    deleted: int
    pair_count: int
    edge_count: int
    point_count: int
    islands: tuple[str, ...]


def database_name(environment: str) -> str:
    """Return the only database names the loader may write."""
    try:
        return _ENVIRONMENTS[environment]
    except KeyError as error:
        raise CountyAdjacencyError("ENVIRONMENT") from error


@lru_cache(maxsize=1)
def project_counties() -> frozenset[str]:
    """Load the frozen 3,144-ID project county reference."""
    text = (
        files("lyme_gap_atlas_data")
        .joinpath("data/canonical-county-fips-2022.txt")
        .read_text(encoding="utf-8")
    )
    identities = tuple(text.splitlines())
    if (
        len(identities) != 3144
        or len(identities) != len(set(identities))
        or any(_FIPS.fullmatch(value) is None for value in identities)
    ):
        raise CountyAdjacencyError("COUNTY_REFERENCE")
    return frozenset(identities)


def validate_definition(definition: Any) -> list[tuple[str, str]]:
    """Reject a census adjacency definition that drifts from the reviewed pin."""
    if definition.resource_key != RESOURCE_KEY:
        return []
    issues: list[tuple[str, str]] = []

    def add(code: str, message: str) -> None:
        issues.append((code, message))

    extra = definition.extra
    if definition.endpoint_template != SOURCE_URL:
        add("ADJACENCY_URL", "Census adjacency endpoint must be the pinned 2025 file")
    if extra.get("artifact_sha256") != PINNED_SHA256:
        add("ADJACENCY_SHA256", "Census adjacency artifact_sha256 must be the pinned digest")
    if extra.get("delimiter") != "|":
        add("ADJACENCY_DELIMITER", "Census adjacency file is pipe-delimited")
    if extra.get("encoding") != "utf-8":
        add("ADJACENCY_ENCODING", "Census adjacency file is UTF-8")
    if extra.get("source_file_name") != SOURCE_FILE_NAME:
        add("ADJACENCY_FILE_NAME", "Census adjacency file name must be county_adjacency2025.txt")
    if str(extra.get("source_vintage")) != SOURCE_VINTAGE:
        add("ADJACENCY_VINTAGE", "Census adjacency vintage must be 2025")
    if extra.get("license_basis") != LICENSE_BASIS:
        add("ADJACENCY_LICENSE", "Census adjacency license basis must match the contract")
    if extra.get("reject_extra_fields") is not True:
        add("ADJACENCY_ROW_WIDTH", "Census adjacency rows must match the header width")
    if definition.required_columns != REQUIRED_COLUMNS:
        add(
            "ADJACENCY_COLUMNS", "Census adjacency required columns must match the publisher header"
        )
    if definition.incremental_strategy != "FULL_REFRESH":
        add("ADJACENCY_REFRESH", "Census adjacency uses a full refresh")
    if extra.get("onboarding_mode") != "ROUTINE_PUBLIC":
        add("ADJACENCY_ONBOARDING", "Census adjacency is a routine public source")
    if definition.geography_semantics != "COUNTY_FIPS_5":
        add("ADJACENCY_GEOGRAPHY", "Census adjacency geography is five-character county FIPS")
    declared = {rule.rule_id for rule in definition.quality_rules}
    if not set(QUALITY_RULE_IDS) <= declared:
        add("ADJACENCY_QUALITY_RULES", "Census adjacency blocking quality rules are required")
    if any(rule.severity != "BLOCKING" for rule in definition.quality_rules):
        add("ADJACENCY_QUALITY_SEVERITY", "Census adjacency quality rules are blocking")
    return issues


def conform_published_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    reference: frozenset[str],
) -> ConformResult:
    """Build undirected in-scope pairs or raise a stable rejection code."""
    if not rows:
        raise CountyAdjacencyError("EMPTY_FILE")
    published = tuple(_published_row(row) for row in rows)
    directed: dict[tuple[str, str], Decimal] = {}
    blank_counties: set[str] = set()
    seen: set[str] = set()
    for row in published:
        _require_fips(row.county_geoid)
        seen.add(row.county_geoid)
        neighbor = row.neighbor_geoid
        if neighbor == "":
            if row.neighbor_name != "" or row.length_text != "":
                raise CountyAdjacencyError("PARTIAL_NEIGHBOR")
            if row.county_geoid in blank_counties:
                raise CountyAdjacencyError("DUPLICATE_DIRECTED")
            blank_counties.add(row.county_geoid)
            continue
        _require_fips(neighbor)
        if not _LENGTH.fullmatch(row.length_text):
            raise CountyAdjacencyError("LENGTH_TEXT")
        if neighbor == row.county_geoid:
            raise CountyAdjacencyError("SELF_PAIR")
        key = (row.county_geoid, neighbor)
        if key in directed:
            raise CountyAdjacencyError("DUPLICATE_DIRECTED")
        directed[key] = Decimal(row.length_text)
    if blank_counties & {county for county, _neighbor in directed}:
        raise CountyAdjacencyError("PARTIAL_NEIGHBOR")
    for (county, neighbor), length in directed.items():
        reverse = directed.get((neighbor, county))
        if reverse is None:
            raise CountyAdjacencyError("ASYMMETRIC_PAIR")
        if reverse != length:
            raise CountyAdjacencyError("LENGTH_MISMATCH")
    missing = reference - seen
    if missing:
        raise CountyAdjacencyError("MISSING_COUNTY")
    pairs: dict[tuple[str, str], GovernedPair] = {}
    for (county, neighbor), length in directed.items():
        county_in = county in reference
        neighbor_in = neighbor in reference
        if not county_in and not neighbor_in:
            continue
        if county_in != neighbor_in:
            raise CountyAdjacencyError("CROSS_SCOPE")
        ordered = (county, neighbor) if county < neighbor else (neighbor, county)
        contact = "POINT" if length == 0 else "EDGE"
        pair = GovernedPair(ordered[0], ordered[1], _boundary_text(length), contact)
        prior = pairs.get(ordered)
        if prior is not None and prior != pair:
            raise CountyAdjacencyError("LENGTH_MISMATCH")
        pairs[ordered] = pair
    ordered_pairs = tuple(pairs[key] for key in sorted(pairs))
    islands = tuple(sorted(reference & blank_counties))
    edge_count = sum(pair.contact_type == "EDGE" for pair in ordered_pairs)
    point_count = sum(pair.contact_type == "POINT" for pair in ordered_pairs)
    result = ConformResult(published, ordered_pairs, islands, edge_count, point_count)
    _enforce_canonical(result, reference)
    return result


def prepare_load(
    records: Sequence[Mapping[str, Any]],
    *,
    artifact_sha256: str | None,
    ingestion_run_id: str,
    retrieved_at: datetime,
    reference: frozenset[str] | None = None,
) -> PreparedLoad:
    """Validate the pinned bytes and the published rows before any write."""
    if artifact_sha256 != PINNED_SHA256:
        raise CountyAdjacencyError("SHA256_MISMATCH")
    if _RUN_ID.fullmatch(ingestion_run_id) is None:
        raise CountyAdjacencyError("RUN_ID")
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise CountyAdjacencyError("RETRIEVED_AT")
    rows = _record_mappings(records)
    counties = project_counties() if reference is None else reference
    return PreparedLoad(
        conform_published_rows(rows, reference=counties),
        artifact_sha256,
        ingestion_run_id,
        retrieved_at,
    )


def apply_prepared_load(
    cursor: Any,
    prepared: PreparedLoad,
    *,
    environment: str,
) -> MergeReceipt:
    """MERGE governed pairs on (RELEASE_ID, FIPS_A, FIPS_B) and raw published rows."""
    database = database_name(environment)
    existing_pairs = _existing_pairs(cursor, database)
    existing_raw = _existing_raw(cursor, database)
    inserted, updated, deleted, pair_statements = _governed_delta(
        database, prepared, existing_pairs
    )
    raw_statements = _raw_delta(database, prepared, existing_raw)
    if inserted == updated == deleted == 0 and not raw_statements:
        return _receipt(prepared, 0, 0, 0)
    for sql, params in (*pair_statements, *raw_statements):
        cursor.execute(sql, params)
    return _receipt(prepared, inserted, updated, deleted)


def quality_results(
    definition: Any,
    records: Iterable[Mapping[str, Any]],
    *,
    reference: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate adjacency rules. Observed values are codes and FIPS lists only."""
    counties = project_counties() if reference is None else reference
    try:
        result = conform_published_rows(_record_mappings(records), reference=counties)
    except CountyAdjacencyError as error:
        return _failed_results(definition, error.code)
    results = _passed_results(definition, result)
    if definition.extra.get("artifact_sha256") != PINNED_SHA256:
        for item in results:
            if item["rule_id"] == "census_adjacency_checksum":
                item["status"] = "FAILED"
                item["observed"] = {"code": "SHA256_MISMATCH"}
    return results


def _receipt(prepared: PreparedLoad, inserted: int, updated: int, deleted: int) -> MergeReceipt:
    result = prepared.result
    return MergeReceipt(
        inserted,
        updated,
        deleted,
        len(result.pairs),
        result.edge_count,
        result.point_count,
        result.islands,
    )


def _record_mappings(records: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for item in records:
        record = item.get("record") if isinstance(item, Mapping) else None
        if isinstance(record, Mapping):
            rows.append(record)
        elif isinstance(item, Mapping) and "County GEOID" in item:
            rows.append(item)
        else:
            raise CountyAdjacencyError("MISSING_COLUMNS")
    return rows


def _published_row(row: Mapping[str, Any]) -> PublishedRow:
    if set(row) != set(REQUIRED_COLUMNS):
        raise CountyAdjacencyError("MISSING_COLUMNS")
    values: list[str] = []
    for column in REQUIRED_COLUMNS:
        value = row.get(column)
        if not isinstance(value, str):
            raise CountyAdjacencyError("MISSING_COLUMNS")
        values.append(value.strip())
    return PublishedRow(values[0], values[1], values[2], values[3], values[4])


def _require_fips(value: str) -> None:
    if _FIPS.fullmatch(value) is None:
        raise CountyAdjacencyError("FIPS_SHAPE")


def _boundary_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _enforce_canonical(result: ConformResult, reference: frozenset[str]) -> None:
    if reference != project_counties():
        return
    if len(result.pairs) != EXPECTED_UNDIRECTED_PAIRS:
        raise CountyAdjacencyError("PAIR_COUNT")
    if result.edge_count != EXPECTED_EDGE_PAIRS or result.point_count != EXPECTED_POINT_PAIRS:
        raise CountyAdjacencyError("CONTACT_COUNT")
    if frozenset(result.islands) != EXPECTED_ISLANDS:
        raise CountyAdjacencyError("ISLAND_SET")
    degrees: Counter[str] = Counter()
    for pair in result.pairs:
        degrees[pair.fips_a] += 1
        degrees[pair.fips_b] += 1
        if pair.fips_a[:2] in _EXCLUDED_STATEFP or pair.fips_b[:2] in _EXCLUDED_STATEFP:
            raise CountyAdjacencyError("CROSS_SCOPE")
    for fips in (*CT_PLANNING_REGIONS, *AK_SPLIT):
        if degrees[fips] < 1:
            raise CountyAdjacencyError("STATE_DEGREE")


def _existing_pairs(cursor: Any, database: str) -> dict[tuple[str, str], tuple[str, str, str, str]]:
    cursor.execute(
        f"""SELECT FIPS_A, FIPS_B, TO_VARCHAR(SHARED_BOUNDARY_M), CONTACT_TYPE,
                   SOURCE_VINTAGE, SOURCE_SHA256
            FROM {database}.CONFORMED.COUNTY_ADJACENCY
            WHERE RELEASE_ID = %s""",
        (RELEASE_ID,),
    )
    rows = cursor.fetchall()
    if rows is None:
        raise CountyAdjacencyError("LEDGER_SHAPE")
    found: dict[tuple[str, str], tuple[str, str, str, str]] = {}
    for row in rows:
        if not isinstance(row, tuple) or len(row) != 6:
            raise CountyAdjacencyError("LEDGER_SHAPE")
        fips_a, fips_b, boundary, contact, vintage, digest = (str(item) for item in row)
        found[(fips_a, fips_b)] = (boundary, contact, vintage, digest)
    return found


def _existing_raw(cursor: Any, database: str) -> dict[tuple[str, str], tuple[str, str, str]]:
    cursor.execute(
        f"""SELECT COUNTY_GEOID, NEIGHBOR_GEOID, COUNTY_NAME, NEIGHBOR_NAME,
                   BOUNDARY_LENGTH_TEXT
            FROM {database}.RAW.CENSUS_COUNTY_ADJACENCY_2025
            WHERE SOURCE_SHA256 = %s""",
        (PINNED_SHA256,),
    )
    rows = cursor.fetchall()
    if rows is None:
        raise CountyAdjacencyError("LEDGER_SHAPE")
    found: dict[tuple[str, str], tuple[str, str, str]] = {}
    for row in rows:
        if not isinstance(row, tuple) or len(row) != 5:
            raise CountyAdjacencyError("LEDGER_SHAPE")
        county, neighbor, county_name, neighbor_name, length_text = (str(item) for item in row)
        found[(county, neighbor)] = (county_name, neighbor_name, length_text)
    return found


def _governed_delta(
    database: str,
    prepared: PreparedLoad,
    existing: Mapping[tuple[str, str], tuple[str, str, str, str]],
) -> tuple[int, int, int, list[tuple[str, tuple[Any, ...]]]]:
    desired = {
        (pair.fips_a, pair.fips_b): (
            pair.shared_boundary_m,
            pair.contact_type,
            SOURCE_VINTAGE,
            prepared.artifact_sha256,
        )
        for pair in prepared.result.pairs
    }
    inserts: list[GovernedPair] = []
    updates: list[GovernedPair] = []
    for pair in prepared.result.pairs:
        key = (pair.fips_a, pair.fips_b)
        current = existing.get(key)
        if current is None:
            inserts.append(pair)
        elif _boundary_changed(current[0], pair.shared_boundary_m) or current[1:] != (
            pair.contact_type,
            SOURCE_VINTAGE,
            prepared.artifact_sha256,
        ):
            updates.append(pair)
    deletes = [key for key in existing if key not in desired]
    statements: list[tuple[str, tuple[Any, ...]]] = []
    statements.extend(_delete_pairs(database, deletes))
    statements.extend(_merge_pairs(database, prepared, [*updates, *inserts]))
    return len(inserts), len(updates), len(deletes), statements


def _boundary_changed(stored: str, desired: str) -> bool:
    try:
        return Decimal(stored) != Decimal(desired)
    except ArithmeticError:
        return True


def _merge_pairs(
    database: str,
    prepared: PreparedLoad,
    pairs: Sequence[GovernedPair],
) -> list[tuple[str, tuple[Any, ...]]]:
    statements: list[tuple[str, tuple[Any, ...]]] = []
    for start in range(0, len(pairs), _MERGE_BATCH):
        batch = pairs[start : start + _MERGE_BATCH]
        values = ",\n".join("(" + ", ".join(["%s"] * 8) + ")" for _ in batch)
        params: list[Any] = []
        for pair in batch:
            params.extend(
                (
                    RELEASE_ID,
                    pair.fips_a,
                    pair.fips_b,
                    pair.shared_boundary_m,
                    pair.contact_type,
                    SOURCE_VINTAGE,
                    prepared.artifact_sha256,
                    prepared.ingestion_run_id,
                )
            )
        sql = f"""MERGE INTO {database}.CONFORMED.COUNTY_ADJACENCY target
USING (
    SELECT column1 AS RELEASE_ID, column2 AS FIPS_A, column3 AS FIPS_B,
           TO_NUMBER(column4, 38, 6) AS SHARED_BOUNDARY_M, column5 AS CONTACT_TYPE,
           column6 AS SOURCE_VINTAGE, column7 AS SOURCE_SHA256,
           column8 AS INGESTION_RUN_ID
    FROM VALUES
    {values}
) source
ON target.RELEASE_ID = source.RELEASE_ID
 AND target.FIPS_A = source.FIPS_A
 AND target.FIPS_B = source.FIPS_B
WHEN MATCHED AND (
        target.SHARED_BOUNDARY_M <> source.SHARED_BOUNDARY_M
     OR target.CONTACT_TYPE <> source.CONTACT_TYPE
     OR target.SOURCE_VINTAGE <> source.SOURCE_VINTAGE
     OR target.SOURCE_SHA256 <> source.SOURCE_SHA256
) THEN UPDATE SET
    SHARED_BOUNDARY_M = source.SHARED_BOUNDARY_M,
    CONTACT_TYPE = source.CONTACT_TYPE,
    SOURCE_VINTAGE = source.SOURCE_VINTAGE,
    SOURCE_SHA256 = source.SOURCE_SHA256,
    INGESTION_RUN_ID = source.INGESTION_RUN_ID
WHEN NOT MATCHED THEN INSERT (
    RELEASE_ID, FIPS_A, FIPS_B, SHARED_BOUNDARY_M, CONTACT_TYPE,
    SOURCE_VINTAGE, SOURCE_SHA256, INGESTION_RUN_ID
) VALUES (
    source.RELEASE_ID, source.FIPS_A, source.FIPS_B, source.SHARED_BOUNDARY_M,
    source.CONTACT_TYPE, source.SOURCE_VINTAGE, source.SOURCE_SHA256,
    source.INGESTION_RUN_ID
)"""
        statements.append((sql, tuple(params)))
    return statements


def _delete_pairs(
    database: str, keys: Sequence[tuple[str, str]]
) -> list[tuple[str, tuple[Any, ...]]]:
    statements: list[tuple[str, tuple[Any, ...]]] = []
    for start in range(0, len(keys), _MERGE_BATCH):
        batch = keys[start : start + _MERGE_BATCH]
        clauses = " OR ".join("(FIPS_A = %s AND FIPS_B = %s)" for _ in batch)
        params: list[Any] = [RELEASE_ID]
        for fips_a, fips_b in batch:
            params.extend((fips_a, fips_b))
        sql = f"""DELETE FROM {database}.CONFORMED.COUNTY_ADJACENCY
WHERE RELEASE_ID = %s AND ({clauses})"""
        statements.append((sql, tuple(params)))
    return statements


def _raw_delta(
    database: str,
    prepared: PreparedLoad,
    existing: Mapping[tuple[str, str], tuple[str, str, str]],
) -> list[tuple[str, tuple[Any, ...]]]:
    desired = {
        (row.county_geoid, row.neighbor_geoid): (
            row.county_name,
            row.neighbor_name,
            row.length_text,
        )
        for row in prepared.result.published
    }
    changed = [
        row
        for row in prepared.result.published
        if existing.get((row.county_geoid, row.neighbor_geoid))
        != (row.county_name, row.neighbor_name, row.length_text)
    ]
    removed = [key for key in existing if key not in desired]
    statements: list[tuple[str, tuple[Any, ...]]] = []
    statements.extend(_delete_raw(database, removed))
    statements.extend(_merge_raw(database, prepared, changed))
    return statements


def _merge_raw(
    database: str, prepared: PreparedLoad, rows: Sequence[PublishedRow]
) -> list[tuple[str, tuple[Any, ...]]]:
    statements: list[tuple[str, tuple[Any, ...]]] = []
    for start in range(0, len(rows), _MERGE_BATCH):
        batch = rows[start : start + _MERGE_BATCH]
        values = ",\n".join("(" + ", ".join(["%s"] * 12) + ")" for _ in batch)
        params: list[Any] = []
        for row in batch:
            params.extend(
                (
                    prepared.artifact_sha256,
                    row.county_name,
                    row.county_geoid,
                    row.neighbor_name,
                    row.neighbor_geoid,
                    row.length_text,
                    prepared.ingestion_run_id,
                    SOURCE_URL,
                    SOURCE_FILE_NAME,
                    SOURCE_VINTAGE,
                    LICENSE_BASIS,
                    prepared.retrieved_at,
                )
            )
        sql = f"""MERGE INTO {database}.RAW.CENSUS_COUNTY_ADJACENCY_2025 target
USING (
    SELECT column1 AS SOURCE_SHA256, column2 AS COUNTY_NAME, column3 AS COUNTY_GEOID,
           column4 AS NEIGHBOR_NAME, column5 AS NEIGHBOR_GEOID,
           column6 AS BOUNDARY_LENGTH_TEXT, column7 AS INGESTION_RUN_ID,
           column8 AS SOURCE_URL, column9 AS SOURCE_FILE_NAME,
           column10 AS SOURCE_VINTAGE, column11 AS LICENSE_BASIS,
           column12 AS RETRIEVED_AT
    FROM VALUES
    {values}
) source
ON target.SOURCE_SHA256 = source.SOURCE_SHA256
 AND target.COUNTY_GEOID = source.COUNTY_GEOID
 AND target.NEIGHBOR_GEOID = source.NEIGHBOR_GEOID
WHEN MATCHED AND (
        target.COUNTY_NAME <> source.COUNTY_NAME
     OR target.NEIGHBOR_NAME <> source.NEIGHBOR_NAME
     OR target.BOUNDARY_LENGTH_TEXT <> source.BOUNDARY_LENGTH_TEXT
     OR target.SOURCE_URL <> source.SOURCE_URL
     OR target.SOURCE_FILE_NAME <> source.SOURCE_FILE_NAME
     OR target.SOURCE_VINTAGE <> source.SOURCE_VINTAGE
     OR target.LICENSE_BASIS <> source.LICENSE_BASIS
) THEN UPDATE SET
    COUNTY_NAME = source.COUNTY_NAME,
    NEIGHBOR_NAME = source.NEIGHBOR_NAME,
    BOUNDARY_LENGTH_TEXT = source.BOUNDARY_LENGTH_TEXT,
    INGESTION_RUN_ID = source.INGESTION_RUN_ID,
    SOURCE_URL = source.SOURCE_URL,
    SOURCE_FILE_NAME = source.SOURCE_FILE_NAME,
    SOURCE_VINTAGE = source.SOURCE_VINTAGE,
    LICENSE_BASIS = source.LICENSE_BASIS,
    RETRIEVED_AT = source.RETRIEVED_AT
WHEN NOT MATCHED THEN INSERT (
    SOURCE_SHA256, COUNTY_NAME, COUNTY_GEOID, NEIGHBOR_NAME, NEIGHBOR_GEOID,
    BOUNDARY_LENGTH_TEXT, INGESTION_RUN_ID, SOURCE_URL, SOURCE_FILE_NAME,
    SOURCE_VINTAGE, LICENSE_BASIS, RETRIEVED_AT
) VALUES (
    source.SOURCE_SHA256, source.COUNTY_NAME, source.COUNTY_GEOID, source.NEIGHBOR_NAME,
    source.NEIGHBOR_GEOID, source.BOUNDARY_LENGTH_TEXT, source.INGESTION_RUN_ID,
    source.SOURCE_URL, source.SOURCE_FILE_NAME, source.SOURCE_VINTAGE,
    source.LICENSE_BASIS, source.RETRIEVED_AT
)"""
        statements.append((sql, tuple(params)))
    return statements


def _delete_raw(
    database: str, keys: Sequence[tuple[str, str]]
) -> list[tuple[str, tuple[Any, ...]]]:
    statements: list[tuple[str, tuple[Any, ...]]] = []
    for start in range(0, len(keys), _MERGE_BATCH):
        batch = keys[start : start + _MERGE_BATCH]
        clauses = " OR ".join("(COUNTY_GEOID = %s AND NEIGHBOR_GEOID = %s)" for _ in batch)
        params: list[Any] = [PINNED_SHA256]
        for county, neighbor in batch:
            params.extend((county, neighbor))
        sql = f"""DELETE FROM {database}.RAW.CENSUS_COUNTY_ADJACENCY_2025
WHERE SOURCE_SHA256 = %s AND ({clauses})"""
        statements.append((sql, tuple(params)))
    return statements


def _severity(definition: Any, rule_id: str) -> str:
    for rule in definition.quality_rules:
        if rule.rule_id == rule_id:
            return str(rule.severity)
    return "BLOCKING"


def _passed_results(definition: Any, result: ConformResult) -> list[dict[str, Any]]:
    observed: dict[str, dict[str, Any]] = {
        "census_adjacency_required_fields": {"row_count": len(result.published)},
        "census_adjacency_identity": {"self_pairs": 0, "invalid_fips": 0},
        "census_adjacency_symmetry": {"asymmetric_pairs": 0},
        "census_adjacency_scope": {
            "pair_count": len(result.pairs),
            "edge_count": result.edge_count,
            "point_count": result.point_count,
        },
        "census_adjacency_checksum": {"artifact_sha256": PINNED_SHA256},
        "census_adjacency_islands": {"islands": list(result.islands), "stored_as_pairs": 0},
    }
    expected: dict[str, dict[str, Any]] = {
        "census_adjacency_required_fields": {"missing_columns": 0},
        "census_adjacency_identity": {"self_pairs": 0, "invalid_fips": 0},
        "census_adjacency_symmetry": {"asymmetric_pairs": 0},
        "census_adjacency_scope": {"outside_reference": 0},
        "census_adjacency_checksum": {"artifact_sha256": PINNED_SHA256},
        "census_adjacency_islands": {"stored_as_pairs": 0},
    }
    return [
        {
            "rule_id": rule_id,
            "severity": _severity(definition, rule_id),
            "status": "PASSED",
            "expected": expected[rule_id],
            "observed": observed[rule_id],
        }
        for rule_id in QUALITY_RULE_IDS
    ]


def _failed_results(definition: Any, code: str) -> list[dict[str, Any]]:
    implicated = _CODE_RULE.get(code, "census_adjacency_scope")
    ordered = [implicated, *[rule_id for rule_id in QUALITY_RULE_IDS if rule_id != implicated]]
    results: list[dict[str, Any]] = []
    for rule_id in ordered:
        failed = rule_id == implicated
        results.append(
            {
                "rule_id": rule_id,
                "severity": _severity(definition, rule_id),
                "status": "FAILED",
                "expected": {"code": code if failed else "EVALUATED"},
                "observed": {"code": code if failed else "NOT_EVALUATED"},
            }
        )
    return results
