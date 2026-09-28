"""Protected DEV-only transport and set-SQL preflight; no governed table writes."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from lyme_gap_atlas_data.ingestion.bulk_stage import remove_transport, stage_json_rows
from lyme_gap_atlas_data.ingestion.runtime import (
    _bulk_record_source,
    _check_bulk_revision_conflicts,
    _merge_bulk_projection,
    _merge_bulk_revisions,
)


class _CaptureCursor:
    def __init__(self) -> None:
        self.sql = ""
        self.params: tuple[Any, ...] = ()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.sql, self.params = sql, params

    def fetchone(self) -> tuple[int]:
        return (0,)


def _verify_destination_types(cursor: Any) -> None:
    common = {
        "RECORD_ID": "VARCHAR",
        "SOURCE_ID": "VARCHAR",
        "DATASET_ID": "VARCHAR",
        "RESOURCE_KEY": "VARCHAR",
        "SOURCE_DEFINITION_VERSION": "NUMBER",
        "INGESTION_RUN_ID": "VARCHAR",
        "SOURCE_RECORD_ID": "VARCHAR",
        "SOURCE_ROW_HASH": "VARCHAR",
        "PAYLOAD": "VARIANT",
        "RETRIEVED_AT": "TIMESTAMP_LTZ",
    }
    relations = {
        "STAGING.GOVERNED_SOURCE_RECORDS": {**common, "NORMALIZED_AT": "TIMESTAMP_LTZ"},
        "CONFORMED.GOVERNED_SOURCE_RECORDS": {**common, "CONFORMED_AT": "TIMESTAMP_LTZ"},
        "RAW.GOVERNED_SOURCE_RECORDS": {**common, "LOADED_AT": "TIMESTAMP_LTZ"},
        "GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS": {
            **common,
            "CAPTURE_RECORD_ID": "VARCHAR",
            "RECORD_REVISION": "VARCHAR",
            "ARTIFACT_ID": "VARCHAR",
            "ARTIFACT_SHA256": "VARCHAR",
            "NORMALIZED_SHA256": "VARCHAR",
            "TRANSFORMATION_VERSION": "VARCHAR",
            "OBSERVED_AT": "TIMESTAMP_LTZ",
        },
    }
    for relation, expected in relations.items():
        cursor.execute(f"DESCRIBE TABLE {relation}")
        actual = {str(row[0]).upper(): str(row[1]).upper() for row in cursor.fetchall()}
        differences = {
            column: (kind, actual.get(column))
            for column, kind in expected.items()
            if not actual.get(column, "").startswith(kind)
        }
        if differences:
            raise AssertionError(f"Live destination type mismatch {relation}: {differences}")
    print("Live projection and revision destination types match V069/V103")


def main() -> None:
    settings = SnowflakeSettings()
    if (
        settings.snowflake_database != "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
        or settings.snowflake_warehouse != "OH_LYME_DEV_INGEST_XS_WH"
    ):
        raise SystemExit("Bulk transport canary requires protected DEV XS")
    run_id = f"canary-{os.environ['GITHUB_RUN_ID']}"
    payload = json.dumps({"test": "bulk transport", "value": 1}, sort_keys=True)
    payload_sha = hashlib.sha256(payload.encode()).hexdigest()
    row = {
        "record_id": "canary-record",
        "source_id": "canary-source",
        "dataset_id": "canary-dataset",
        "resource_key": "canary-resource",
        "source_definition_version": 1,
        "ingestion_run_id": run_id,
        "source_record_id": None,
        "source_row_hash": "canary-row-hash",
        "payload": payload,
        "payload_sha256": payload_sha,
        "retrieved_at": "2025-01-15T12:34:56+00:00",
    }
    with connect(settings) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()"
        )
        identity_row = cursor.fetchone()
        if identity_row is None:
            raise AssertionError("Runtime identity query returned no row")
        identity = tuple(identity_row)
        if identity != (
            "OH_LYME_DEV_PIPELINE_SVC",
            "OH_LYME_DEV_RUNTIME",
            "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
            "OH_LYME_DEV_INGEST_XS_WH",
        ):
            raise SystemExit(f"Unexpected runtime identity: {identity}")
        _verify_destination_types(cursor)
        prefix = f"@GOVERNANCE.INGESTION_BULK_STAGE/{run_id}/records"
        cursor.execute(f"LIST {prefix}")
        if cursor.fetchall():
            raise SystemExit("Canary prefix already contains transport objects")
        source = stage_json_rows(cursor, run_id=run_id, kind="records", rows=[row])
        try:
            cursor.execute(
                f"""SELECT COUNT(*), COUNT_IF(SHA2($1:payload::VARCHAR, 256)
                           = $1:payload_sha256::VARCHAR),
                           COUNT_IF(AS_VARCHAR($1:source_record_id) IS NULL),
                           COUNT_IF(PARSE_JSON($1:payload::VARCHAR):value::NUMBER = 1),
                           COUNT_IF(TO_TIMESTAMP_LTZ($1:retrieved_at::VARCHAR)
                           = TO_TIMESTAMP_LTZ('2025-01-15T12:34:56+00:00'))
                    FROM {source}"""
            )
            result = cursor.fetchone()
            if result is None:
                raise AssertionError("Stage expression query returned no row")
            observed = tuple(int(value or 0) for value in result)
            if observed != (1, 1, 1, 1, 1):
                raise AssertionError(f"Stage expression mismatch: {observed}")
            cursor.execute(f"SELECT COUNT(*) FROM ({_bulk_record_source(source)})")
            count_row = cursor.fetchone()
            if count_row is None or count_row[0] != 1:
                raise AssertionError("Bulk source projection did not read one row")
            if stage_json_rows(cursor, run_id=run_id, kind="records", rows=[row]) != source:
                raise AssertionError("Retry changed content-addressed transport path")
            cursor.execute(f"LIST {prefix}")
            if len(cursor.fetchall()) != 1:
                raise AssertionError("Retry created a second staged object")
            for relation, timestamp_column in (
                ("STAGING.GOVERNED_SOURCE_RECORDS", "normalized_at"),
                ("CONFORMED.GOVERNED_SOURCE_RECORDS", "conformed_at"),
                ("RAW.GOVERNED_SOURCE_RECORDS", "loaded_at"),
            ):
                captured = _CaptureCursor()
                _merge_bulk_projection(captured, relation, timestamp_column, source)
                cursor.execute("EXPLAIN USING TEXT " + captured.sql, captured.params)
                cursor.fetchall()
            captured = _CaptureCursor()
            _check_bulk_revision_conflicts(captured, source, "canary-artifact", "canary-v1")
            cursor.execute("EXPLAIN USING TEXT " + captured.sql, captured.params)
            cursor.fetchall()
            captured = _CaptureCursor()
            _merge_bulk_revisions(
                captured, source, "canary-artifact", "canary-artifact", "canary-v1"
            )
            cursor.execute("EXPLAIN USING TEXT " + captured.sql, captured.params)
            cursor.fetchall()
            print(f"Stage expressions and set SQL planned: {source}")
        finally:
            remove_transport(cursor, source)
            cursor.execute(f"LIST {prefix}")
            if cursor.fetchall():
                raise AssertionError("Canary transport residue remains")
    print("Protected DEV transport canary passed; no governed table writes")


if __name__ == "__main__":
    main()
