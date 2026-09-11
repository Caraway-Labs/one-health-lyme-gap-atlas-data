"""Run real CDC SQL/functions against DEV session-temporary fixture tables.

No real approval, RAW, publication or quality table is mutated. Only object names
are redirected; transaction, validation and publication logic is the shipped code.
This complements (does not replace) real-source bootstrap/dbt/unchanged proof.
"""

from contextlib import ExitStack, suppress
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from lyme_gap_atlas_data import cdc_incidents, cdc_operations, cdc_publication, cdc_quality

ROOT = Path(__file__).resolve().parents[1]


class FixtureConnection:
    def __init__(self, connection, names):
        self.connection, self.names = connection, names

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        # The outer owner keeps this one session alive for all temporary objects.
        return False

    def cursor(self):
        return FixtureCursor(self.connection.cursor(), self.names)

    def __getattr__(self, name):
        return getattr(self.connection, name)


class FixtureCursor:
    def __init__(self, cursor, names):
        self.cursor, self.names = cursor, names

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.cursor.close()

    def execute(self, statement, *args):
        for original, temporary in sorted(self.names.items(), key=lambda item: -len(item[0])):
            statement = statement.replace(original, temporary)
        if any(prefix in statement for prefix in ("GOVERNANCE.", "RAW.", "CONFORMED.")):
            raise ValueError("Fixture attempted an unmapped governed relation")
        self.cursor.execute(statement, *args)
        return self

    def __getattr__(self, name):
        return getattr(self.cursor, name)


