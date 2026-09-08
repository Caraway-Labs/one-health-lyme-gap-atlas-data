"""Append-only CDC validation evidence; no source payloads leave Snowflake."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect


class CdcQualityError(RuntimeError):
    """Validation failed after its aggregate results were committed."""


# Compare multisets, not only total counts: equal-sized substitutions and
# duplicate output rows must fail reconciliation. Scope each check to its RAW run.
QUALITY_SQL = """
WITH raw AS (
  SELECT * FROM RAW.CDC_LYME_X5J9_WYBP WHERE data_source_version_id = %s
), conformed AS (
  SELECT * FROM CONFORMED.CONFORMED_CDC_LYME_X5J9_WYBP
  WHERE data_source_version_id = %s
), runs AS (
  SELECT DISTINCT ingestion_run_id FROM raw
  UNION SELECT DISTINCT ingestion_run_id FROM conformed
), raw_keys AS (
  SELECT ingestion_run_id, artifact_id, SHA2(TO_JSON(payload),256) AS row_hash,
         COUNT(*) AS n FROM raw GROUP BY ALL
), conformed_keys AS (
  SELECT ingestion_run_id, artifact_id, SHA2(TO_JSON(payload),256) AS row_hash,
         COUNT(*) AS n FROM conformed GROUP BY ALL
), differences AS (
  SELECT COALESCE(r.ingestion_run_id,c.ingestion_run_id) AS ingestion_run_id
  FROM raw_keys r FULL OUTER JOIN conformed_keys c
    ON EQUAL_NULL(r.ingestion_run_id,c.ingestion_run_id)
    AND EQUAL_NULL(r.artifact_id,c.artifact_id) AND r.row_hash=c.row_hash
  WHERE COALESCE(r.n,0) <> COALESCE(c.n,0)
)
SELECT runs.ingestion_run_id, 'nonempty_raw' AS rule_id, 1 AS expected,
       IFF((SELECT COUNT(*) FROM raw r WHERE r.ingestion_run_id=runs.ingestion_run_id)>0,1,0)
         AS observed FROM runs
UNION ALL
SELECT runs.ingestion_run_id, 'row_reconciliation',
       (SELECT COUNT(*) FROM raw r WHERE r.ingestion_run_id=runs.ingestion_run_id),
       (SELECT COUNT(*) FROM conformed c WHERE c.ingestion_run_id=runs.ingestion_run_id)
FROM runs
UNION ALL
SELECT runs.ingestion_run_id, 'payload_lineage_multiset', 0,
       (SELECT COUNT(*) FROM differences d WHERE d.ingestion_run_id=runs.ingestion_run_id)
FROM runs
UNION ALL
SELECT ingestion_run_id, 'required_provenance', 0,
       COUNT_IF(data_source_version_id IS NULL OR ingestion_run_id IS NULL
         OR artifact_id IS NULL OR retrieved_at IS NULL OR caveat IS NULL
         OR geography_semantics IS NULL OR source_resolution IS NULL OR temporal_window IS NULL)
FROM conformed GROUP BY ingestion_run_id
UNION ALL
SELECT r.ingestion_run_id, 'registered_lineage', 0,
       COUNT_IF(a.artifact_id IS NULL OR i.ingestion_run_id IS NULL
         OR a.ingestion_run_id <> r.ingestion_run_id OR a.sha256 IS NULL
         OR i.status <> 'COMPLETED')
FROM raw r LEFT JOIN GOVERNANCE.RAW_ARTIFACTS a ON r.artifact_id=a.artifact_id
LEFT JOIN GOVERNANCE.INGESTION_RUNS i ON r.ingestion_run_id=i.ingestion_run_id
GROUP BY r.ingestion_run_id
UNION ALL
SELECT ingestion_run_id, 'source_hash_integrity', 0,
       COUNT_IF(source_row_hash IS NULL OR source_row_hash <> SHA2(TO_JSON(payload),256))
FROM raw GROUP BY ingestion_run_id
UNION ALL
SELECT ingestion_run_id, 'duplicate_source_hash', 0,
       COUNT(*)-COUNT(DISTINCT source_row_hash) FROM raw GROUP BY ingestion_run_id
