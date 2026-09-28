"""Bounded, read-only measurements for the January 2025 nClimGrid DEV pilot."""

from __future__ import annotations

import re
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from lyme_gap_atlas_shared.settings import SnowflakeSettings
from lyme_gap_atlas_shared.snowflake import connect

from ..migrations import load_migrations
from .checkpoints import SnowflakeCheckpointStore
from .nclimgrid_coverage import build_coverage_report
from .types import RunState, RunStatus, Stage

RESOURCE_KEY = "noaa_nclimgrid_daily_202501"
EXPECTED_USER = "OH_LYME_DEV_PIPELINE_SVC"
EXPECTED_ROLE = "OH_LYME_DEV_RUNTIME"
EXPECTED_DATABASE = "ONE_HEALTH_LYME_GAP_ATLAS_DEV"
LEDGER = f"{EXPECTED_DATABASE}.GOVERNANCE.SCHEMA_MIGRATIONS"
V103 = "V103__bounded_ingestion_partitions_and_revisions.sql"
TABLES = (
    "INGESTION_RUN_NORMALIZED_PARTITIONS",
    "INGESTION_RUN_PARTITION_COMPLETIONS",
    "GOVERNED_SOURCE_RECORD_REVISIONS",
)
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class MeasurementError(RuntimeError):
    """A bounded measurement could not be completed safely."""


def _query_one(sql: str, params: tuple[object, ...] = ()) -> tuple[Any, ...] | None:
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def _query_all(sql: str, params: tuple[object, ...] = ()) -> list[tuple[Any, ...]]:
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


def _identity() -> dict[str, object]:
    row = _query_one(
        "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()"
    )
    if row is None:
        raise MeasurementError("INSUFFICIENT_VISIBILITY: runtime identity unavailable")
    settings = SnowflakeSettings()
    values = (str(row[0]), str(row[1]), str(row[2]), str(row[3]))
    expected = (EXPECTED_USER, EXPECTED_ROLE, EXPECTED_DATABASE, settings.snowflake_warehouse)
    matches = tuple(actual == target for actual, target in zip(values, expected, strict=True))
    return {
        "user_matches": matches[0],
        "role_matches": matches[1],
        "database_matches": matches[2],
        "warehouse_matches": matches[3],
        "expected_warehouse": settings.snowflake_warehouse,
    }


def _source_v103_checksum() -> str:
    migration = next((item for item in load_migrations() if item.filename == V103), None)
    if migration is None:
        raise MeasurementError("V103 source is missing")
    return migration.sha256


def _migration_state() -> dict[str, object]:
    rows = _query_all(
        """SELECT version, filename, sha256 FROM GOVERNANCE.SCHEMA_MIGRATIONS
           WHERE version='V103' OR version=(SELECT MAX(version)
             FROM GOVERNANCE.SCHEMA_MIGRATIONS) ORDER BY version"""
    )
    receipt = next((row for row in rows if str(row[0]) == "V103"), None)
    latest = max((row for row in rows), key=lambda row: str(row[0])) if rows else None
    source = _source_v103_checksum()
    ledger = str(receipt[2]) if receipt else None
    return {
        "v103_present": receipt is not None,
        "v103_filename": str(receipt[1]) if receipt else None,
        "v103_ledger_sha256": ledger,
        "v103_source_sha256": source,
        "v103_checksum_matches": ledger == source,
        "latest_version": str(latest[0]) if latest else None,
        "latest_filename": str(latest[1]) if latest else None,
        "latest_sha256": str(latest[2]) if latest else None,
    }