def main():
    settings = SnowflakeSettings()
    if settings.snowflake_database != "ONE_HEALTH_LYME_GAP_ATLAS_DEV":
        raise ValueError("DEV only")
    with connect(settings) as base:
        with base.cursor() as cursor:
            cursor.execute(
                "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()"
            )
            user, role, database, warehouse = cursor.fetchone()
            if (
                database != "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
                or role != "OH_LYME_DEV_PIPELINE_RUNTIME"
            ):
                raise ValueError("Fixture requires the isolated DEV runtime identity")
            print(
                f"DEV_FIXTURE_CONTEXT user={user} role={role} "
                f"database={database} warehouse={warehouse}"
            )
        ddl = [
            sql.strip()
            for sql in (ROOT / "migrations/V043__cdc_snapshot_operations.sql")
            .read_text()
            .split(";")
            if sql.strip().startswith("CREATE TABLE")
        ]
        ddl += [
            "CREATE TABLE IF NOT EXISTS GOVERNANCE.DATA_SOURCE_VERSIONS "
            "(data_source_version_id VARCHAR,resource_key VARCHAR,"
            "status VARCHAR,retired_at TIMESTAMP_LTZ)",
            "CREATE TABLE IF NOT EXISTS GOVERNANCE.INGESTION_RUNS "
            "(ingestion_run_id VARCHAR,status VARCHAR)",
            "CREATE TABLE IF NOT EXISTS GOVERNANCE.RAW_ARTIFACTS "
            "(artifact_id VARCHAR,ingestion_run_id VARCHAR,sha256 VARCHAR)",
            "CREATE TABLE IF NOT EXISTS RAW.CDC_LYME_X5J9_WYBP "
            "(payload VARIANT,data_source_version_id VARCHAR,ingestion_run_id VARCHAR,"
            "artifact_id VARCHAR,source_row_hash VARCHAR)",
        ]
        governance = (ROOT / "migrations/V001__governed_platform.sql").read_text()
        ddl.append(
            next(
                sql.strip()
                for sql in governance.split(";")
                if sql.strip().startswith(
                    "CREATE TABLE IF NOT EXISTS GOVERNANCE.DATA_QUALITY_RESULTS"
                )
            )
        )
        prefix = "STAGING.CDC_POLICY_FIXTURE_" + uuid4().hex.upper() + "_"
        names = {sql.split()[5]: prefix + str(index) for index, sql in enumerate(ddl)}
        names["STAGING.CDC_LYME_CANDIDATE"] = prefix + "CANDIDATE"
        fixture = FixtureConnection(base, names)
        with fixture.cursor() as cur:
            for sql in ddl:
                cur.execute(sql.replace("CREATE TABLE IF NOT EXISTS", "CREATE TEMPORARY TABLE"))
            cur.execute(
                "CREATE TEMPORARY TABLE STAGING.CDC_LYME_CANDIDATE "
                "LIKE CONFORMED.CDC_VALIDATED_SNAPSHOTS"
            )
            cur.execute(
                "INSERT INTO GOVERNANCE.DATA_SOURCE_VERSIONS "
                "VALUES ('fixture-source','cdc_lyme_x5j9_wybp','APPROVED',NULL)"
            )
            cur.execute(
                "INSERT INTO GOVERNANCE.CDC_OPERATION_LEASE(resource_key,publication_enabled) "
                "VALUES ('cdc_lyme_x5j9_wybp',TRUE)"
            )
        base.commit()
        with ExitStack() as patches:
            for module in (cdc_publication, cdc_quality, cdc_operations, cdc_incidents):
                patches.enter_context(patch.object(module, "connect", lambda _: fixture))

            def seed(run, frequency):
                with fixture.cursor() as cur:
                    cur.execute(
                        "INSERT INTO GOVERNANCE.INGESTION_RUNS VALUES (%s,'COMPLETED')", (run,)
                    )
                    cur.execute(
                        "INSERT INTO GOVERNANCE.RAW_ARTIFACTS VALUES (%s,%s,'fixture-checksum')",
                        (run, run),
                    )
                    cur.execute(
                        """INSERT INTO RAW.CDC_LYME_X5J9_WYBP
                        SELECT p,'fixture-source',%s,%s,SHA2(TO_JSON(p),256)
                        FROM (SELECT OBJECT_CONSTRUCT('fips','unknown','year',2022,
                          'sex','suppressed','case_status','confirmed',
                          'age_cat_yrs','not reported','frequency',%s) p)""",
                        (run, run, frequency),
                    )
                    cur.execute(
                        """INSERT INTO STAGING.CDC_LYME_CANDIDATE
                        SELECT NULL,payload,data_source_version_id,ingestion_run_id,artifact_id,
                          payload:fips::VARCHAR,payload:year::NUMBER,payload:case_status::VARCHAR,
                          payload:sex::VARCHAR,payload:age_cat_yrs::VARCHAR,payload:frequency::NUMBER,
                          OBJECT_CONSTRUCT('county_fips','unknown','sex','suppressed',
                            'age_category_years','not reported'),
                          'COUNTY_OF_RESIDENCE','COUNTY_YEAR_CASE_STATUS_SEX_AGE',
                          'ANNUAL_SURVEILLANCE_YEAR','fixture-only',CURRENT_TIMESTAMP()
                        FROM RAW.CDC_LYME_X5J9_WYBP WHERE ingestion_run_id=%s""",
                        (run,),
                    )
                base.commit()

            def publish(run, revision):
                quality = cdc_quality.record_cdc_quality(
                    "fixture-source", ingestion_run_id=run, candidate=True
                )
                with cdc_publication.cdc_operation() as owner:
                    return cdc_publication.publish_snapshot(
                        "fixture-source",
                        run,
                        quality["validation_id"],
                        owner,
                        expected_revision=revision,
                    )

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
            assert pointer() == ("changed", 2)
            seed("rejected", 3)
            with fixture.cursor() as cur:
                cur.execute(
                    "UPDATE STAGING.CDC_LYME_CANDIDATE SET frequency=0 "
                    "WHERE ingestion_run_id='rejected'"
                )
            base.commit()
            try:
                publish("rejected", 2)
            except cdc_quality.CdcQualityError:
                pass
            else:
                raise AssertionError("Corrupt projection passed quality")
            assert pointer() == ("changed", 2)
            assert (
                cdc_publication.rollback_publication(
                    "fixture-source", "first", expected_revision=2
                )["status"]
                == "PUBLISHED"
            )
            assert pointer() == ("first", 3)
            with (
                patch.object(
                    cdc_operations, "current_metadata_fingerprint", side_effect=TimeoutError
                ),
                suppress(TimeoutError),
            ):
                cdc_operations.check_cdc_metadata()
            with fixture.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM GOVERNANCE.CDC_METADATA_CHECKS WHERE status='FAILED'"
                )
                assert cur.fetchone()[0] == 1
                cur.execute(
                    "SELECT COUNT(*) FROM GOVERNANCE.CDC_INCIDENTS "
                    "WHERE incident_type='METADATA_FAILED'"
                )
                assert cur.fetchone()[0] == 1
                cur.execute("""SELECT COUNT(*),SUM(s.frequency)
                    FROM CONFORMED.CDC_VALIDATED_SNAPSHOTS s
                    JOIN GOVERNANCE.CDC_PUBLICATIONS p ON s.ingestion_run_id=p.ingestion_run_id""")
                assert cur.fetchone() == (1, 0)
        print("CDC_POLICY_DEV_FIXTURES=PASSED unchanged changed rejected rollback durable_failure")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        trace = error.__traceback__
        while trace and trace.tb_next:
            trace = trace.tb_next
        print(
            f"CDC_POLICY_DEV_FAILURE={type(error).__name__} "
            f"ERRNO={getattr(error, 'errno', 'NA')} "
            f"SFQID={getattr(error, 'sfqid', 'NA')} "
            f"LINE={trace.tb_lineno if trace else 0}",
            flush=True,
        )
        raise SystemExit(1) from None
