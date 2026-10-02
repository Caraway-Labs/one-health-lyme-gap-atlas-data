"""Fixed, opt-in DEV SELECT recipes; no writes, objects, grants or procedure calls."""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
from datetime import datetime
from typing import Any

CONNECTION = "ATLAS_DEV_READ"
ROLE = "OH_LYME_DEV_READ"
DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
CONNECTOR_VERSION = "4.3.0"  # uv.lock; a different driver requires reviewed recipe evidence.
IDENTITY_SQL = (
    "SELECT CURRENT_USER() AS CURRENT_USER, CURRENT_ROLE() AS CURRENT_ROLE, "
    "CURRENT_DATABASE() AS CURRENT_DATABASE, CURRENT_WAREHOUSE() AS CURRENT_WAREHOUSE, "
    "CURRENT_VERSION() AS ENGINE_VERSION"
)
FIXTURES = (
    ('{"fixture":"alpha","county":"01001"}', "2026-01-02T03:04:05+00:00"),
    ('{"fixture":"O\'Brien","unknown":null}', "2026-01-03T03:04:05+00:00"),
)
SELECT_BATCH_SQL = "SELECT PARSE_JSON(%s), TO_TIMESTAMP_TZ(%s)"
SCRIPTING_SQL = """EXECUTE IMMEDIATE $$
DECLARE
  payload_text VARCHAR DEFAULT %s;
  timestamp_text VARCHAR DEFAULT %s;
  result VARIANT;
BEGIN
  SELECT OBJECT_CONSTRUCT('payload', PARSE_JSON(:payload_text),
    'stamp', TO_VARCHAR(TO_TIMESTAMP_TZ(:timestamp_text),
                       'YYYY-MM-DD"T"HH24:MI:SSTZH:TZM')) INTO :result;
  RETURN result;
END; $$"""
COVERAGE_SQL = """WITH canonical(county) AS (
  SELECT column1 FROM VALUES ('01001'), ('01003'), ('01005')
), source(county) AS (
  SELECT column1 FROM VALUES ('01001'), ('01003'), ('01999')
)
SELECT
  (SELECT COUNT(*) FROM canonical),
  (SELECT COUNT(*) FROM canonical JOIN source USING (county)),
  (SELECT ARRAY_AGG(OBJECT_CONSTRUCT('county', county, 'state', 'UNKNOWN'))
   FROM canonical WHERE county NOT IN (SELECT county FROM source)),
  (SELECT ARRAY_AGG(county) FROM source WHERE county NOT IN (SELECT county FROM canonical))
"""


def same_timestamp(actual: str | datetime, expected: str) -> bool:
    value = datetime.fromisoformat(actual) if isinstance(actual, str) else actual
    return value.tzinfo is not None and value == datetime.fromisoformat(expected)


def cursor_checks(cursor: Any) -> dict[str, str]:
    """Only fixed fixtures and fixed read-only statements; no caller-provided SQL."""
    cursor.execute("SELECT CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()")
    if cursor.fetchone() != (ROLE, DATABASE, "OH_LYME_DEV_INGEST_XS_WH"):
        raise ValueError("unexpected driver identity")
    cursor.executemany(SELECT_BATCH_SQL, FIXTURES)
    payload, stamp = cursor.fetchone()
    batch_pass = json.loads(payload) == json.loads(FIXTURES[-1][0]) and same_timestamp(
        stamp, FIXTURES[-1][1]
    )
    cursor.execute(SCRIPTING_SQL, FIXTURES[-1])
    result = json.loads(cursor.fetchone()[0])
    scripting_pass = result["payload"] == json.loads(FIXTURES[-1][0]) and same_timestamp(
        result["stamp"], FIXTURES[-1][1]
    )
    cursor.execute(COVERAGE_SQL)
    total, matched, missing, extra = cursor.fetchone()
    coverage_pass = (
        total == 3
        and matched == 2
        and json.loads(missing) == [{"county": "01005", "state": "UNKNOWN"}]
        and json.loads(extra) == ["01999"]
    )
    return {
        "driver_executemany_select": "PASS" if batch_pass else "FAIL",
        "anonymous_scripting_bind": "PASS" if scripting_pass else "FAIL",
        "canonical_select_fixture": "PASS" if coverage_pass else "FAIL",
    }


def verify_dev() -> dict[str, Any]:
    import snowflake.connector

    logging.getLogger("snowflake").setLevel(logging.CRITICAL)
    report: dict[str, Any] = {
        "evidence_class": "authorized_DEV_read_only",
        "connection": CONNECTION,
        "connector_version": snowflake.connector.__version__,
        "mutation_started": False,
        "bulk_insert_engine_proof": "UNVERIFIED",
        "caller_owner_procedure_proof": "UNVERIFIED",
        "role_allow_deny_proof": "UNVERIFIED",
        "parity_procedure_proof": "UNVERIFIED",
    }
    if snowflake.connector.__version__ != CONNECTOR_VERSION:
        return {**report, "status": "BLOCKED", "reason": "DRIVER_VERSION_NOT_REVIEWED"}
    try:
        observation = subprocess.run(
            [
                "snow",
                "sql",
                "--connection",
                CONNECTION,
                "--format",
                "json",
                "--query",
                IDENTITY_SQL,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=45,
        )
        rows = json.loads(observation.stdout)
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("unexpected identity shape")
        identity = rows[0]
        if (
            identity.get("CURRENT_ROLE") != ROLE
            or identity.get("CURRENT_DATABASE") != DATABASE
            or identity.get("CURRENT_WAREHOUSE") != "OH_LYME_DEV_INGEST_XS_WH"
            or not identity.get("CURRENT_USER")
        ):
            return {**report, "status": "BLOCKED", "reason": "UNEXPECTED_DEV_IDENTITY"}
        engine_version = identity.get("ENGINE_VERSION")
        if (
            not isinstance(engine_version, str)
            or re.fullmatch(r"[0-9.]{1,24}", engine_version) is None
        ):
            raise ValueError("unexpected engine version")
        # Retain bounded public environment facts, never the actual user or raw CLI diagnostics.
        report["identity"] = {
            "user_observed": bool(identity.get("CURRENT_USER")),
            "role": ROLE,
            "database": DATABASE,
            "warehouse_expected": identity.get("CURRENT_WAREHOUSE") == "OH_LYME_DEV_INGEST_XS_WH",
            "engine_version": engine_version,
        }
        with (
            snowflake.connector.connect(
                connection_name=CONNECTION,
                authenticator="PROGRAMMATIC_ACCESS_TOKEN",  # never trigger external-browser fallback
                paramstyle="pyformat",
                login_timeout=15,
                network_timeout=15,
            ) as connection,
            connection.cursor() as cursor,
        ):
            report.update(cursor_checks(cursor))
        report["status"] = (
            "PASS"
            if all(
                report[key] == "PASS"
                for key in (
                    "driver_executemany_select",
                    "anonymous_scripting_bind",
                    "canonical_select_fixture",
                )
            )
            else "FAIL"
        )
    except Exception:
        # Neither exception text, stderr, SQL parameters nor config values enter the packet.
        report.update(status="UNKNOWN", reason="READ_ONLY_CHECK_UNAVAILABLE")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect-dev", action="store_true", required=True)
    parser.parse_args()
    result = verify_dev()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
