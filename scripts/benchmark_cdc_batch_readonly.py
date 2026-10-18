"""Explicit opt-in: eight bounded PROD SELECTs via named reader; safe metrics only.

One identity + four singleton + two pair batch + one query-history SELECT.
No retries, settings, DDL/DML, payload files, credentials or public API requests.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from lyme_gap_atlas_data.cdc_consumer_admission import SLICES, TARGET_RELEASE_ID
from lyme_gap_atlas_data.cdc_consumer_batch import _authority_sql, produce_cdc_batch_v1
from lyme_gap_atlas_data.cdc_consumer_runtime import (
    AUTHORITY_SQL,
    IDENTITY_SQL,
    _project,
    _resources,
)

CASES = {"scapularis_status": ("01001", "13081"), "burgdorferi_status": ("06001", "19135")}


def _literal_sql(sql: str, params: tuple[str, ...]) -> str:
    # snow CLI has no connector binds: only source-controlled/validated literals.
    for value in params:
        if re.fullmatch(r"[a-zA-Z0-9_.:-]+", value) is None:
            raise ValueError("invalid benchmark literal")
        sql = sql.replace("%s", "'" + value + "'", 1)
    if "%s" in sql:
        raise ValueError("unbound benchmark SQL")
    return sql


def run(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    run_id = "cdc_batch_benchmark_v1_" + uuid4().hex
    window_start = datetime.now(UTC).isoformat()
    receipts: list[dict[str, Any]] = []
    statements = 0

    def select(sql: str, label: str) -> list[dict[str, Any]]:
        nonlocal statements
        statements += 1
        if statements > 8:
            raise ValueError("benchmark SQL budget exceeded")
        started = time.perf_counter()
        result = subprocess.run(
            [
                "snow",
                "sql",
                "--silent",
                "--connection",
                "ATLAS_PROD_READ",
                "--database",
                "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
                "--warehouse",
                "COMPUTE_WH",
                "--secondary-roles",
                "NONE",
                "--format",
                "JSON",
                "--query",
                f"/* {run_id}_{label} */\n{sql}",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        rows = json.loads(result.stdout)
        receipts.append(
            {
                "label": label,
                "cli_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "logical_result_json_bytes": len(
                    json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                ),
                "row_count": len(rows),
            }
        )
        return list(rows)

    try:
        identity = select(IDENTITY_SQL, "identity")
        if len(identity) != 1 or (
            identity[0].get("ROLE") != "OH_LYME_PROD_READ"
            or identity[0].get("DATABASE") != "ONE_HEALTH_LYME_GAP_ATLAS_PROD"
            or identity[0].get("WAREHOUSE") != "COMPUTE_WH"
            or not identity[0].get("USER")
        ):
            raise ValueError("intended reader unavailable")
        for measure, counties in CASES.items():
            baselines = {}
            expected = []
            for county in counties:
                params = (TARGET_RELEASE_ID, measure, county, SLICES[measure]["source_version_id"])
                baselines[county] = select(
                    _literal_sql(AUTHORITY_SQL, params), measure + "_" + county
                )

                def singleton_query(
                    sql: str,
                    params: tuple[str, ...],
                    captured: dict[str, list[dict[str, Any]]] = baselines,
                ) -> list[dict[str, Any]]:
                    return identity if sql == IDENTITY_SQL else captured[params[2]]

                expected.append(
                    _project(
                        singleton_query,
                        _resources(),
                        measure,
                        county,
                        "prod",
                        release_id=TARGET_RELEASE_ID,
                    )
                )
            params = (TARGET_RELEASE_ID, measure, SLICES[measure]["source_version_id"], *counties)
            actual_rows = select(
                _literal_sql(_authority_sql(len(counties)), params), measure + "_batch2"
            )

            def batch_query(
                sql: str,
                params: tuple[str, ...],
                captured: list[dict[str, Any]] = actual_rows,
            ) -> list[dict[str, Any]]:
                return identity if sql == IDENTITY_SQL else captured

            actual = produce_cdc_batch_v1(batch_query, measure, counties)
            if actual.observations != tuple(expected):
                raise ValueError("real reader batch/singleton parity failed")
            receipts[-1]["scientific_parity"] = "PASS: full consumer-safe equality both counties"
            # Never persist or print the restricted raw rows or result payloads.
            del baselines, actual_rows, actual, expected
        history = select(
            f"""SELECT query_id, query_text, start_time::VARCHAR AS start_time,
 total_elapsed_time, compilation_time, execution_time,
 queued_provisioning_time+queued_repair_time+queued_overload_time AS queued_ms,
 bytes_scanned, rows_produced, bytes_written_to_result, execution_status
 FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
 END_TIME_RANGE_START=>'{window_start}'::TIMESTAMP_LTZ,RESULT_LIMIT=>1000))
 WHERE query_type='SELECT'
 AND query_text ILIKE '%FROM LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V%'
 AND query_text NOT ILIKE '%QUERY_HISTORY%'
 ORDER BY start_time""",
            "history",
        )
        safe_history = []
        for row in history:
            text = row.pop("QUERY_TEXT")
            marker = re.search(re.escape(run_id) + r"_([a-zA-Z0-9_]+)", text)
            if marker:
                label = marker.group(1)
            else:
                # The CLI may strip comments. Correlate the bounded window and
                # closed source-controlled query shapes; never persist SQL text.
                measures = [measure for measure in CASES if measure in text]
                if len(measures) != 1:
                    raise ValueError("ambiguous benchmark history")
                measure = measures[0]
                if "AS batch_authority" in text:
                    label = measure + "_batch2"
                else:
                    counties = [county for county in CASES[measure] if "'" + county + "'" in text]
                    if len(counties) != 1:
                        raise ValueError("ambiguous singleton history")
                    label = measure + "_" + counties[0]
            row["LABEL"] = label
            row["CACHE_CLASSIFICATION"] = "unproven; secure scan metrics not cache proof"
            safe_history.append(row)
        expected_labels = {
            measure + "_" + suffix
            for measure, counties in CASES.items()
            for suffix in (*counties, "batch2")
        }
        if len(safe_history) != 6 or {row["LABEL"] for row in safe_history} != expected_labels:
            raise ValueError("incomplete or ambiguous benchmark history")
        if safe_history:
            with (output / "query_history.csv").open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(safe_history[0]))
                writer.writeheader()
                writer.writerows(safe_history)
        (output / "metrics.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "statements": statements,
                    "receipts": receipts,
                    "environment": "prod",
                    "role": "OH_LYME_PROD_READ",
                    "limitations": "one sample/case; separate CLI sessions; "
                    "CLI elapsed includes auth; "
                    "JSON logical bytes are not compressed wire bytes; no cache manipulation; "
                    "live SELECT rows revalidated locally, not deployed batch/API evidence",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print("Bounded read-only comparison complete; safe metrics only: " + str(output))
    except Exception:
        (output / "failure.json").write_text(
            json.dumps(
                {
                    "statements_submitted": statements,
                    "status": "failed closed; private driver/authority diagnostics suppressed",
                    "completed_safe_receipts": receipts,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        raise SystemExit("CDC benchmark failed closed; no retries or private diagnostics") from None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-prod-readonly", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output)