def _runtime_ledger_grants() -> dict[str, object]:
    """Check the runtime's direct ledger grants before reporting pilot readiness."""
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        cursor.execute(f"SHOW GRANTS TO ROLE {EXPECTED_ROLE}")
        columns = [str(item[0]).lower() for item in cursor.description]
        rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    privileges = {
        str(row["privilege"]).upper()
        for row in rows
        if str(row.get("granted_on", "")).upper() == "TABLE"
        and str(row.get("name", "")).upper() == LEDGER
        and str(row.get("grantee_name", "")).upper() == EXPECTED_ROLE
    }
    return {
        "select": "SELECT" in privileges,
        "insert": "INSERT" in privileges,
        "update": "UPDATE" in privileges,
        "delete": "DELETE" in privileges,
        "ownership": "OWNERSHIP" in privileges,
        "unexpected_privileges": sorted(privileges - {"SELECT"}),
        "select_only": privileges == {"SELECT"},
    }


def _table_baseline() -> dict[str, object]:
    result: dict[str, object] = {}
    for table in TABLES:
        count = _query_one(
            f"""SELECT COUNT(*), COALESCE(COUNT_IF(r.resource_key=%s),0)
                FROM GOVERNANCE.{table} t LEFT JOIN GOVERNANCE.INGESTION_RUNS r
                  ON r.ingestion_run_id=t.ingestion_run_id""",
            (RESOURCE_KEY,),
        )
        if count is None:
            raise MeasurementError("INSUFFICIENT_VISIBILITY: V103 table query returned no result")
        result[table] = {
            "row_count": int(count[0]),
            "matching_resource_row_count": int(count[1]),
            "physical_bytes": "UNAVAILABLE",
        }
    partition = _query_one(
        """SELECT COALESCE(SUM(t.byte_count),0),
                  COALESCE(SUM(IFF(r.resource_key=%s,t.byte_count,0)),0)
           FROM GOVERNANCE.INGESTION_RUN_NORMALIZED_PARTITIONS t
           LEFT JOIN GOVERNANCE.INGESTION_RUNS r ON r.ingestion_run_id=t.ingestion_run_id""",
        (RESOURCE_KEY,),
    )
    if partition is not None:
        metrics = result[TABLES[0]]
        assert isinstance(metrics, dict)
        metrics["normalized_byte_count"] = int(partition[0])
        metrics["matching_resource_normalized_byte_count"] = int(partition[1])
    return result


def _candidate_runs(store: SnowflakeCheckpointStore) -> list[RunState]:
    ids = _query_all(
        """SELECT ingestion_run_id FROM GOVERNANCE.INGESTION_RUNS
           WHERE resource_key=%s AND run_mode='SOURCE_INGESTION'
           ORDER BY started_at DESC LIMIT 51""",
        (RESOURCE_KEY,),
    )
    if len(ids) > 50:
        raise MeasurementError("AMBIGUOUS_RUN_STATE: more than 50 matching runs")
    states = [store.load(str(row[0])) for row in ids]
    if any(state is None for state in states):
        raise MeasurementError("INSUFFICIENT_VISIBILITY: a matching run could not be loaded")
    return [state for state in states if state is not None]


def _classify_runs(runs: list[RunState]) -> tuple[str, list[RunState]]:
    from .nclimgrid_longitudinal import definition_mapping

    expected_digest = str(definition_mapping("202501")["source_definition_sha256"])
    runs = [run for run in runs if run.tier.value == "B"]
    for run in runs:
        acquire = run.checkpoint(Stage.ACQUIRE)
        if not acquire or acquire.detail.get("source_definition_sha256") != expected_digest:
            return "AMBIGUOUS_RUN_STATE", runs
    if not runs:
        return "READY_FOR_PILOT", []
    if any(run.status is RunStatus.SUCCEEDED for run in runs):
        return "EXISTING_SUCCESS", runs
    if any(run.status in {RunStatus.PENDING, RunStatus.RUNNING} for run in runs):
        return "EXISTING_NONTERMINAL_RUN", runs
    return "AMBIGUOUS_RUN_STATE", runs


