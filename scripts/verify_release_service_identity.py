"""Protected post-deployment read canary using the real API service identity.

Credentials are supplied process-locally by the protected environment. This is
not a personal PAT workaround. Never log exception text or connection settings.
"""

from __future__ import annotations

import json

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from lyme_gap_atlas_data.release_completeness import (
    VIEWS,
    authorize_artifacts,
    validate_manifest,
    verify_current,
)
from lyme_gap_atlas_data.sql_sessions import connect


def run() -> dict:
    settings = SnowflakeSettings()
    with connect(settings) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()"
        )
        context = cursor.fetchone()
        if (
            context is None
            or tuple(context[:3])
            != ("OH_LYME_API_SVC", "OH_LYME_PROD_READ", "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
            or not context[3]
        ):
            raise ValueError("Real API service context required")
        cursor.execute(
            "SELECT IS_ROLE_IN_SESSION('OH_LYME_PROD_ML_PUBLISHER'),"
            "IS_ROLE_IN_SESSION('OH_LYME_PROD_OWNER'),"
            "IS_ROLE_IN_SESSION('OH_LYME_PROD_MIGRATION_DEPLOYER')"
        )
        if tuple(cursor.fetchone()) != (False, False, False):
            raise ValueError("API session inherits model publication or approval authority")
        cursor.execute("ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=60")
        for view in VIEWS:
            cursor.execute("SELECT * FROM PRESENTATION." + view + " LIMIT 0")
        cursor.execute("SELECT release_id,bundle_sha256 FROM PRESENTATION.CURRENT_RELEASE_V")
        releases = cursor.fetchmany(2)
        if len(releases) != 1:
            raise ValueError("Current release ambiguous")
        release, bundle = releases[0]
        cursor.execute("SELECT completeness FROM PRESENTATION.CURRENT_RELEASE_COMPLETENESS_V")
        profiles = cursor.fetchmany(2)
        if len(profiles) != 1:
            raise ValueError("Current completeness admission ambiguous")
        profile = profiles[0][0]
        if isinstance(profile, str):
            profile = json.loads(profile)
        artifacts = authorize_artifacts(cursor, release, bundle, validate_manifest(profile))
        verify_current(
            cursor,
            release,
            {
                "artifacts": artifacts,
                "independent_consumers": profile["independent_consumers"],
            },
        )
        cursor.execute(
            "SELECT COUNT(*),COUNT(DISTINCT fips) FROM PRESENTATION.CURRENT_COUNTY_ATLAS_V"
        )
        if tuple(cursor.fetchone()) != (3144, 3144):
            raise ValueError("Incomplete county release")
        cursor.execute(
            "SELECT COUNT(*),COUNT_IF(availability<>'AVAILABLE') FROM "
            "PRESENTATION.COUNTY_SURVEILLANCE_SITUATION_AVAILABILITY_V"
        )
        expected_situations = sum(
            artifacts[key]["expected_rows"]
            for key in ("surveillance-situation-four-state", "surveillance-situation-tick-pathogen")
        )
        if tuple(cursor.fetchone()) != (6288, 6288 - expected_situations):
            raise ValueError("Surveillance situation eligibility regression")
        cursor.execute(
            "SELECT COUNT(*) FROM (SELECT model_id,county_fips,COUNT(*) AS n,"
            "COUNT_IF(TRY_TO_DOUBLE(p.value:probability::VARCHAR) IS NULL OR "
            "TRY_TO_DOUBLE(p.value:probability::VARCHAR) NOT BETWEEN 0 AND 1) AS bad,"
            "SUM(TRY_TO_DOUBLE(p.value:probability::VARCHAR)) AS total "
            "FROM PRESENTATION.CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V s,"
            "LATERAL FLATTEN(INPUT=>s.probabilities,OUTER=>TRUE) p GROUP BY model_id,county_fips) "
            "WHERE n<>4 OR bad<>0 OR ABS(total-1)>1e-6"
        )
        if cursor.fetchone()[0] != 0:
            raise ValueError("Invalid published membership probabilities")
        if artifacts["tier1"]["expected_rows"] > 0:
            cursor.execute(
                "SELECT county_fips,priority_tier FROM PRESENTATION.CURRENT_TIER1_COUNTY_REVIEW_V "
                "WHERE county_fips IN ('36001','01003','01001')"
            )
            if dict(cursor.fetchall()) != {"36001": "HIGH", "01003": "MEDIUM", "01001": "LOW"}:
                raise ValueError("Tier 1 representative county regression")
        # Probe only denial-safe SELECT/SHOW. Never execute a publisher or DML
        # to test privileges against real approved production data.
        for table in (
            "TIER1_COUNTY_REVIEW_OUTPUTS",
            "COUNTY_SURVEILLANCE_SITUATIONS",
            "SURVEILLANCE_SITUATION_BATCHES",
            "SURVEILLANCE_SITUATION_AUTHORIZATIONS",
        ):
            try:
                cursor.execute("SELECT * FROM FEATURE_STORE." + table + " LIMIT 0")
            except Exception as exc:
                if getattr(exc, "sqlstate", None) != "42S02":
                    raise ValueError("Permission denial could not be established") from None
            else:
                raise ValueError("API can access restricted base table")
        cursor.execute("SHOW GRANTS TO ROLE OH_LYME_PROD_READ")
        names = [str(c[0]).lower() for c in cursor.description]
        grants = [dict(zip(names, r, strict=True)) for r in cursor.fetchall()]
        if any(
            g.get("granted_on") == "PROCEDURE"
            and (
                "SP_PUBLISH_SURVEILLANCE" in str(g.get("name"))
                or "SP_STAGE_SURVEILLANCE" in str(g.get("name"))
                or "SP_AUTHORIZE_SURVEILLANCE" in str(g.get("name"))
            )
            for g in grants
        ):
            raise ValueError("API role can execute model publisher")
    return {
        "service_identity": "OH_LYME_API_SVC",
        "release_id": release,
        "bundle_sha256": bundle,
        "tier1_eligible_rows": artifacts["tier1"]["expected_rows"],
        "situations_eligible_rows": expected_situations,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(run(), sort_keys=True))
    except Exception:
        raise SystemExit(
            "API service release-integrity canary failed; retain protected job evidence"
        ) from None
