"""Protected post-deployment read canary using the real API service identity.

Credentials are supplied process-locally by the protected environment. This is
not a personal PAT workaround. Never log exception text or connection settings.
"""

from __future__ import annotations

import json
from pathlib import Path

from lyme_gap_atlas_shared.settings import SnowflakeSettings

from lyme_gap_atlas_data.release_completeness import VIEWS, validate_manifest, verify_current
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
        cursor.execute("ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=60")
        for view in VIEWS:
            cursor.execute("SELECT * FROM PRESENTATION." + view + " LIMIT 0")
        cursor.execute("SELECT release_id,bundle_sha256 FROM PRESENTATION.CURRENT_RELEASE_V")
        releases = cursor.fetchmany(2)
        if len(releases) != 1:
            raise ValueError("Current release ambiguous")
        release, bundle = releases[0]
        profile_path = (
            Path(__file__).parents[1]
            / "docs/contracts/semantic-release"
            / "release-completeness-2026-10-18.json"
        )
        profile = json.loads(profile_path.read_text())
        verify_current(
            cursor,
            release,
            {
                "artifacts": validate_manifest(profile),
                "independent_consumers": profile["independent_consumers"],
            },
        )
        cursor.execute(
            "SELECT COUNT(*),COUNT(DISTINCT fips) FROM PRESENTATION.CURRENT_COUNTY_ATLAS_V"
        )
        if tuple(cursor.fetchone()) != (3144, 3144):
            raise ValueError("Incomplete county release")
        cursor.execute(
            "SELECT release_id,bundle_sha256,prediction_batch_version,priority_tier,COUNT(*) "
            "FROM PRESENTATION.CURRENT_TIER1_COUNTY_REVIEW_V GROUP BY ALL"
        )
        rows = cursor.fetchall()
        if {r[3]: r[4] for r in rows} != {"HIGH": 315, "MEDIUM": 628, "LOW": 2201}:
            raise ValueError("Incomplete Tier 1 output")
        identities = {(r[0], r[1], r[2]) for r in rows}
        if len(identities) != 1:
            raise ValueError("Ambiguous model batch")
        input_release, input_bundle, batch = identities.pop()
        if (input_release, input_bundle) != (release, bundle):
            cursor.execute(
                "SELECT COUNT(*) FROM PRESENTATION.MODEL_RELEASE_COMPATIBILITY_V "
                "WHERE artifact_id='tier1' AND batch_id=%s AND input_release_id=%s "
                "AND input_bundle_sha256=%s AND target_release_id=%s AND target_bundle_sha256=%s",
                (batch, input_release, input_bundle, release, bundle),
            )
            if cursor.fetchone()[0] != 1:
                raise ValueError("Tier 1 not admitted for current release")
        cursor.execute(
            "SELECT model_id,COUNT(*),COUNT(DISTINCT county_fips) "
            "FROM PRESENTATION.CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V GROUP BY model_id"
        )
        counts = cursor.fetchall()
        if {r[0]: (r[1], r[2]) for r in counts} != {
            "surveillance-situation-four-state": (3144, 3144),
            "surveillance-situation-tick-pathogen": (3144, 3144),
        }:
            raise ValueError("Incomplete surveillance situation output")
        cursor.execute(
            "SELECT COUNT(*),COUNT_IF(availability<>'AVAILABLE') FROM "
            "PRESENTATION.COUNTY_SURVEILLANCE_SITUATION_AVAILABILITY_V"
        )
        if tuple(cursor.fetchone()) != (6288, 0):
            raise ValueError("Surveillance situation eligibility regression")
        cursor.execute(
            "SELECT COUNT(*) FROM (SELECT model_id,county_fips,COUNT(*) AS n,"
            "COUNT_IF(TRY_TO_DOUBLE(p.value:probability::VARCHAR) IS NULL OR "
            "TRY_TO_DOUBLE(p.value:probability::VARCHAR) NOT BETWEEN 0 AND 1) AS bad,"
            "SUM(TRY_TO_DOUBLE(p.value:probability::VARCHAR)) AS total "
            "FROM PRESENTATION.CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V s,"
            "LATERAL FLATTEN(INPUT=>s.probabilities) p GROUP BY model_id,county_fips) "
            "WHERE n<>4 OR bad<>0 OR ABS(total-1)>1e-6"
        )
        if cursor.fetchone()[0] != 0:
            raise ValueError("Invalid published membership probabilities")
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
            )
            for g in grants
        ):
            raise ValueError("API role can execute model publisher")
    return {
        "service_identity": "OH_LYME_API_SVC",
        "release_id": release,
        "bundle_sha256": bundle,
        "tier1_rows": 3144,
        "situations_rows_per_fit": 3144,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(run(), sort_keys=True))
    except Exception:
        raise SystemExit(
            "API service release-integrity canary failed; retain protected job evidence"
        ) from None
