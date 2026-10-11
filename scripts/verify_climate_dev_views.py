"""Read-only postapply proof using the existing protected DEV migration service."""

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from lyme_gap_atlas_data.climate_dev_validation import DEV, ROLE, USER, WAREHOUSE

NAMES = (
    "CURRENT_CLIMATE_COUNTY_DAY_OBSERVATIONS_V",
    "CURRENT_CLIMATE_MEASURE_METADATA_V",
)
CHECKSUM = "f3a33d21cba33f27a4e1683b65f9295f33c796f445c8c9ed82c84bd16948b2c2"


def body(sql: str) -> str:
    token_pattern = r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*|/\*.*?\*/)"
    tokens = re.split(token_pattern, sql, flags=re.S)
    sql = "".join(" " if part.startswith(("--", "/*")) else part for part in tokens)
    match = re.search(r"\bAS\s+((?:WITH|SELECT)\b.*)", sql, re.I | re.S)
    if not match:
        raise ValueError("CLIMATE_VIEW_BODY")
    parts = re.split(token_pattern, match[1].rstrip().rstrip(";"), flags=re.S)
    return "".join(
        part if index % 2 else re.sub(r"\s+", " ", part) for index, part in enumerate(parts)
    ).strip()


def proposals(sql: str) -> list[str]:
    # The reviewed day-convention string and comments contain semicolons.
    # Split only at the two explicit view-definition boundaries.
    return re.split(r"(?=CREATE OR REPLACE VIEW\b)", sql, flags=re.I)[1:]


def rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def verify(cursor: Any, sql: str) -> dict[str, Any]:
    cursor.execute("SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()")
    if cursor.fetchone() != (USER, ROLE, DEV, WAREHOUSE):
        raise ValueError("CLIMATE_VIEW_IDENTITY")
    cursor.execute("SELECT filename,sha256 FROM GOVERNANCE.SCHEMA_MIGRATIONS WHERE version='V136'")
    if cursor.fetchall() != [("V136__dev_january_climate_consumer_views.sql", CHECKSUM)]:
        raise ValueError("CLIMATE_VIEW_LEDGER")
    reviewed = proposals(sql)
    views = []
    for name, proposal in zip(NAMES, reviewed, strict=True):
        qualified = f"{DEV}.PRESENTATION.{name}"
        cursor.execute(f"SELECT GET_DDL('VIEW','{qualified}')")
        ddl = cursor.fetchone()[0]
        cursor.execute(f"DESCRIBE VIEW {qualified}")
        description = rows(cursor)
        if name == NAMES[0]:
            # The published view joins the complete January capture list. A full
            # count exceeded the protected query timeout; sample actual rows.
            cursor.execute(
                f"SELECT RELEASE_ID, MEASURE_ID, COUNTY_FIPS, PERIOD_START, "
                f"VALUE, VALUE_STATE, UNIT FROM {qualified} LIMIT 4"
            )
            sample = rows(cursor)
            if not sample:
                raise ValueError("CLIMATE_OBSERVATIONS_EMPTY")
            count = None
        else:
            cursor.execute(f"SELECT COUNT(*) FROM {qualified}")
            count = cursor.fetchone()[0]
            sample = []
        cursor.execute(f"SHOW GRANTS ON VIEW {qualified}")
        grants = rows(cursor)
        cursor.execute(f"SHOW VIEWS LIKE '{name}' IN SCHEMA {DEV}.PRESENTATION")
        catalog = rows(cursor)
        views.append(
            {
                "name": name,
                "ddl": ddl,
                "normalized_body_matches_reviewed": body(ddl) == body(proposal),
                "ddl_sha256": hashlib.sha256(ddl.encode()).hexdigest(),
                "description": description,
                "successful_row_count": count,
                "bounded_sample": sample,
                "existing_grants": grants,
                "catalog": catalog,
            }
        )
    cursor.execute(f"SHOW TABLES LIKE 'CLIMATE_VALIDATION_%' IN SCHEMA {DEV}.PRESENTATION")
    temporary_visible = rows(cursor)
    history: dict[str, Any]
    try:
        cursor.execute(
            "SELECT query_id,start_time,user_name,role_name,query_type,query_text,error_code "
            "FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_USER(RESULT_LIMIT=>10000)) "
            "WHERE start_time >= DATEADD('day',-7,CURRENT_TIMESTAMP()) "
            "AND query_type IN ('CREATE_VIEW','GRANT','REVOKE','DROP_VIEW') "
            "AND (query_text ILIKE '%CURRENT_CLIMATE_COUNTY_DAY_OBSERVATIONS_V%' "
            "OR query_text ILIKE '%CURRENT_CLIMATE_MEASURE_METADATA_V%') "
            "ORDER BY start_time LIMIT 100"
        )
        history = {"status": "SUCCESS", "rows": rows(cursor)}
    except Exception as exc:
        history = {"status": "UNAVAILABLE", "error_type": type(exc).__name__}
    return {
        "mode": "READ_ONLY_DEV_POSTAPPLY",
        "code_sha": os.environ.get("GITHUB_SHA", "UNKNOWN"),
        "v136_checksum": CHECKSUM,
        "views": views,
        "validation_tables_visible_in_this_session": temporary_visible,
        "history": history,
        "history_limitations": "Current service user, seven days, latest 10000 queries; "
        "not account-complete. CREATE OR REPLACE resets creation metadata; current grants "
        "and timestamps cannot prove no prior grants or definitions were replaced.",
        "writes": False,
    }


def main() -> None:
    sql = (Path(__file__).parents[1] / "sql/january_climate_consumer_views.sql").read_text()
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        report = verify(cursor, sql)
    print(json.dumps(report, sort_keys=True, default=str))
    if not all(view["normalized_body_matches_reviewed"] for view in report["views"]):
        raise SystemExit("CLIMATE_COMPILED_BODY_DIFF_REVIEW_REQUIRED")


if __name__ == "__main__":
    main()
