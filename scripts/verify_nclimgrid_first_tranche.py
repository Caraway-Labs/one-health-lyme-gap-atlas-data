"""Read-only protected DEV acceptance evidence for the approved #443 first tranche.

This deliberately has no input range or write path. It verifies only the three
approved 2008 months and emits compact, source/run-pinned evidence to the job log.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from lyme_gap_atlas_data.ingestion.checkpoints import SnowflakeCheckpointStore
from lyme_gap_atlas_data.ingestion.nclimgrid_coverage import build_coverage_report
from lyme_gap_atlas_data.ingestion.nclimgrid_longitudinal import definition_mapping, expected_days
from lyme_gap_atlas_data.ingestion.types import RunState, RunStatus, Stage

MONTHS = ("200801", "200802", "200803")
RESOURCE_PREFIX = "noaa_nclimgrid_daily_"
EXPECTED_USER = "OH_LYME_DEV_PIPELINE_SVC"
EXPECTED_ROLE = "OH_LYME_DEV_RUNTIME"
EXPECTED_DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
EXPECTED_COUNTIES = 3144
MEASURE_COUNT = 4
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def query(sql: str, params: tuple[object, ...] = ()) -> list[tuple[Any, ...]]:
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


def require_identity() -> None:
    settings = SnowflakeSettings()
    rows = query("SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()")
    expected = (EXPECTED_USER, EXPECTED_ROLE, EXPECTED_DATABASE, settings.snowflake_warehouse)
    if len(rows) != 1 or tuple(str(value) for value in rows[0]) != expected:
        raise RuntimeError("Protected DEV runtime identity mismatch")


def selected_runs(store: SnowflakeCheckpointStore) -> list[RunState]:
    rows = query(
        """SELECT ingestion_run_id, resource_key, status
           FROM GOVERNANCE.INGESTION_RUNS
           WHERE run_mode='SOURCE_INGESTION' AND resource_key IN (%s,%s,%s)
           ORDER BY started_at""",
        tuple(RESOURCE_PREFIX + month for month in MONTHS),
    )
    if len(rows) != len(MONTHS):
        raise RuntimeError("Expected exactly one governed run per approved month")
    by_month: dict[str, RunState] = {}
    for run_id, resource_key, status in rows:
        if not RUN_ID_PATTERN.fullmatch(str(run_id)):
            raise RuntimeError("Unsafe governed run identity")
        month = str(resource_key).removeprefix(RESOURCE_PREFIX)
        state = store.load(str(run_id))
        if (
            month not in MONTHS
            or month in by_month
            or status != "COMPLETED"
            or state is None
            or state.status is not RunStatus.SUCCEEDED
            or state.tier.value != "B"
        ):
            raise RuntimeError("Tranche run state is incomplete or ambiguous")
        acquire = state.checkpoint(Stage.ACQUIRE)
        if (
            acquire is None
            or acquire.detail.get("source_definition_sha256")
            != definition_mapping(month)["source_definition_sha256"]
        ):
            raise RuntimeError("Tranche source definition lineage mismatch")
        by_month[month] = state
    return [by_month[month] for month in MONTHS]


def history_counts(started: datetime, completed: datetime) -> tuple[dict[str, int], dict[str, int]]:
    if started.tzinfo is None or completed.tzinfo is None or completed <= started:
        raise RuntimeError("Invalid governed run time window")
    lower = (started - timedelta(minutes=5)).isoformat()
    upper = (completed + timedelta(minutes=5)).isoformat()
    rows = query(
        "SELECT QUERY_TYPE, QUERY_TEXT, START_TIME "
        "FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_USER("
        f"END_TIME_RANGE_START=>TO_TIMESTAMP_LTZ('{lower}'), "
        f"END_TIME_RANGE_END=>TO_TIMESTAMP_LTZ('{upper}'), RESULT_LIMIT=>10000))"
    )
    if len(rows) == 10000:
        raise RuntimeError("Query-history result limit reached")
    selected = [
        row for row in rows if isinstance(row[2], datetime) and started <= row[2] <= completed
    ]
    if not selected:
        raise RuntimeError("Governed run query history is unavailable")
    types = Counter(str(row[0]).upper() for row in selected)
    insert_targets: Counter[str] = Counter()
    for query_type, query_text, _started in selected:
        if str(query_type).upper() != "INSERT":
            continue
        target = re.search(r"\bINSERT\s+INTO\s+([A-Z0-9_.]+)", str(query_text).upper())
        insert_targets[target.group(1) if target else "UNCLASSIFIED"] += 1
    return dict(types), dict(insert_targets)


def measure_run(store: SnowflakeCheckpointStore, state: RunState) -> dict[str, Any]:
    month = state.resource_key.removeprefix(RESOURCE_PREFIX)
    run_id = state.ingestion_run_id
    expected_rows = EXPECTED_COUNTIES * expected_days(month) * MEASURE_COUNT
    partition_rows = query(
        """SELECT COUNT(*), COALESCE(SUM(row_count),0), COALESCE(SUM(byte_count),0),
                  MIN(partition_ordinal), MAX(partition_ordinal)
           FROM GOVERNANCE.INGESTION_RUN_NORMALIZED_PARTITIONS
           WHERE ingestion_run_id=%s""",
        (run_id,),
    )
    completion_rows = query(
        """SELECT partition_count FROM GOVERNANCE.INGESTION_RUN_PARTITION_COMPLETIONS
           WHERE ingestion_run_id=%s""",
        (run_id,),
    )
    revision_rows = query(
        "SELECT COUNT(*) FROM GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS "
        "WHERE ingestion_run_id=%s",
        (run_id,),
    )
    artifact_rows = query(
        """SELECT artifact_id, sha256, byte_count FROM GOVERNANCE.RAW_ARTIFACTS
           WHERE ingestion_run_id=%s ORDER BY artifact_id""",
        (run_id,),
    )
    window_rows = query(
        """SELECT started_at, completed_at FROM GOVERNANCE.INGESTION_RUNS
           WHERE ingestion_run_id=%s AND status='COMPLETED'""",
        (run_id,),
    )
    if (
        len(partition_rows) != 1
        or len(completion_rows) != 1
        or len(revision_rows) != 1
        or len(artifact_rows) != 2
        or len(window_rows) != 1
    ):
        raise RuntimeError("Required run evidence is missing")
    partition_count, row_count, canonical_bytes, first_ordinal, last_ordinal = partition_rows[0]
    completion_count = int(completion_rows[0][0])
    revision_count = int(revision_rows[0][0])
    if (
        int(row_count) != expected_rows
        or revision_count != expected_rows
        or int(partition_count) != completion_count
        or first_ordinal != 0
        or last_ordinal != completion_count - 1
    ):
        raise RuntimeError("Row, revision, ordinal, or completion invariant failed")
    ordered_count = 0
    for ordinal, partition in enumerate(store.iter_partitions(run_id)):
        if partition.ordinal != ordinal:
            raise RuntimeError("Fresh-process ordered partition read failed")
        ordered_count += 1
    if ordered_count != completion_count:
        raise RuntimeError("Ordered read differs from completion count")

    class OneRunStore:
        def list_runs(self) -> list[RunState]:
            return [state]

        def iter_partitions(self, selected_run_id: str) -> Any:
            if selected_run_id != run_id:
                raise RuntimeError("Report selected another run")
            return store.iter_partitions(run_id)

    with tempfile.TemporaryDirectory(prefix="nclimgrid-443-report-") as directory:
        report = build_coverage_report(
            OneRunStore(), start=month, end=month, county_csv=Path(directory) / "county.csv"
        )
    monthly = cast(list[dict[str, Any]], report["months"])[0]
    if (
        report["captured_month_count"] != 1
        or monthly["selected_run_id"] != run_id
        or monthly["observed_days"] != expected_days(month)
        or monthly["missing_source_days"]
        or monthly["normalized_partition_count"] != completion_count
    ):
        raise RuntimeError("Run-pinned coverage report failed")
    started, completed = window_rows[0]
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        cursor.execute(f"LIST @GOVERNANCE.INGESTION_BULK_STAGE/{run_id}/")
        run_stage_objects = list(cursor.fetchall())
    query_types, insert_targets = history_counts(started, completed)
    return {
        "month": month,
        "run_id": run_id,
        "status": "SUCCEEDED",
        "runtime_seconds": (completed - started).total_seconds(),
        "expected_days": expected_days(month),
        "normalized_rows": int(row_count),
        "logical_partitions": completion_count,
        "canonical_bytes": int(canonical_bytes),
        "completion_records": 1,
        "revision_rows": revision_count,
        "ordered_read_partitions": ordered_count,
        "transport_stage_residual_objects": len(run_stage_objects),
        "artifacts": [
            {"id": str(a[0]), "sha256": str(a[1]), "bytes": int(a[2])} for a in artifact_rows
        ],
        "coverage": monthly,
        "query_types": query_types,
        "insert_targets": insert_targets,
    }


def main() -> None:
    require_identity()
    store = SnowflakeCheckpointStore()
    results = [measure_run(store, state) for state in selected_runs(store)]
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        cursor.execute("LIST @GOVERNANCE.INGESTION_BULK_STAGE")
        stage_objects = list(cursor.fetchall())
    types: Counter[str] = Counter()
    for result in results:
        types.update(result["query_types"])
    print(
        json.dumps(
            {
                "contract": "nclimgrid-443-first-tranche-review-v1",
                "read_only": True,
                "months": results,
                "totals": {
                    "normalized_rows": sum(int(r["normalized_rows"]) for r in results),
                    "logical_partitions": sum(int(r["logical_partitions"]) for r in results),
                    "canonical_bytes": sum(int(r["canonical_bytes"]) for r in results),
                    "completion_records": len(results),
                    "revision_rows": sum(int(r["revision_rows"]) for r in results),
                    "artifact_count": sum(len(r["artifacts"]) for r in results),
                    "artifact_bytes": sum(int(a["bytes"]) for r in results for a in r["artifacts"]),
                    "query_types": dict(types),
                    "query_count": sum(types.values()),
                    "stage_residual_objects": len(stage_objects),
                    "credits": "UNAVAILABLE",
                    "physical_storage_bytes": "UNAVAILABLE",
                },
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
