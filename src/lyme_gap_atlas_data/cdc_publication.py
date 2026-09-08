"""Serialized CDC publication: retained snapshots and an atomic visible pointer."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from .cdc_policy import publication_decision, snapshot_checksum
from .cdc_quality import QUALITY_SQL, record_cdc_quality

PUBLIC_VIEW_SQL = """CREATE OR REPLACE VIEW CONFORMED.CONFORMED_CDC_LYME_X5J9_WYBP
COPY GRANTS AS SELECT snapshot.* FROM CONFORMED.CDC_VALIDATED_SNAPSHOTS snapshot
JOIN GOVERNANCE.CDC_PUBLICATIONS publication
  ON snapshot.data_source_version_id=publication.data_source_version_id
 AND snapshot.ingestion_run_id=publication.ingestion_run_id
JOIN GOVERNANCE.DATA_SOURCE_VERSIONS version
  ON snapshot.data_source_version_id=version.data_source_version_id
WHERE version.status IN ('APPROVED','CONDITIONAL') AND version.retired_at IS NULL"""


def require_publication_enabled() -> None:
    """Guard acquisition without requiring a new source version to have RAW yet."""
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT publication_enabled FROM GOVERNANCE.CDC_OPERATION_LEASE
            WHERE resource_key='cdc_lyme_x5j9_wybp'"""
        )
        ready = cursor.fetchone()
        if ready is None or not ready[0]:
            raise RuntimeError("CDC publication must be bootstrapped before refresh")


