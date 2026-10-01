"""Execute actual view numeric expressions in an offline Snowflake-shaped harness.

This verifies query/connector handling, not Snowflake compilation or live grants.
AS_DOUBLE deliberately coerces DECIMAL in this harness, matching observed runtime.
"""

from __future__ import annotations

import json
import re
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from lyme_gap_atlas_data.climate_numeric import FIELDS, decode_numeric_fields

SQL = (Path(__file__).parents[1] / "sql/january_climate_consumer_views.sql").read_text()


def query_row(kind: str, value: str | None) -> tuple[dict, bool]:
    marker = json.dumps({"kind": kind, "value": value}) if kind else None

    def unpack(item):
        return json.loads(item) if item is not None else {"kind": None, "value": None}

    with sqlite3.connect(":memory:") as connection:
        connection.create_function("VARIANT_FIELD", 1, lambda field: marker)
        connection.create_function(
            "IS_NULL_VALUE", 1, lambda item: unpack(item)["kind"] == "NULL_VALUE"
        )
        connection.create_function("TYPEOF", 1, lambda item: unpack(item)["kind"])
        connection.create_function(
            "AS_DOUBLE",
            1,
            lambda item: (
                float(unpack(item)["value"]) if unpack(item)["value"] is not None else None
            ),
        )
        connection.create_function("IFF", 3, lambda test, yes, no: yes if test else no)
        aliases = {field for field in FIELDS} | {
            f"{field}_{suffix}" for field in FIELDS for suffix in ("stored_type", "native_double")
        }
        expressions = []
        for line in SQL.splitlines():
            match = re.fullmatch(r"\s*(.+) AS ([a-z_0-9]+),", line)
            if match and match[2] in aliases:
                expression = re.sub(r"record:([a-z_0-9]+)", r"VARIANT_FIELD('\1')", match[1])
                expressions.append((expression, match[2]))
        assert {alias for _, alias in expressions} == aliases
        result = connection.execute(
            "SELECT " + ",".join(f"{expression} AS {alias}" for expression, alias in expressions)
        )
        row = dict(zip([item[0] for item in result.description], result.fetchone(), strict=True))
        all_sql_null = all(
            connection.execute(f"SELECT ({expression}) IS NULL").fetchone()[0]
            for expression, alias in expressions
            if alias in FIELDS
        )
        # Connector returns VARIANT as JSON scalar text; DOUBLE JSON may be rounded.
        for field in FIELDS:
            if row[field] is not None:
                item = unpack(row[field])
                row[field] = (
                    format(float(item["value"]), ".15g") if kind == "DOUBLE" else item["value"]
                )
        return row, all_sql_null


@pytest.mark.parametrize(
    "kind,value,expected",
    [
        ("DOUBLE", "12.263159578356436", 12.263159578356436),
        ("DOUBLE", "0.0", 0.0),
        ("DOUBLE", "-1.25", -1.25),
        ("INTEGER", "0", 0),
        ("INTEGER", "17", 17),
        ("DECIMAL", "0", Decimal("0")),
        ("DECIMAL", "123456789012345.678901234567", Decimal("123456789012345.678901234567")),
        ("NULL_VALUE", None, None),
        ("", None, None),
    ],
)
def test_all_seven_fields_preserve_storage_precision_and_null(kind, value, expected) -> None:
    row, all_sql_null = query_row(kind, value)
    decoded = decode_numeric_fields(row)
    assert decoded == dict.fromkeys(FIELDS, expected)
    assert all_sql_null is (expected is None)
    if expected is None:
        assert json.loads(json.dumps(decoded)) == dict.fromkeys(FIELDS, None)
    if kind != "DOUBLE":
        assert all(row[f"{field}_native_double"] is None for field in FIELDS)
    assert not any(key.endswith(("_stored_type", "_native_double")) for key in decoded)


def test_frozen_membership_excludes_appended_matching_run_row() -> None:
    # Execute the actual capture join predicate after its dialect-only substitution.
    predicate = re.search(r"WHERE (v.capture_record_id=member.value::VARCHAR)", SQL)[1]
    predicate = predicate.replace("::VARCHAR", "")
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE records(capture_record_id TEXT, ingestion_run_id TEXT)")
        connection.execute("INSERT INTO records VALUES ('frozen','same-run')")
        query = "SELECT v.capture_record_id FROM records v, json_each(?) member WHERE " + predicate
        before = connection.execute(query, ('["frozen"]',)).fetchall()
        connection.execute("INSERT INTO records VALUES ('appended','same-run')")
        assert connection.execute(query, ('["frozen"]',)).fetchall() == before == [("frozen",)]
