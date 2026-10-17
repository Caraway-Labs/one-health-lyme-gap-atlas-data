"""Fail-closed V154 release/owner invariants, using the existing protected runner."""

import json
from pathlib import Path
from typing import Any

from .climate_release import validate_extension

RELEASE = "governed-2026-10-15-january-climate-prod"
BUNDLE = "53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d"
VIEW = "PRESENTATION.CURRENT_CLIMATE_COUNTY_DAY_OBSERVATIONS_V"
OWNER = "OH_LYME_PROD_MIGRATION_DEPLOYER"
ROOT = Path(__file__).resolve().parents[2]


def snapshot(cursor: Any, normalize: Any, *, optimized: bool) -> dict[str, Any]:
    """No source records emitted; inaccessible objects are a blocking exception."""
    cursor.execute(
        "SELECT r.release_id,r.bundle_sha256,r.source_manifest:climate_extension "
        "FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p "
        "JOIN PRESENTATION.SEMANTIC_RELEASES r ON r.release_id=p.current_release_id "
        "WHERE p.pointer_key='ATLAS' AND r.status='PUBLISHED' LIMIT 2"
    )
    rows = cursor.fetchall()
    if len(rows) != 1 or rows[0][:2] != (RELEASE, BUNDLE):
        raise ValueError("POINT_RELEASE_BINDING")
    extension = rows[0][2]
    if isinstance(extension, str):
        extension = json.loads(extension)
    validate_extension(extension)
    if (
        extension.get("target_environment") != "prod"
        or extension.get("ingestion_run_id") != "d0e1e30b-49f1-5400-8345-af0b3e975114"
        or extension.get("capture_membership_sha256")
        != "8a577c0450024808a2c1bfcfe60b9a5cbe569cc6bbb229170894bdd5a117e4bf"
    ):
        raise ValueError("POINT_CAPTURE_BINDING")
    cursor.execute(f"SHOW GRANTS ON VIEW {VIEW}")
    columns = [item[0].lower() for item in cursor.description]
    grants = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    stable = sorted(
        (g["privilege"], g["granted_to"], g["grantee_name"], str(g["grant_option"])) for g in grants
    )
    if not any(g["privilege"] == "OWNERSHIP" and g["grantee_name"] == OWNER for g in grants):
        raise ValueError("POINT_VIEW_OWNER")
    if not any(
        g["privilege"] == "SELECT" and g["grantee_name"] == "OH_LYME_PROD_READ" for g in grants
    ):
        raise ValueError("POINT_READER_GRANT")
    cursor.execute(f"SELECT GET_DDL('VIEW','{VIEW}')")
    definition = cursor.fetchone()[0]
    filename = (
        "V154__prod_climate_membership_point_lookup.sql"
        if optimized
        else "V152__prod_january_climate_consumer_views.sql"
    )
    source = (ROOT / "migrations" / filename).read_text()
    if not optimized:
        source = source[
            : source.index(
                "\nCREATE OR REPLACE VIEW PRESENTATION.CURRENT_CLIMATE_MEASURE_METADATA_V"
            )
        ]
    if normalize(definition) != normalize(source[source.index("CREATE OR REPLACE VIEW") :]):
        raise ValueError("POINT_VIEW_DEFINITION")
    return {
        "release": RELEASE,
        "bundle": BUNDLE,
        "grants": stable,
        "membership_sha256": extension["capture_membership_sha256"],
        "row_count": extension["row_count"],
    }


SCOPE = (
    "county_fips IN ('48277','02013') AND period_start=DATE '2025-01-17' "
    "AND measure_id IN ('nclimgrid_prcp_county_day','nclimgrid_tmin_county_day',"
    "'nclimgrid_tmax_county_day','nclimgrid_tavg_county_day')"
)


def scientific_gate(cursor: Any, *, optimized: bool) -> dict[str, Any]:
    """Fixed eight-row full-projection acceptance; no unbounded scientific scan."""
    import time

    if not optimized:
        query = (ROOT / "sql/january_climate_full_projection_parity.sql").read_text()
        cursor.execute(query, timeout=60, _no_retry=True)
        if cursor.fetchall() != [(8, 8, 0, 0)]:
            raise ValueError("POINT_FULL_PROJECTION_PARITY")
        return {"full_projection_parity_query_id": cursor.sfqid}
    start = time.monotonic()
    cursor.execute(
        f"SELECT * FROM {VIEW} WHERE {SCOPE} ORDER BY county_fips,measure_id LIMIT 9",
        timeout=60,
        _no_retry=True,
    )
    elapsed = time.monotonic() - start
    columns = [item[0].lower() for item in cursor.description]
    values = cursor.fetchmany(9)
    if len(values) != 8:
        raise ValueError("POINT_SCIENTIFIC_ROW_COUNT")
    expected = {
        "prcp": 0,
        "tmin": -1.992294192037333,
        "tmax": 16.29939307942125,
        "tavg": 7.153611977327104,
    }
    seen = set()
    for value in values:
        row = dict(zip(columns, value, strict=True))
        code = row["measure_id"].removeprefix("nclimgrid_").removesuffix("_county_day")
        key = (row["county_fips"], code)
        if key in seen or code not in expected or row["release_id"] != RELEASE:
            raise ValueError("POINT_SCIENTIFIC_IDENTITY")
        seen.add(key)
        if row["unit"] != ("mm" if code == "prcp" else "degree_Celsius"):
            raise ValueError("POINT_SCIENTIFIC_UNIT")
        if row["county_fips"] == "02013":
            if (
                row["value"] is not None
                or row["coverage_status"] != "OUT_OF_SOURCE_COVERAGE"
                or row["value_state"] != "UNAVAILABLE"
            ):
                raise ValueError("POINT_SCIENTIFIC_UNAVAILABLE")
        elif (
            row["value"] is None
            or abs(float(row["value"]) - expected[code]) > 1e-10
            or row["coverage_status"] != "COMPLETE"
            or row["value_state"] != ("ZERO" if code == "prcp" else "OBSERVED")
        ):
            raise ValueError("POINT_SCIENTIFIC_VALUE")
    return {
        "full_projection_query_id": cursor.sfqid,
        "returned_rows": len(values),
        "client_seconds": elapsed,
        "api_acceptance": False,
    }
