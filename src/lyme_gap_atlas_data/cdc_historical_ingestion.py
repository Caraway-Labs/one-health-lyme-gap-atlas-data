"""Explicit environment-isolated historical acquisition and publication.

No schedule, source approval, or current-era publication lives here. PROD is
permitted only through the existing production-execution setting and exact
database/runtime-role checks.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from .cdc import _fetch_json, ingest_approved_cdc, run_cdc_dbt
from .cdc_historical import DATASET_ID, REQUIRED_COLUMNS, RESOURCE_KEY
from .cdc_incidents import record_incident
from .cdc_policy import metadata_fingerprint, snapshot_checksum
from .cdc_quality import QUALITY_SQL, CdcQualityError
from .settings import PipelineSettings

ENDPOINT = "https://data.cdc.gov/resource/qtbi-xd4i.json"
METADATA = "https://data.cdc.gov/api/views/qtbi-xd4i"
CANDIDATE = "STAGING.CDC_LYME_HISTORICAL_CANDIDATE"
RETAINED = "CONFORMED.CDC_HISTORICAL_VALIDATED_SNAPSHOTS"


def require_governed_environment() -> PipelineSettings:
    settings = PipelineSettings()
    if settings.topx_env not in {"dev", "prod"}:
        raise ValueError("Historical ingestion requires an isolated DEV or PROD environment")
    return settings


def validate_page(page: Any, limit: int) -> None:
    """Do not manufacture a natural key or coerce unknown/suppressed values."""
    if not isinstance(page, list) or not 0 < len(page) <= limit:
        raise ValueError("Historical page is empty, malformed or exceeds its bound")
    for row in page:
        if not isinstance(row, dict):
            raise ValueError("Historical record must be an object")
        year = str(row.get("year", ""))
        if not year.isascii() or not year.isdigit() or not 2008 <= int(year) <= 2021:
            raise ValueError("Historical record crosses the 2008-2021 era")
        frequency = row.get("frequency")
        if frequency is not None and str(frequency).lower() not in {
            "unknown",
            "suppressed",
            "not reported",
        }:
            try:
                count = Decimal(str(frequency))
            except InvalidOperation as error:
                raise ValueError("Historical frequency is not a supported source value") from error
            if not count.is_finite() or count < 0 or count != count.to_integral_value():
                raise ValueError("Historical frequency must not be rounded or negative")


def quality_sql(relation: str) -> str:
    if relation not in {CANDIDATE, RETAINED}:
        raise ValueError("Unsupported historical validation relation")
    query = (
        QUALITY_SQL.replace("RAW.CDC_LYME_X5J9_WYBP", "RAW.CDC_LYME_QTBI_XD4I")
        .replace("CONFORMED.CONFORMED_CDC_LYME_X5J9_WYBP", relation)
        .replace(
            "WHERE data_source_version_id = %s",
            "WHERE data_source_version_id = %s AND ingestion_run_id = %s",
        )
    )
    states = []
    for field, status in (
        ("fips", "county_fips"),
        ("sex", "sex"),
        ("case_status", "case_status"),
        ("age_cat_yrs", "age_category_years"),
        ("frequency", "frequency"),
    ):
        states.append(f"""NOT EQUAL_NULL(source_value_status:{status}::VARCHAR,
          CASE WHEN payload:{field} IS NULL THEN 'missing'
          WHEN IS_NULL_VALUE(payload:{field}) THEN 'null'
          WHEN LOWER(payload:{field}::VARCHAR) IN ('unknown','suppressed','not reported')
          THEN LOWER(payload:{field}::VARCHAR)
          WHEN payload:{field}::VARCHAR='0' THEN 'zero' ELSE 'observed' END)""")
    query = query.replace(
        "COUNT_IF(data_source_version_id IS NULL",
        "COUNT_IF(" + " OR ".join(states) + " OR data_source_version_id IS NULL",
    )
    return (
        query
        + """
UNION ALL
SELECT ingestion_run_id, 'historical_era', 0,
 COUNT_IF(report_year IS NULL OR report_year NOT BETWEEN 2008 AND 2021
   OR caveat NOT LIKE '2008-2021%%') FROM conformed GROUP BY ingestion_run_id
UNION ALL
SELECT ingestion_run_id, 'historical_source', 0,
 COUNT_IF(source_url <> 'https://data.cdc.gov/resource/qtbi-xd4i.json')
 FROM raw GROUP BY ingestion_run_id
