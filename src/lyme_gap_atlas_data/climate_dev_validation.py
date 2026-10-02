"""Bounded DEV checks of reviewed SQL numeric transport and fixture manifest storage.

No semantic release, source approval, grant or pointer is inserted/updated. The
large-manifest test uses one randomly named session-temporary table and removes it.
All sample identities are explicitly non-publishable fixtures.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from decimal import Decimal
from typing import Any

from .climate_numeric import FIELDS, decode_numeric_fields
from .climate_semantics import january_measure_definitions

DEV = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
ROLE = "OH_LYME_DEV_MIGRATION_DEPLOYER"
USER = "OH_LYME_DEV_MIGRATION_DEPLOY_SVC"
WAREHOUSE = "OH_LYME_DEV_INGEST_XS_WH"
CASES = (
    ("double_nonzero", "TO_VARIANT(12.263159578356436::DOUBLE)", 12.263159578356436),
    ("double_zero", "TO_VARIANT(0.0::DOUBLE)", 0.0),
    ("double_negative", "TO_VARIANT(-1.25::DOUBLE)", -1.25),
    ("integer_zero", "TO_VARIANT(0::INTEGER)", 0),
    ("integer_nonzero", "TO_VARIANT(17::INTEGER)", 17),
    ("decimal_zero", "TO_VARIANT(0::NUMBER(38,18))", Decimal("0")),
    (
        "decimal_precision",
        "TO_VARIANT(1234567890123.123456789123456::NUMBER(38,15))",
        Decimal("1234567890123.123456789123456"),
    ),
    ("json_null", "PARSE_JSON('null')", None),
    ("sql_null", "NULL::VARIANT", None),
)


def numeric_expressions(sql: str) -> list[tuple[str, str]]:
    """Use actual reviewed view expressions, not a second codec implementation."""
    aliases = set(FIELDS) | {
        f"{field}_{suffix}" for field in FIELDS for suffix in ("stored_type", "native_double")
    }
    expressions = []
    for line in sql.splitlines():
        match = re.fullmatch(r"\s*(.+) AS ([a-z_0-9]+),", line)
        if match and match[2] in aliases:
            expressions.append((match[1], match[2]))
    if {alias for _, alias in expressions} != aliases or len(expressions) != len(aliases):
        raise ValueError("CLIMATE_DEV_NUMERIC_PROJECTION")
    return expressions


def numeric_query(sql: str, expression: str) -> str:
    fields = ",".join(f"'{field}',{expression}" for field in FIELDS)
    projections = numeric_expressions(sql)
    select = ",".join(f"{value} AS {name}" for value, name in projections)
    nulls = ",".join(
        f"({value}) IS NULL AS {name}_is_sql_null" for value, name in projections if name in FIELDS
    )
    builder = "OBJECT_CONSTRUCT" if expression == "NULL::VARIANT" else "OBJECT_CONSTRUCT_KEEP_NULL"
    return (
        f"WITH records AS (SELECT {builder}({fields}) AS record) "
        f"SELECT {select},{nulls} FROM records"
    )


def _row(cursor: Any) -> dict[str, Any]:
    columns = [str(item[0]).lower() for item in cursor.description]
    result = cursor.fetchone()
    if result is None:
        raise ValueError("CLIMATE_DEV_EMPTY_RESULT")
    return dict(zip(columns, result, strict=True))


def verify_dev(cursor: Any, sql: str, code_sha: str) -> dict[str, Any]:
    """Run only under the existing protected DEV migration service identity."""
    cursor.execute("SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()")
    if cursor.fetchone() != (USER, ROLE, DEV, WAREHOUSE):
        raise ValueError("CLIMATE_DEV_IDENTITY")
    numeric = []
    observed_types: set[str | None] = set()
    for name, expression, expected in CASES:
        cursor.execute(numeric_query(sql, expression))
        row = _row(cursor)
        observed_types.update(row[f"{field}_stored_type"] for field in FIELDS)
        decoded = decode_numeric_fields(row)
        for field in FIELDS:
            if decoded[field] != expected or row[f"{field}_is_sql_null"] is not (expected is None):
                raise ValueError("CLIMATE_DEV_NUMERIC_PARITY")
            if expected is None and json.loads(json.dumps(decoded[field])) is not None:
                raise ValueError("CLIMATE_DEV_JSON_NULL")
        numeric.append({"fixture": name, "numeric_fields_verified": len(FIELDS), "passed": True})
    if not {"DOUBLE", "INTEGER", "DECIMAL"}.issubset(observed_types):
        raise ValueError("CLIMATE_DEV_STORAGE_TYPES")

    fixture: dict[str, Any] = {
        "fixture": True,
        "publication_status": "NOT_PUBLISHABLE_FIXTURE",
        "metadata_review": "PENDING",
        "approved_source_versions": [],
        "definitions": january_measure_definitions(),
        "capture_ids": [f"{index:064x}" for index in range(389856)],
    }
    encoded = json.dumps(fixture, sort_keys=True, separators=(",", ":"))
    table = f"PRESENTATION.CLIMATE_VALIDATION_{uuid.uuid4().hex.upper()}"
    created = False
    try:
        cursor.execute(f"CREATE TEMPORARY TABLE {table} (document VARIANT)")
        created = True
        cursor.execute(f"INSERT INTO {table} SELECT PARSE_JSON(%s)", (encoded,))
        cursor.execute(f"SELECT document FROM {table}")
        returned = cursor.fetchone()
        if returned is None:
            raise ValueError("CLIMATE_DEV_MANIFEST_ROUND_TRIP")
        document = json.loads(returned[0]) if isinstance(returned[0], str) else returned[0]
        if document != fixture:
            raise ValueError("CLIMATE_DEV_MANIFEST_ROUND_TRIP")
    finally:
        if created:
            cursor.execute(f"DROP TABLE {table}")
    return {
        "mode": "FIXTURE_ONLY_NOT_PUBLICATION_AUTHORITY",
        "code_sha": code_sha,
        "numeric_checks": numeric,
        "manifest_bytes": len(encoded.encode()),
        "fixture_capture_ids": len(fixture["capture_ids"]),
        "fixture_manifest_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
        "manifest_round_trip": "PASSED",
        "temporary_table_removed": True,
        "semantic_release_writes": False,
        "pointer_writes": False,
        "grants_changed": False,
    }
