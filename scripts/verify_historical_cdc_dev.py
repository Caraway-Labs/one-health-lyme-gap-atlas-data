"""Exercise shipped historical quality/publication against session-temporary DEV fixtures.

Object-name redirection fails closed; no real source, approval or publication is written.
"""

import re
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect
from verify_cdc_policy_dev import FixtureConnection

from lyme_gap_atlas_data import cdc_historical_ingestion as historical
from lyme_gap_atlas_data.cdc_quality import CdcQualityError

ROOT = Path(__file__).resolve().parents[1]


def main():
    historical.require_governed_environment()
    with connect(SnowflakeSettings()) as base:
        with base.cursor() as cursor:
            cursor.execute(
                "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()"
            )
            user, role, database, warehouse = cursor.fetchone()
            if (database, role) != (
                "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
                "OH_LYME_DEV_PIPELINE_RUNTIME",
            ):
                raise ValueError("Historical fixtures require DEV runtime")
            print(f"HISTORICAL_FIXTURE_CONTEXT {user} {role} {database} {warehouse}")
        ddl = []
        for filename in (
            "V043__cdc_snapshot_operations.sql",
            "V046__dev_historical_cdc_storage.sql",
        ):
            ddl.extend(
                re.findall(
                    r"CREATE TABLE IF NOT EXISTS .*?\);",
                    (ROOT / "migrations" / filename).read_text(),
                    re.S,
                )
            )
        ddl.extend(
            [
                "CREATE TABLE IF NOT EXISTS GOVERNANCE.DATA_SOURCE_VERSIONS "
                "(data_source_version_id VARCHAR,resource_key VARCHAR,status VARCHAR,"
                "retired_at TIMESTAMP_LTZ)",
                "CREATE TABLE IF NOT EXISTS GOVERNANCE.INGESTION_RUNS "
                "(ingestion_run_id VARCHAR,status VARCHAR)",
                "CREATE TABLE IF NOT EXISTS GOVERNANCE.RAW_ARTIFACTS "
                "(artifact_id VARCHAR,ingestion_run_id VARCHAR,sha256 VARCHAR)",
            ]
        )
        governance = (ROOT / "migrations/V001__governed_platform.sql").read_text()
        ddl.append(
            next(
                sql
                for sql in re.findall(r"CREATE TABLE IF NOT EXISTS .*?\);", governance, re.S)
                if "GOVERNANCE.DATA_QUALITY_RESULTS" in sql
            )
        )
        prefix = "STAGING.HISTORICAL_FIXTURE_" + uuid4().hex.upper() + "_"
        names = {sql.split()[5]: prefix + str(i) for i, sql in enumerate(ddl)}
        names[historical.CANDIDATE] = prefix + "CANDIDATE"
        fixture = FixtureConnection(base, names)
        with fixture.cursor() as cur:
            for sql in ddl:
                cur.execute(sql.replace("CREATE TABLE IF NOT EXISTS", "CREATE TEMPORARY TABLE"))
            cur.execute(f"CREATE TEMPORARY TABLE {historical.CANDIDATE} LIKE {historical.RETAINED}")
            cur.execute(
                "INSERT INTO GOVERNANCE.DATA_SOURCE_VERSIONS VALUES (%s,%s,'APPROVED',NULL)",
                ("fixture-source", historical.RESOURCE_KEY),
            )
            cur.execute(
                "INSERT INTO GOVERNANCE.CDC_OPERATION_LEASE(resource_key,publication_enabled) "
                "VALUES (%s,TRUE)",
                (historical.RESOURCE_KEY,),
            )
        base.commit()
        with patch.object(historical, "connect", lambda _: fixture):

            def seed(run, frequency):
                with fixture.cursor() as cur:
                    cur.execute(
                        "INSERT INTO GOVERNANCE.INGESTION_RUNS VALUES (%s,'COMPLETED')", (run,)
                    )
                    cur.execute(
                        "INSERT INTO GOVERNANCE.RAW_ARTIFACTS VALUES (%s,%s,'hash')", (run, run)
                    )
                    cur.execute(
                        """INSERT INTO RAW.CDC_LYME_QTBI_XD4I
                        (payload,data_source_version_id,ingestion_run_id,artifact_id,
                         source_url,source_row_hash,retrieved_at)
                        SELECT p,'fixture-source',%s,%s,%s,SHA2(TO_JSON(p),256),CURRENT_TIMESTAMP()
                        FROM (SELECT OBJECT_CONSTRUCT('fips','unknown','year','2008',
                          'case_status','confirmed','sex','suppressed','age_cat_yrs','not reported',
                          'frequency',%s) p)""",
                        (run, run, historical.ENDPOINT, frequency),
                    )
                    cur.execute(
                        f"""INSERT INTO {historical.CANDIDATE}
                        SELECT NULL,payload,data_source_version_id,ingestion_run_id,artifact_id,
                          payload:fips::VARCHAR,payload:year::NUMBER,payload:case_status::VARCHAR,
                          payload:sex::VARCHAR,payload:age_cat_yrs::VARCHAR,payload:frequency::NUMBER,
                          OBJECT_CONSTRUCT('county_fips','unknown','sex','suppressed',
                            'case_status','observed','age_category_years','not reported',
                            'frequency',IFF(payload:frequency::NUMBER=0,'zero','observed')),
                          'COUNTY_OF_RESIDENCE','COUNTY_YEAR_CASE_STATUS_SEX_AGE',
                          'ANNUAL_SURVEILLANCE_YEAR','2008-2021 fixture-only',CURRENT_TIMESTAMP()
                        FROM RAW.CDC_LYME_QTBI_XD4I WHERE ingestion_run_id=%s""",
                        (run,),
                    )
                base.commit()

            def publish(run, revision):
                validation = historical.record_quality("fixture-source", run, 1)
                with historical.historical_operation() as owner:
                    return historical.publish("fixture-source", run, validation, owner, revision)

            def pointer():
                with fixture.cursor() as cur:
                    cur.execute("SELECT ingestion_run_id,revision FROM GOVERNANCE.CDC_PUBLICATIONS")
                    return cur.fetchone()

            seed("first", 0)
            assert publish("first", 0)["status"] == "PUBLISHED"
            seed("same", 0)
            assert publish("same", 1)["status"] == "UNCHANGED"
            assert pointer() == ("first", 1)
            seed("changed", 2)
            assert publish("changed", 1)["status"] == "PUBLISHED"
            seed("rejected", 3)
            with fixture.cursor() as cur:
                cur.execute(
                    f"UPDATE {historical.CANDIDATE} SET frequency=0 "
                    "WHERE ingestion_run_id='rejected'"
                )
            base.commit()
            try:
                publish("rejected", 2)
            except CdcQualityError:
                pass
            else:
                raise AssertionError("Invalid historical projection passed")
            assert pointer() == ("changed", 2)
            assert (
                historical.rollback_historical("fixture-source", "first", 2)["status"]
                == "PUBLISHED"
            )
            assert pointer() == ("first", 3)
        print("HISTORICAL_DEV_FIXTURES=PASSED unchanged changed rejected rollback")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"HISTORICAL_DEV_FIXTURE_FAILURE={type(error).__name__} "
            f"ERRNO={getattr(error, 'errno', 'NA')} SFQID={getattr(error, 'sfqid', 'NA')}",
            flush=True,
        )
        raise SystemExit(1) from None
