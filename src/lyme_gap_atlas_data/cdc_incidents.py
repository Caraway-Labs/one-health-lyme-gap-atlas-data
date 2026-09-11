"""Redacted CDC incident ledger; notification receipts are retained in GitHub."""

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect


def record_incident(kind: str, key: str, run_id: str | None = None) -> None:
    if kind not in {"ACQUISITION_FAILED", "VALIDATION_FAILED", "METADATA_FAILED", "OVERDUE"}:
        raise ValueError("Unsupported CDC incident type")
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        cursor.execute(
            """MERGE INTO GOVERNANCE.CDC_INCIDENTS target
            USING (SELECT %s AS incident_key) source ON target.incident_key=source.incident_key
            WHEN NOT MATCHED THEN INSERT
              (incident_key,incident_type,related_run_id,created_at)
              VALUES (source.incident_key,%s,%s,CURRENT_TIMESTAMP())""",
            (key, kind, run_id),
        )
        connection.commit()
