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