def publication_context(source_version_id: str) -> tuple[str, int]:
    """Resolve one completed candidate and the visible publication revision."""
    require_publication_enabled()
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT r.ingestion_run_id FROM RAW.CDC_LYME_X5J9_WYBP r
            JOIN GOVERNANCE.INGESTION_RUNS i ON r.ingestion_run_id=i.ingestion_run_id
            WHERE r.data_source_version_id=%s AND i.status='COMPLETED'
            GROUP BY r.ingestion_run_id,i.started_at ORDER BY i.started_at DESC LIMIT 1""",
            (source_version_id,),
        )
        candidate = cursor.fetchone()
        if candidate is None:
            raise ValueError("No completed CDC snapshot is available")
        cursor.execute(
            "SELECT revision FROM GOVERNANCE.CDC_PUBLICATIONS WHERE data_source_version_id=%s",
            (source_version_id,),
        )
        pointer = cursor.fetchone()
        return str(candidate[0]), int(pointer[0]) if pointer else 0


def bootstrap_publication(source_version_id: str, run_id: str) -> dict[str, Any]:
    """Validate the existing visible snapshot before activating pointer serving."""
    with cdc_operation() as owner:
        quality = record_cdc_quality(source_version_id, ingestion_run_id=run_id)
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT revision FROM GOVERNANCE.CDC_PUBLICATIONS WHERE data_source_version_id=%s",
                (source_version_id,),
            )
            current = cursor.fetchone()
        result = publish_snapshot(
            source_version_id,
            run_id,
            str(quality["validation_id"]),
            owner,
            expected_revision=int(current[0]) if current else 0,
            candidate_relation="CONFORMED.CONFORMED_CDC_LYME_X5J9_WYBP",
        )
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            cursor.execute(PUBLIC_VIEW_SQL)
            cursor.execute(
                """UPDATE GOVERNANCE.CDC_OPERATION_LEASE SET publication_enabled=TRUE
                WHERE resource_key='cdc_lyme_x5j9_wybp' AND lease_owner=%s""",
                (owner,),
            )
            connection.commit()
        return result


@contextmanager
def cdc_operation() -> Iterator[str]:
    """Lease expires after 30 minutes; publication also checks lease ownership."""
    owner = str(uuid.uuid4())
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        cursor.execute(
            """UPDATE GOVERNANCE.CDC_OPERATION_LEASE SET lease_owner=%s,
            expires_at=DATEADD(minute,30,CURRENT_TIMESTAMP())
            WHERE resource_key='cdc_lyme_x5j9_wybp'
              AND (lease_owner IS NULL OR expires_at<CURRENT_TIMESTAMP())""",
            (owner,),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise RuntimeError("Another CDC operation holds the lease")
        connection.commit()
    try:
        yield owner
    finally:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            cursor.execute(
                """UPDATE GOVERNANCE.CDC_OPERATION_LEASE SET lease_owner=NULL,expires_at=NULL
                WHERE resource_key='cdc_lyme_x5j9_wybp' AND lease_owner=%s""",
                (owner,),
            )
            connection.commit()


def publish_snapshot(
    source_version_id: str,
    run_id: str,
    validation_id: str,
    lease_owner: str,
    *,
    expected_revision: int,
    candidate_relation: str = "STAGING.CDC_LYME_CANDIDATE",
    reason: str = "VALIDATED_PUBLICATION",
) -> dict[str, Any]:
    """Copy validated rows and update their pointer in one transaction."""
    if candidate_relation not in {
        "STAGING.CDC_LYME_CANDIDATE",
        "CONFORMED.CONFORMED_CDC_LYME_X5J9_WYBP",
        "CONFORMED.CDC_VALIDATED_SNAPSHOTS",
    }:
        raise ValueError("Unsupported candidate relation")
    if reason not in {"VALIDATED_PUBLICATION", "OPERATOR_ROLLBACK"}:
        raise ValueError("Unsupported publication reason")
    with connect(SnowflakeSettings()) as connection:
        connection.autocommit(False)
        try:
            with connection.cursor() as cursor:
                # Lock the singleton through commit; an expired worker may not publish.
                cursor.execute(
                    """UPDATE GOVERNANCE.CDC_OPERATION_LEASE SET expires_at=expires_at
                    WHERE resource_key='cdc_lyme_x5j9_wybp' AND lease_owner=%s
                      AND expires_at>CURRENT_TIMESTAMP()""",
                    (lease_owner,),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("CDC publication lease expired")
                cursor.execute(
                    """SELECT COUNT(*) FROM GOVERNANCE.DATA_SOURCE_VERSIONS
                    WHERE data_source_version_id=%s AND status IN ('APPROVED','CONDITIONAL')
                      AND resource_key='cdc_lyme_x5j9_wybp' AND retired_at IS NULL""",
                    (source_version_id,),
                )
                approval = cursor.fetchone()
                if approval is None or approval[0] != 1:
                    raise ValueError("Publication requires active source approval")
                cursor.execute(
                    """SELECT COUNT(DISTINCT rule_id),COUNT_IF(status<>'PASSED')
                    FROM GOVERNANCE.DATA_QUALITY_RESULTS WHERE ingestion_run_id=%s
                      AND observed_value:validation_id::VARCHAR=%s
                      AND observed_value:source_version_id::VARCHAR=%s
                      AND rule_id LIKE 'cdc_x5j9_v1_%%'""",
                    (run_id, validation_id, source_version_id),
                )
                quality = cursor.fetchone()
                if quality is None:
                    raise ValueError("Quality evidence is missing")
                count, failed = quality
                cursor.execute(
                    """SELECT source_row_hash FROM RAW.CDC_LYME_X5J9_WYBP
                    WHERE ingestion_run_id=%s AND data_source_version_id=%s""",
                    (run_id, source_version_id),
                )
                hashes = [str(row[0]) for row in cursor.fetchall()]
                checksum = snapshot_checksum(hashes)
                cursor.execute(
                    """SELECT revision,content_sha256,ingestion_run_id
                    FROM GOVERNANCE.CDC_PUBLICATIONS WHERE data_source_version_id=%s""",
                    (source_version_id,),
                )
                pointer = cursor.fetchone()
                revision, previous_checksum, previous_run = pointer or (0, None, None)
                action = publication_decision(
                    current_revision=int(revision),
                    expected_revision=expected_revision,
                    current_checksum=previous_checksum,
                    candidate_checksum=checksum,
                    failed_checks=int(failed or 0),
                    check_count=int(count),
                )
                if action == "UNCHANGED":
                    connection.commit()
                    return {"status": action, "ingestion_run_id": previous_run}
                cursor.execute(
                    "SELECT COUNT(*) FROM GOVERNANCE.CDC_SNAPSHOTS WHERE ingestion_run_id=%s",
                    (run_id,),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise RuntimeError("Snapshot lookup returned no result")
                if existing[0] == 0:
                    cursor.execute(
                        f"""INSERT INTO CONFORMED.CDC_VALIDATED_SNAPSHOTS
                        SELECT * FROM {candidate_relation}
                        WHERE ingestion_run_id=%s AND data_source_version_id=%s""",
                        (run_id, source_version_id),
                    )
                    if cursor.rowcount != len(hashes):
                        raise ValueError("Candidate changed after validation")
                # Validate the copied/retained rows inside the publication
                # transaction, not only the earlier candidate view. A concurrent
                # dbt replacement must not create a validation-to-copy race.
                retained_query = QUALITY_SQL.replace(
                    "CONFORMED.CONFORMED_CDC_LYME_X5J9_WYBP",
                    "CONFORMED.CDC_VALIDATED_SNAPSHOTS",
                ).replace(
                    "WHERE data_source_version_id = %s",
                    "WHERE data_source_version_id = %s AND ingestion_run_id = %s",
                )
                cursor.execute(
                    retained_query, (source_version_id, run_id, source_version_id, run_id)
                )
                retained_checks = cursor.fetchall()
                if len(retained_checks) != 8 or any(
                    int(expected or 0) != int(observed or 0)
                    for _, _, expected, observed in retained_checks
                ):
                    raise ValueError("Retained snapshot failed transactional quality validation")
                if existing[0] == 0:
                    cursor.execute(
                        """INSERT INTO GOVERNANCE.CDC_SNAPSHOTS VALUES (%s,%s,%s,%s,%s,%s)""",
                        (
                            run_id,
                            source_version_id,
                            checksum,
                            validation_id,
                            len(hashes),
                            datetime.now(UTC),
                        ),
                    )
                if pointer is None:
                    cursor.execute(
                        """INSERT INTO GOVERNANCE.CDC_PUBLICATIONS
                        VALUES (%s,%s,%s,1,CURRENT_TIMESTAMP())""",
                        (source_version_id, run_id, checksum),
                    )
                else:
                    cursor.execute(
                        """UPDATE GOVERNANCE.CDC_PUBLICATIONS
                        SET ingestion_run_id=%s,content_sha256=%s,revision=revision+1,
                            published_at=CURRENT_TIMESTAMP()
                        WHERE data_source_version_id=%s AND revision=%s""",
                        (run_id, checksum, source_version_id, expected_revision),
                    )
                    if cursor.rowcount != 1:
                        raise RuntimeError("Concurrent publication rejected")
                cursor.execute(
                    """INSERT INTO GOVERNANCE.CDC_PUBLICATION_EVENTS
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        str(uuid.uuid4()),
                        source_version_id,
                        previous_run,
                        run_id,
                        int(revision) + 1,
                        reason,
                        datetime.now(UTC),
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {"status": "PUBLISHED", "ingestion_run_id": run_id, "content_sha256": checksum}


def rollback_publication(
    source_version_id: str, run_id: str, *, expected_revision: int
) -> dict[str, Any]:
    """Repoint to retained validated data without acquiring or deleting RAW."""
    with cdc_operation() as owner:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT validation_id,row_count FROM GOVERNANCE.CDC_SNAPSHOTS
                WHERE data_source_version_id=%s AND ingestion_run_id=%s""",
                (source_version_id, run_id),
            )
            snapshot = cursor.fetchone()
            if snapshot is None:
                raise ValueError("Rollback requires a retained validated snapshot")
            cursor.execute(
                """SELECT COUNT(*) FROM CONFORMED.CDC_VALIDATED_SNAPSHOTS
                WHERE data_source_version_id=%s AND ingestion_run_id=%s""",
                (source_version_id, run_id),
            )
            retained = cursor.fetchone()
            if retained is None or retained[0] != snapshot[1] or retained[0] == 0:
                raise ValueError("Retained snapshot row reconciliation failed")
        return publish_snapshot(
            source_version_id,
            run_id,
            str(snapshot[0]),
            owner,
            expected_revision=expected_revision,
            candidate_relation="CONFORMED.CDC_VALIDATED_SNAPSHOTS",
            reason="OPERATOR_ROLLBACK",
        )