def preflight() -> dict[str, object]:
    try:
        identity = _identity()
        if not all(value is True for key, value in identity.items() if key.endswith("_matches")):
            return {"disposition": "IDENTITY_MISMATCH", "identity": identity}
        migration = _migration_state()
        if not migration["v103_present"] or not migration["v103_checksum_matches"]:
            return {"disposition": "V103_MISMATCH", "identity": identity, "migration": migration}
        ledger_grants = _runtime_ledger_grants()
        if not ledger_grants["select_only"]:
            return {
                "disposition": "LEDGER_GRANT_MISMATCH",
                "identity": identity,
                "migration": migration,
                "ledger_grants": ledger_grants,
            }
        baseline = _table_baseline()
        store = SnowflakeCheckpointStore()
        runs = _candidate_runs(store)
        disposition, matching = _classify_runs(runs)
        artifact = _query_one(
            """SELECT COUNT(*), COALESCE(SUM(a.byte_count),0)
               FROM GOVERNANCE.RAW_ARTIFACTS a JOIN GOVERNANCE.INGESTION_RUNS r
                 ON r.ingestion_run_id=a.ingestion_run_id
               WHERE r.resource_key=%s AND r.run_mode='SOURCE_INGESTION'""",
            (RESOURCE_KEY,),
        )
        if artifact is None:
            raise MeasurementError("INSUFFICIENT_VISIBILITY: artifact baseline unavailable")
        existing_artifacts: list[dict[str, object]] = []
        if matching:
            placeholders = ",".join("%s" for _ in matching)
            artifact_rows = _query_all(
                """SELECT ingestion_run_id, artifact_id, sha256, byte_count
                   FROM GOVERNANCE.RAW_ARTIFACTS
                   WHERE ingestion_run_id IN ("""
                + placeholders
                + ") ORDER BY ingestion_run_id, artifact_id LIMIT 5001",
                tuple(run.ingestion_run_id for run in matching),
            )
            if len(artifact_rows) > 5000:
                raise MeasurementError(
                    "AMBIGUOUS_RUN_STATE: artifact detail exceeds bounded result"
                )
            existing_artifacts = [
                {
                    "run_id": str(row[0]),
                    "artifact_id": str(row[1]),
                    "sha256": str(row[2]),
                    "byte_count": int(row[3]),
                }
                for row in artifact_rows
            ]
        return {
            "disposition": disposition,
            "identity": identity,
            "migration": migration,
            "ledger_grants": ledger_grants,
            "v103_baseline": baseline,
            "matching_tier_b_run_count": len(matching),
            "matching_run_ids": [item.ingestion_run_id for item in matching],
            "matching_run_artifacts": existing_artifacts,
            "matching_artifact_count": int(artifact[0]),
            "matching_artifact_bytes": int(artifact[1]),
            "warehouse_credit_metadata": "UNAVAILABLE_TO_RUNTIME",
            "physical_table_bytes": "UNAVAILABLE_TO_RUNTIME",
        }
    except Exception as exc:
        return {"disposition": "INSUFFICIENT_VISIBILITY", "error_type": type(exc).__name__}


def _run(run_id: str) -> RunState:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise MeasurementError("Invalid run ID")
    state = SnowflakeCheckpointStore().load(run_id)
    if state is None or state.resource_key != RESOURCE_KEY or state.tier.value != "B":
        raise MeasurementError("Run is not the supplied January 2025 Tier B pilot")
    return state