"""
    )


@contextmanager
def historical_operation() -> Iterator[str]:
    settings = require_governed_environment()
    owner = str(uuid.uuid4())
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT CURRENT_DATABASE(),CURRENT_ROLE()")
        context = cursor.fetchone()
        environment = settings.topx_env.upper()
        expected = (
            f"ONE_HEALTH_LYME_GAP_ATLAS_{environment}",
            f"OH_LYME_{environment}_PIPELINE_RUNTIME",
        )
        if context != expected:
            raise ValueError("Historical operations require the isolated environment runtime")
        cursor.execute(
            """UPDATE GOVERNANCE.CDC_OPERATION_LEASE SET lease_owner=%s,
            expires_at=DATEADD(minute,30,CURRENT_TIMESTAMP()) WHERE resource_key=%s
            AND (lease_owner IS NULL OR expires_at<CURRENT_TIMESTAMP())""",
            (owner, RESOURCE_KEY),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise RuntimeError("Historical lease is missing or already held")
        connection.commit()
    try:
        yield owner
    finally:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            cursor.execute(
                """UPDATE GOVERNANCE.CDC_OPERATION_LEASE SET lease_owner=NULL,expires_at=NULL
                WHERE resource_key=%s AND lease_owner=%s""",
                (RESOURCE_KEY, owner),
            )
            connection.commit()


def require_approval(cursor: Any, source_version_id: str) -> None:
    cursor.execute(
        """SELECT COUNT(*) FROM GOVERNANCE.DATA_SOURCE_VERSIONS
        WHERE resource_key=%s AND data_source_version_id=%s
        AND status='APPROVED' AND retired_at IS NULL""",
        (RESOURCE_KEY, source_version_id),
    )
    if cursor.fetchone() != (1,):
        raise ValueError("Historical ingestion requires the exact active approved version")


def record_quality(source: str, run: str, expected_rows: int) -> str:
    require_governed_environment()
    validation = str(uuid.uuid4())
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        require_approval(cursor, source)
        cursor.execute(quality_sql(CANDIDATE), (source, run, source, run))
        checks = [(r, rule, int(a or 0), int(b or 0)) for r, rule, a, b in cursor.fetchall()]
        cursor.execute(
            """SELECT COUNT(*) FROM RAW.CDC_LYME_QTBI_XD4I
            WHERE data_source_version_id=%s AND ingestion_run_id=%s""",
            (source, run),
        )
        count = cursor.fetchone()
        if len(checks) != 10 or count is None:
            raise CdcQualityError("Historical validation requires all ten candidate checks")
        checks.append((run, "publisher_row_reconciliation", expected_rows, int(count[0])))
        connection.autocommit(False)
        try:
            for run_id, rule, expected, observed in checks:
                passed = expected == observed
                cursor.execute(
                    """INSERT INTO GOVERNANCE.DATA_QUALITY_RESULTS
                    (data_quality_result_id,ingestion_run_id,rule_id,severity,status,
                     expected_value,observed_value,created_at)
                    SELECT %s,%s,%s,'BLOCKING',%s,PARSE_JSON(%s),PARSE_JSON(%s),
                    CURRENT_TIMESTAMP()""",
                    (
                        str(uuid.uuid4()),
                        run_id,
                        f"cdc_qtbi_v1_{rule}",
                        "PASSED" if passed else "FAILED",
                        json.dumps({"value": expected}),
                        json.dumps(
                            {
                                "value": observed,
                                "validation_id": validation,
                                "source_version_id": source,
                            }
                        ),
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    if any(expected != observed for _, _, expected, observed in checks):
        raise CdcQualityError("Historical quality failed; persisted evidence retained")
    return validation


def publish(
    source: str, run: str, validation: str, owner: str, revision: int, *, rollback: bool = False
) -> dict[str, Any]:
    """Recheck retained data and approval while holding the source lease through commit."""
    require_governed_environment()
    relation = RETAINED if rollback else CANDIDATE
    with connect(SnowflakeSettings()) as connection:
        connection.autocommit(False)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE GOVERNANCE.CDC_OPERATION_LEASE SET expires_at=expires_at
                    WHERE resource_key=%s AND lease_owner=%s AND expires_at>CURRENT_TIMESTAMP()""",
                    (RESOURCE_KEY, owner),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Historical publication lease expired")
                require_approval(cursor, source)
                cursor.execute(
                    """SELECT COUNT(DISTINCT rule_id),COUNT_IF(status<>'PASSED')
                    FROM GOVERNANCE.DATA_QUALITY_RESULTS WHERE ingestion_run_id=%s
                    AND observed_value:validation_id::VARCHAR=%s
                    AND observed_value:source_version_id::VARCHAR=%s
                    AND rule_id LIKE 'cdc_qtbi_v1_%%'""",
                    (run, validation, source),
                )
                evidence = cursor.fetchone()
                if evidence is None or evidence[0] != 11 or int(evidence[1] or 0) != 0:
                    raise CdcQualityError("Historical publication requires eleven passing checks")
                cursor.execute(
                    """SELECT source_row_hash FROM RAW.CDC_LYME_QTBI_XD4I
                    WHERE data_source_version_id=%s AND ingestion_run_id=%s""",
                    (source, run),
                )
                hashes = [str(row[0]) for row in cursor.fetchall()]
                checksum = snapshot_checksum(hashes)
                cursor.execute(
                    """SELECT revision,content_sha256,ingestion_run_id
                    FROM GOVERNANCE.CDC_PUBLICATIONS WHERE data_source_version_id=%s""",
                    (source,),
                )
                pointer = cursor.fetchone()
                current_revision, previous_hash, previous_run = pointer or (0, None, None)
                if current_revision != revision:
                    raise ValueError("Historical publication revision changed")
                if previous_hash == checksum and not rollback:
                    connection.commit()
                    return {"status": "UNCHANGED", "ingestion_run_id": previous_run}
                cursor.execute(
                    """SELECT COUNT(*) FROM GOVERNANCE.CDC_SNAPSHOTS
                    WHERE data_source_version_id=%s AND ingestion_run_id=%s""",
                    (source, run),
                )
                existing = cursor.fetchone()
                if existing == (0,) and not rollback:
                    cursor.execute(
                        f"""INSERT INTO {RETAINED} SELECT * FROM {relation}
                        WHERE data_source_version_id=%s AND ingestion_run_id=%s""",
                        (source, run),
                    )
                    if cursor.rowcount != len(hashes):
                        raise CdcQualityError("Historical copy row count changed")
                elif existing != (1,):
                    raise ValueError("Historical snapshot registry is missing or ambiguous")
                cursor.execute(quality_sql(RETAINED), (source, run, source, run))
                checks = cursor.fetchall()
                if len(checks) != 10 or any(int(a or 0) != int(b or 0) for _, _, a, b in checks):
                    raise CdcQualityError("Retained historical snapshot failed validation")
                if existing == (0,):
                    cursor.execute(
                        """INSERT INTO GOVERNANCE.CDC_SNAPSHOTS
                        VALUES (%s,%s,%s,%s,%s,CURRENT_TIMESTAMP())""",
                        (run, source, checksum, validation, len(hashes)),
                    )
                if pointer is None:
                    cursor.execute(
                        """INSERT INTO GOVERNANCE.CDC_PUBLICATIONS
                        VALUES (%s,%s,%s,1,CURRENT_TIMESTAMP())""",
                        (source, run, checksum),
                    )
                else:
                    cursor.execute(
                        """UPDATE GOVERNANCE.CDC_PUBLICATIONS SET ingestion_run_id=%s,
                        content_sha256=%s,revision=revision+1,published_at=CURRENT_TIMESTAMP()
                        WHERE data_source_version_id=%s AND revision=%s""",
                        (run, checksum, source, revision),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError("Concurrent historical publication rejected")
                cursor.execute(
                    """INSERT INTO GOVERNANCE.CDC_PUBLICATION_EVENTS
                    VALUES (%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP())""",
                    (
                        str(uuid.uuid4()),
                        source,
                        previous_run,
                        run,
                        revision + 1,
                        "OPERATOR_ROLLBACK" if rollback else "VALIDATED_PUBLICATION",
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {"status": "PUBLISHED", "ingestion_run_id": run, "content_sha256": checksum}


def refresh_historical(source_version_id: str) -> dict[str, Any]:
    settings = require_governed_environment()
    source_version_id = str(uuid.UUID(source_version_id))
    token = settings.socrata_app_token.get_secret_value() if settings.socrata_app_token else None
    with historical_operation() as owner:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            require_approval(cursor, source_version_id)
            cursor.execute(
                "SELECT revision FROM GOVERNANCE.CDC_PUBLICATIONS WHERE data_source_version_id=%s",
                (source_version_id,),
            )
            pointer = cursor.fetchone()
            revision = int(pointer[0]) if pointer else 0
        metadata = _fetch_json(METADATA, token)
        fingerprint = metadata_fingerprint(metadata, dataset_id=DATASET_ID)
        if not REQUIRED_COLUMNS.issubset({c.get("fieldName") for c in metadata["columns"]}):
            raise ValueError("Historical schema changed; steward review required")
        count_url = ENDPOINT + "?" + urlencode({"$select": "count(*) as row_count"})
        expected_rows = int(_fetch_json(count_url, token)[0]["row_count"])
        if not 0 < expected_rows <= 1_000_000:
            raise ValueError("Historical source exceeds the reviewed acquisition bound")
        ingestion = ingest_approved_cdc(
            dataset_id=DATASET_ID,
            expected_metadata=fingerprint,
            expected_source_version_id=source_version_id,
        )
        run = str(ingestion["ingestion_run_id"])
        try:
            if int(_fetch_json(count_url, token)[0]["row_count"]) != expected_rows:
                raise ValueError("Historical publisher row count changed during acquisition")
            run_cdc_dbt("stg_cdc_lyme_qtbi_xd4i+")
            validation = record_quality(source_version_id, run, expected_rows)
            result = publish(source_version_id, run, validation, owner, revision)
        except Exception:
            record_incident("VALIDATION_FAILED", f"historical-validation:{run}", run)
            raise
    return {"ingestion": ingestion, "publication": result, "quality_checks": 11}


def rollback_historical(source: str, run: str, revision: int) -> dict[str, Any]:
    require_governed_environment()
    with historical_operation() as owner:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            require_approval(cursor, source)
            cursor.execute(
                """SELECT validation_id FROM GOVERNANCE.CDC_SNAPSHOTS
                WHERE data_source_version_id=%s AND ingestion_run_id=%s""",
                (source, run),
            )
            snapshot = cursor.fetchone()
            if snapshot is None:
                raise ValueError("Rollback requires a retained historical snapshot")
        return publish(source, run, str(snapshot[0]), owner, revision, rollback=True)
