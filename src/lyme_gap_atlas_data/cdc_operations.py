"""Metadata-only monitoring and explicitly authorized CDC refreshes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from .cdc import _fetch_json, build_approved_cdc_models, ingest_approved_cdc, load_cdc_profile
from .cdc_incidents import record_incident
from .cdc_policy import metadata_fingerprint, overdue_metadata_period
from .cdc_publication import cdc_operation, require_publication_enabled
from .cdc_quality import record_cdc_quality
from .settings import PipelineSettings


def current_metadata_fingerprint() -> str:
    settings = PipelineSettings()
    token = settings.socrata_app_token.get_secret_value() if settings.socrata_app_token else None
    return metadata_fingerprint(
        _fetch_json(str(load_cdc_profile()["metadata_endpoint_template"]), token)
    )


def check_cdc_metadata() -> dict[str, str]:
    """Capture a change signal without acquiring source rows or publishing data."""
    check_id = str(uuid.uuid4())
    with cdc_operation():
        try:
            fingerprint = current_metadata_fingerprint()
            with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """SELECT metadata_sha256 FROM GOVERNANCE.CDC_METADATA_CHECKS
                    WHERE status<>'FAILED' ORDER BY checked_at DESC LIMIT 1"""
                )
                previous = cursor.fetchone()
                status = (
                    "BASELINE"
                    if previous is None
                    else ("UNCHANGED" if previous[0] == fingerprint else "CHANGED")
                )
                cursor.execute(
                    """INSERT INTO GOVERNANCE.CDC_METADATA_CHECKS
                    VALUES (%s,CURRENT_TIMESTAMP(),%s,%s,NULL)""",
                    (check_id, fingerprint, status),
                )
                connection.commit()
            return {"check_id": check_id, "status": status, "metadata_sha256": fingerprint}
        except Exception:
            with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO GOVERNANCE.CDC_METADATA_CHECKS
                    VALUES (%s,CURRENT_TIMESTAMP(),NULL,'FAILED','CDC_METADATA_FAILED')""",
                    (check_id,),
                )
                connection.commit()
            record_incident("METADATA_FAILED", f"metadata:{check_id}")
            raise


def operator_refresh(check_id: str) -> dict[str, Any]:
    """The operator explicitly selects a recorded metadata check for acquisition."""
    with cdc_operation() as owner:
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT data_source_version_id FROM GOVERNANCE.DATA_SOURCE_VERSIONS
                WHERE resource_key='cdc_lyme_x5j9_wybp' AND status IN ('APPROVED','CONDITIONAL')
                  AND retired_at IS NULL ORDER BY created_at DESC LIMIT 1"""
            )
            source = cursor.fetchone()
            if source is None:
                raise ValueError("CDC refresh requires source approval")
            require_publication_enabled()
            cursor.execute(
                """SELECT metadata_sha256 FROM GOVERNANCE.CDC_METADATA_CHECKS
                WHERE check_id=%s AND status IN ('BASELINE','CHANGED','UNCHANGED')""",
                (check_id,),
            )
            selected = cursor.fetchone()
            if selected is None:
                raise ValueError("Select a successful CDC metadata check")
        if selected[0] != current_metadata_fingerprint():
            raise ValueError("Publisher metadata changed; run a new metadata check")
        ingestion = ingest_approved_cdc(
            expected_metadata=str(selected[0]), expected_source_version_id=str(source[0])
        )
        try:
            promotion = build_approved_cdc_models(str(source[0]), lease_owner=owner)
        except Exception:
            record_incident(
                "VALIDATION_FAILED",
                f"validation:{ingestion['ingestion_run_id']}",
                str(ingestion["ingestion_run_id"]),
            )
            raise
        return {"ingestion": ingestion, "promotion": promotion, "status": "COMPLETED"}


def check_cdc_overdue() -> dict[str, str]:
    """Record one incident per missed month; never acquire or transform source rows."""
    with cdc_operation():
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT MAX(checked_at) FROM GOVERNANCE.CDC_METADATA_CHECKS
                WHERE status IN ('BASELINE','CHANGED','UNCHANGED')"""
            )
            last = cursor.fetchone()
        period = overdue_metadata_period(datetime.now(UTC), last[0] if last else None)
        if period is None:
            return {"status": "ON_TIME"}
        record_incident("OVERDUE", f"overdue:{period}")
        return {"status": "OVERDUE", "period": period}


def verify_cdc_ready(source_version_id: str) -> dict[str, str]:
    """Require current publication quality and a recent metadata baseline before scheduling."""
    with cdc_operation():
        require_publication_enabled()
        record_cdc_quality(source_version_id)
        with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
            cursor.execute(
                """SELECT COUNT(*) FROM GOVERNANCE.CDC_METADATA_CHECKS
                WHERE status IN ('BASELINE','CHANGED','UNCHANGED')
                  AND checked_at >= DATEADD(day,-7,CURRENT_TIMESTAMP())"""
            )
            recent = cursor.fetchone()
            if recent is None or recent[0] == 0:
                raise ValueError("A successful metadata baseline within seven days is required")
    return {"status": "READY", "source_version_id": source_version_id}