UNION ALL
SELECT ingestion_run_id, 'value_state_preservation', 0,
       COUNT_IF(NOT EQUAL_NULL(county_fips,payload:fips::VARCHAR)
         OR NOT EQUAL_NULL(report_year,TRY_TO_NUMBER(payload:year::VARCHAR))
         OR NOT EQUAL_NULL(case_status,payload:case_status::VARCHAR)
         OR NOT EQUAL_NULL(sex,payload:sex::VARCHAR)
         OR NOT EQUAL_NULL(age_category_years,payload:age_cat_yrs::VARCHAR)
         OR NOT EQUAL_NULL(frequency,TRY_TO_NUMBER(payload:frequency::VARCHAR))
         OR (LOWER(payload:fips::VARCHAR) IN ('unknown','suppressed','not reported')
             AND NOT EQUAL_NULL(source_value_status:county_fips::VARCHAR,
                                LOWER(payload:fips::VARCHAR)))
         OR (LOWER(payload:sex::VARCHAR) IN ('unknown','suppressed','not reported')
             AND NOT EQUAL_NULL(source_value_status:sex::VARCHAR,LOWER(payload:sex::VARCHAR)))
         OR (LOWER(payload:age_cat_yrs::VARCHAR) IN ('unknown','suppressed','not reported')
             AND NOT EQUAL_NULL(source_value_status:age_category_years::VARCHAR,
                                LOWER(payload:age_cat_yrs::VARCHAR))))
FROM conformed GROUP BY ingestion_run_id
"""


def record_cdc_quality(
    source_version_id: str,
    *,
    ingestion_run_id: str | None = None,
    candidate: bool = False,
) -> dict[str, int | str]:
    """Persist aggregate checks atomically, then fail on any blocking result.

    A repeat creates new evidence with a shared validation_id and timestamp;
    existing results are never updated. The ledger links to the original RAW
    ingestion run so the existing post-ingestion validation page can show it.
    """
    validation_id = str(uuid.uuid4())
    checked_at = datetime.now(UTC)
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT COUNT(*) FROM GOVERNANCE.DATA_SOURCE_VERSIONS
                WHERE data_source_version_id=%s AND resource_key='cdc_lyme_x5j9_wybp'
                  AND status IN ('APPROVED','CONDITIONAL') AND retired_at IS NULL""",
            (source_version_id,),
        )
        approval = cursor.fetchone()
        if approval is None or int(approval[0]) != 1:
            raise CdcQualityError("CDC quality requires one active approved source version")
        if ingestion_run_id is None:
            cursor.execute(
                """SELECT ingestion_run_id FROM GOVERNANCE.CDC_PUBLICATIONS
                WHERE data_source_version_id=%s""",
                (source_version_id,),
            )
            published = cursor.fetchone()
            if published is None or published[0] is None:
                raise CdcQualityError("No published snapshot; specify a candidate ingestion run")
            ingestion_run_id = str(published[0])
        query = QUALITY_SQL.replace(
            "WHERE data_source_version_id = %s",
            "WHERE data_source_version_id = %s AND ingestion_run_id = %s",
        )
        if candidate:
            query = query.replace(
                "CONFORMED.CONFORMED_CDC_LYME_X5J9_WYBP", "STAGING.CDC_LYME_CANDIDATE"
            )
        cursor.execute(
            query, (source_version_id, ingestion_run_id, source_version_id, ingestion_run_id)
        )
        checks = cursor.fetchall()
        if not checks:
            raise CdcQualityError("CDC quality requires retained source rows")
        failed = 0
        connection.autocommit(False)
        try:
            for run_id, rule_id, expected, observed in checks:
                expected, observed = int(expected or 0), int(observed or 0)
                passed = expected == observed
                failed += int(not passed)
                cursor.execute(
                    """INSERT INTO GOVERNANCE.DATA_QUALITY_RESULTS
                        (data_quality_result_id,ingestion_run_id,rule_id,severity,status,
                         expected_value,observed_value,created_at)
                        SELECT %s,%s,%s,'BLOCKING',%s,PARSE_JSON(%s),PARSE_JSON(%s),%s""",
                    (
                        str(uuid.uuid4()),
                        run_id,
                        f"cdc_x5j9_v1_{rule_id}",
                        "PASSED" if passed else "FAILED",
                        json.dumps({"value": expected}),
                        json.dumps(
                            {
                                "value": observed,
                                "validation_id": validation_id,
                                "source_version_id": source_version_id,
                            }
                        ),
                        checked_at,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    if failed:
        raise CdcQualityError(f"CDC quality failed {failed} blocking checks; evidence retained")
    return {"validation_id": validation_id, "checks": len(checks), "failed": failed}