def inspect_run(run_id: str) -> dict[str, object]:
    state = _run(run_id)
    partitions = _query_one(
        """SELECT COUNT(*), COALESCE(SUM(row_count),0), COALESCE(SUM(byte_count),0),
                  MIN(partition_ordinal), MAX(partition_ordinal)
           FROM GOVERNANCE.INGESTION_RUN_NORMALIZED_PARTITIONS WHERE ingestion_run_id=%s""",
        (run_id,),
    )
    completion = _query_one(
        """SELECT partition_count FROM GOVERNANCE.INGESTION_RUN_PARTITION_COMPLETIONS
           WHERE ingestion_run_id=%s""",
        (run_id,),
    )
    revisions = _query_one(
        """SELECT COUNT(*) FROM GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS
           WHERE ingestion_run_id=%s""",
        (run_id,),
    )
    artifacts = _query_all(
        """SELECT artifact_id, sha256, byte_count FROM GOVERNANCE.RAW_ARTIFACTS
           WHERE ingestion_run_id=%s ORDER BY artifact_id""",
        (run_id,),
    )
    if partitions is None or revisions is None:
        raise MeasurementError("INSUFFICIENT_VISIBILITY: run measurements unavailable")
    acquire = state.checkpoint(Stage.ACQUIRE)
    return {
        "run_id": run_id,
        "status": state.status.value,
        "resource_key": state.resource_key,
        "tier": state.tier.value,
        "source_definition_version": state.source_definition_version,
        "source_definition_sha256": acquire.detail.get("source_definition_sha256")
        if acquire
        else None,
        "stages": [
            {
                "stage": stage.stage.value,
                "status": stage.status.value,
                "attempt_count": stage.attempt_count,
                "started_at": stage.started_at,
                "completed_at": stage.completed_at,
                "failure_category": stage.failure_category.value
                if stage.failure_category
                else None,
                "redacted_diagnostic_code": stage.redacted_diagnostic_code,
            }
            for stage in state.stages
        ],
        "partition_count": int(partitions[0]),
        "normalized_row_count": int(partitions[1]),
        "normalized_byte_count": int(partitions[2]),
        "partition_ordinal_min": partitions[3],
        "partition_ordinal_max": partitions[4],
        "completion_partition_count": int(completion[0]) if completion else None,
        "revision_count": int(revisions[0]),
        "artifacts": [
            {"artifact_id": str(a[0]), "sha256": str(a[1]), "byte_count": int(a[2])}
            for a in artifacts
        ],
    }


def ordered_read(run_id: str) -> dict[str, object]:
    _run(run_id)
    store = SnowflakeCheckpointStore()
    completion = _query_one(
        """SELECT partition_count FROM GOVERNANCE.INGESTION_RUN_PARTITION_COMPLETIONS
           WHERE ingestion_run_id=%s""",
        (run_id,),
    )
    if completion is None:
        raise MeasurementError("Partition completion record is missing")
    expected = int(completion[0])
    started = time.perf_counter()
    count = 0
    for ordinal, _partition in enumerate(store.iter_partitions(run_id)):
        if ordinal != _partition.ordinal:
            raise MeasurementError("Partition order is not contiguous")
        count += 1
    elapsed = time.perf_counter() - started
    if count != expected:
        raise MeasurementError("Partition count differs from completion contract")
    return {
        "run_id": run_id,
        "partition_count": count,
        "completion_count": expected,
        "ordered_read_seconds": elapsed,
        "writes_performed": False,
    }


def time_report(run_id: str) -> dict[str, object]:
    state = _run(run_id)
    if state.status is not RunStatus.SUCCEEDED:
        raise MeasurementError("Coverage report requires a succeeded pilot run")
    store = SnowflakeCheckpointStore()

    class OneRunStore:
        def list_runs(self) -> list[RunState]:
            return [state]

        def iter_partitions(self, selected_run_id: str) -> Any:
            if selected_run_id != run_id:
                raise MeasurementError("Report requested another run")
            return store.iter_partitions(run_id)

    with tempfile.TemporaryDirectory(prefix="nclimgrid-pilot-report-") as directory:
        output = Path(directory) / "coverage.csv"
        started = time.perf_counter()
        report = build_coverage_report(
            OneRunStore(), start="202501", end="202501", county_csv=output
        )
        elapsed = time.perf_counter() - started
        months = report["months"]
        return {
            "run_id": run_id,
            "start_month": report["start_month"],
            "end_month": report["end_month"],
            "captured_month_count": report["captured_month_count"],
            "report_seconds": elapsed,
            "report_status": "COMPLETED",
            "csv_bytes": output.stat().st_size,
            "partition_bytes": report["selected_normalized_partition_bytes"],
            "captured_month": months[0] if isinstance(months, list) and months else None,
        }


def benchmark_history(run_id: str) -> dict[str, object]:
    """Read the completed pilot's own query history and transport residue.

    This runs only under the protected DEV runtime user. Query history is scoped
    to that user and the governed run's timestamps; no SQL text is emitted.
    """
    state = _run(run_id)
    identity = _identity()
    if state.status is not RunStatus.SUCCEEDED or not all(
        identity[key]
        for key in ("user_matches", "role_matches", "database_matches", "warehouse_matches")
    ):
        raise MeasurementError("Benchmark history requires a succeeded protected DEV run")
    window = _query_one(
        "SELECT started_at, completed_at FROM GOVERNANCE.INGESTION_RUNS "
        "WHERE ingestion_run_id=%s AND status='COMPLETED'",
        (run_id,),
    )
    if window is None or not isinstance(window[0], datetime) or not isinstance(window[1], datetime):
        raise MeasurementError("Completed governed run window is unavailable")
    started, completed = window
    if started.tzinfo is None or completed.tzinfo is None or completed <= started:
        raise MeasurementError("Invalid governed run window")
    lower = (started - timedelta(minutes=5)).isoformat()
    upper = (completed + timedelta(minutes=5)).isoformat()
    history_sql = (
        "SELECT QUERY_ID, QUERY_TYPE, QUERY_TEXT, START_TIME, END_TIME "
        "FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_USER("
        f"END_TIME_RANGE_START=>TO_TIMESTAMP_LTZ('{lower}'), "
        f"END_TIME_RANGE_END=>TO_TIMESTAMP_LTZ('{upper}'), RESULT_LIMIT=>10000))"
    )
    with connect(SnowflakeSettings()) as connection, connection.cursor() as cursor:
        cursor.execute(history_sql)
        rows = list(cursor.fetchall())
        if len(rows) == 10000:
            raise MeasurementError("Query history result hit Snowflake's 10000-row limit")
        cursor.execute(f"LIST @GOVERNANCE.INGESTION_BULK_STAGE/{run_id}/")
        objects = list(cursor.fetchall())
    selected = [
        row for row in rows if isinstance(row[3], datetime) and started <= row[3] <= completed
    ]
    if not selected:
        raise MeasurementError("No protected runtime queries visible in governed run window")
    counts = Counter(str(row[1]).upper() for row in selected)
    paths: dict[str, list[tuple[Any, ...]]] = {
        "checkpoint": [],
        "staging": [],
        "conformed": [],
        "raw": [],
        "revisions": [],
    }
    for row in selected:
        sql = str(row[2]).upper()
        if "INGESTION_RUN_NORMALIZED_PARTITIONS" in sql:
            paths["checkpoint"].append(row)
        if "STAGING." in sql:
            paths["staging"].append(row)
        if "CONFORMED." in sql:
            paths["conformed"].append(row)
        if "RAW." in sql:
            paths["raw"].append(row)
        if "GOVERNED_SOURCE_RECORD_REVISIONS" in sql:
            paths["revisions"].append(row)

    def span(path_rows: list[tuple[Any, ...]]) -> dict[str, object]:
        starts = [row[3] for row in path_rows if isinstance(row[3], datetime)]
        ends = [row[4] for row in path_rows if isinstance(row[4], datetime)]
        return {
            "query_count": len(path_rows),
            "first_start": min(starts).isoformat() if starts else None,
            "last_end": max(ends).isoformat() if ends else None,
            "span_seconds": (max(ends) - min(starts)).total_seconds() if starts and ends else None,
        }

    return {
        "run_id": run_id,
        "run_started_at": started.isoformat(),
        "run_completed_at": completed.isoformat(),
        "run_seconds": (completed - started).total_seconds(),
        "query_count": len(selected),
        "query_type_counts": dict(sorted(counts.items())),
        "path_spans": {name: span(path_rows) for name, path_rows in paths.items()},
        "transport_object_count": len(objects),
        "transport_object_bytes": sum(int(row[1]) for row in objects),
        "history_scope": "current protected runtime user, governed run window",
    }
