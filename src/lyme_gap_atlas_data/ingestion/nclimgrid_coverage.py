"""Reproducible longitudinal coverage from governed run and partition ledgers."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any, Protocol

from .nclimgrid_longitudinal import expected_days, months
from .types import RunState, RunStatus, Stage

MEASURES = ("PRCP", "TMIN", "TMAX", "TAVG")
STATUSES = (
    "COMPLETE",
    "PARTIAL_COVERAGE",
    "SOURCE_MISSING",
    "OUT_OF_SOURCE_COVERAGE",
)
PREFIX = "noaa_nclimgrid_daily_"


def canonical_counties() -> frozenset[str]:
    """Load the governed 2022 county identities used by #198 normalization."""
    identities = (
        files("lyme_gap_atlas_data")
        .joinpath("data/canonical-county-fips-2022.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    if (
        not identities
        or len(identities) != len(set(identities))
        or any(len(value) != 5 or not value.isdigit() for value in identities)
    ):
        raise ValueError("Invalid packaged canonical county identity asset")
    return frozenset(identities)


class CoverageStore(Protocol):
    def list_runs(self) -> list[RunState]: ...

    def iter_partitions(self, run_id: str) -> Any: ...


def _stamp(run: RunState) -> tuple[str, str]:
    acquire = run.checkpoint(Stage.ACQUIRE)
    return (acquire.completed_at or "" if acquire else "", run.ingestion_run_id)


def _elapsed_seconds(run: RunState) -> float | None:
    acquire = run.checkpoint(Stage.ACQUIRE)
    published = run.checkpoint(Stage.PUBLISH_STAGE)
    if not acquire or not published or not acquire.started_at or not published.completed_at:
        return None
    return (
        datetime.fromisoformat(published.completed_at) - datetime.fromisoformat(acquire.started_at)
    ).total_seconds()


def _month_runs(runs: list[RunState], selected: set[str]) -> dict[str, list[RunState]]:
    result: dict[str, list[RunState]] = defaultdict(list)
    for run in runs:
        if run.resource_key.startswith(PREFIX):
            month = run.resource_key[len(PREFIX) :]
            if month in selected:
                result[month].append(run)
    return result


def selected_successful_runs(runs: list[RunState]) -> list[RunState]:
    """Keep a failed recapture from replacing the last completed capture."""
    return sorted((run for run in runs if run.status is RunStatus.SUCCEEDED), key=_stamp)


def build_coverage_report(
    store: CoverageStore,
    *,
    start: str,
    end: str,
    county_csv: Path,
) -> dict[str, object]:
    """Stream selected completed captures into one county-month-measure CSV.

    At most one month's county/measure counters and row identities are held in
    memory. A failed recapture cannot replace an earlier successful capture.
    """
    expected = months(start, end)
    expected_counties = canonical_counties()
    runs_by_month = _month_runs(store.list_runs(), set(expected))
    county_csv.parent.mkdir(parents=True, exist_ok=True)
    temporary = county_csv.with_name(county_csv.name + ".tmp")
    month_reports: list[dict[str, object]] = []
    measure_history: dict[str, list[str]] = {measure: [] for measure in MEASURES}
    total_retained_bytes = 0
    total_partition_bytes = 0
    total_runtime_seconds = 0.0
    fieldnames = [
        "month",
        "county_fips",
        "measure",
        "run_id",
        "expected_days",
        "observed_days",
        "source_time_days",
        *[status.lower() for status in STATUSES],
        "source_supported_area_m2",
        "source_coverage_fraction",
        "all_days_complete",
        "historical_publication_time_known",
    ]
    try:
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for month in expected:
                runs = runs_by_month.get(month, [])
                successes = selected_successful_runs(runs)
                failed = sorted(
                    run.ingestion_run_id for run in runs if run.status is RunStatus.FAILED
                )
                in_progress = sorted(
                    run.ingestion_run_id
                    for run in runs
                    if run.status in {RunStatus.PENDING, RunStatus.RUNNING}
                )
                review_required = sorted(
                    run.ingestion_run_id
                    for run in runs
                    if run.status
                    in {
                        RunStatus.EXCEPTION_REVIEW,
                        RunStatus.OPERATOR_INTERVENTION,
                        RunStatus.POLICY_BLOCKED,
                        RunStatus.PAUSED,
                    }
                )
                unavailable = sorted(
                    run.ingestion_run_id
                    for run in runs
                    if run.status is RunStatus.FAILED
                    if (checkpoint := run.checkpoint(Stage.ACQUIRE))
                    and checkpoint.redacted_diagnostic_code == "NCLIMGRID_UNAVAILABLE"
                )
                digests = sorted(
                    {
                        checkpoint.artifact_sha256
                        for run in successes
                        if (checkpoint := run.checkpoint(Stage.ACQUIRE))
                        and checkpoint.artifact_sha256
                    }
                )
                if not successes:
                    missing_status = (
                        "IN_PROGRESS"
                        if in_progress
                        else "REVIEW_REQUIRED"
                        if review_required
                        else "UNAVAILABLE"
                        if failed and len(unavailable) == len(failed)
                        else "FAILED"
                        if failed
                        else "NOT_ATTEMPTED"
                    )
                    month_reports.append(
                        {
                            "month": month,
                            "status": missing_status,
                            "attempted_tiers": sorted({run.tier.value for run in runs}),
                            "failed_run_ids": failed,
                            "in_progress_run_ids": in_progress,
                            "review_required_run_ids": review_required,
                            "unavailable_run_ids": unavailable,
                            "expected_days": expected_days(month),
                            "observed_days": 0,
                        }
                    )
                    continue
                run = successes[-1]
                acquire = run.checkpoint(Stage.ACQUIRE)
                if acquire is None or not acquire.artifact_sha256:
                    raise ValueError(f"Successful nClimGrid run lacks ACQUIRE digest: {month}")
                counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
                support: dict[tuple[str, str], tuple[float | None, float | None]] = {}
                county_support: dict[str, tuple[float | None, float | None]] = {}
                seen: set[tuple[str, str, str]] = set()
                observed: set[str] = set()
                represented: set[str] = set()
                source_supported: set[str] = set()
                low_source_support: set[str] = set()
                status_totals: Counter[str] = Counter()
                normalized_bytes = 0
                partition_count = 0
                upstream_date_modified: set[str] = set()
                for partition in store.iter_partitions(run.ingestion_run_id):
                    partition_count += 1
                    normalized_bytes += partition.byte_count
                    for output in partition.records:
                        record = output.get("record")
                        if not isinstance(record, dict):
                            raise ValueError("Normalized nClimGrid record is missing")
                        county = str(record["county_fips"])
                        if county not in expected_counties:
                            raise ValueError(
                                f"Unexpected canonical county identity in {month}: {county}"
                            )
                        day = str(record["observation_date"])
                        measure = str(record["measure"])
                        status = str(record["coverage_status"])
                        if (
                            day[:7].replace("-", "") != month
                            or measure not in MEASURES
                            or status not in STATUSES
                            or record.get("noaa_sha256") != acquire.artifact_sha256
                        ):
                            raise ValueError(f"nClimGrid lineage or status drift in {month}")
                        identity = (county, day, measure)
                        if identity in seen:
                            raise ValueError(f"Duplicate county-day-measure in {month}")
                        seen.add(identity)
                        key = (county, measure)
                        counts[key][status] += 1
                        counts[key]["observed_days"] += 1
                        if record.get("source_time_present") is True:
                            counts[key]["source_time_days"] += 1
                            observed.add(day)
                        current_support = (
                            float(record["source_supported_area_m2"])
                            if record.get("source_supported_area_m2") is not None
                            else None,
                            float(record["source_coverage_fraction"])
                            if record.get("source_coverage_fraction") is not None
                            else None,
                        )
                        if (key in support and support[key] != current_support) or (
                            county in county_support and county_support[county] != current_support
                        ):
                            raise ValueError(f"Monthly nClimGrid source support changed: {month}")
                        support[key] = current_support
                        county_support[county] = current_support
                        if not county.startswith(("02", "15")):
                            represented.add(county)
                            supported_area = support[key][0]
                            if supported_area is not None and supported_area > 0:
                                source_supported.add(county)
                            source_fraction = support[key][1]
                            if source_fraction is not None and source_fraction < 0.95:
                                low_source_support.add(county)
                        status_totals[status] += 1
                        upstream_date_modified.add(str(record.get("upstream_date_modified", "")))
                days = expected_days(month)
                if (
                    {county for county, _measure in counts} != expected_counties
                    or len(counts) != len(expected_counties) * len(MEASURES)
                    or len(seen) != len(expected_counties) * days * len(MEASURES)
                ):
                    raise ValueError(f"Incomplete normalized nClimGrid county-day matrix: {month}")
                first_day = date(int(month[:4]), int(month[4:]), 1)
                missing_source_days = [
                    (first_day + timedelta(days=offset)).isoformat()
                    for offset in range(days)
                    if (first_day + timedelta(days=offset)).isoformat() not in observed
                ]
                for (county, measure), detail in sorted(counts.items()):
                    supported_area, source_fraction = support[(county, measure)]
                    all_complete = detail["COMPLETE"] == days
                    writer.writerow(
                        {
                            "month": month,
                            "county_fips": county,
                            "measure": measure,
                            "run_id": run.ingestion_run_id,
                            "expected_days": days,
                            "observed_days": detail["observed_days"],
                            "source_time_days": detail["source_time_days"],
                            **{status.lower(): detail[status] for status in STATUSES},
                            "source_supported_area_m2": supported_area,
                            "source_coverage_fraction": source_fraction,
                            "all_days_complete": all_complete,
                            "historical_publication_time_known": False,
                        }
                    )
                    if all_complete and month not in measure_history[measure]:
                        measure_history[measure].append(month)
                artifacts = acquire.detail.get("artifacts", [])
                artifact_bytes = sum(
                    int(item["byte_count"]) for item in artifacts if isinstance(item, dict)
                )
                runtime_seconds = _elapsed_seconds(run)
                total_retained_bytes += artifact_bytes
                total_partition_bytes += normalized_bytes
                total_runtime_seconds += runtime_seconds or 0.0
                monthly_support = {county: county_support[county] for county in sorted(represented)}
                support_digest = hashlib.sha256(
                    json.dumps(monthly_support, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                month_reports.append(
                    {
                        "month": month,
                        "status": "CAPTURED",
                        "selected_tier": run.tier.value,
                        "attempted_tiers": sorted({item.tier.value for item in runs}),
                        "selected_run_id": run.ingestion_run_id,
                        "failed_run_ids": failed,
                        "in_progress_run_ids": in_progress,
                        "review_required_run_ids": review_required,
                        "unavailable_run_ids": unavailable,
                        "successful_run_ids": [r.ingestion_run_id for r in successes],
                        "unique_noaa_digests": digests,
                        "revision_count": max(0, len(digests) - 1),
                        "expected_days": days,
                        "observed_days": len(observed),
                        "missing_source_days": missing_source_days,
                        "conus_counties_represented": len(represented),
                        "source_supported_counties": len(source_supported),
                        "counties_below_95_percent_source_support": len(low_source_support),
                        "county_support_signature_sha256": support_digest,
                        "county_day_measure_statuses": dict(status_totals),
                        "normalized_partition_count": partition_count,
                        "normalized_partition_bytes": normalized_bytes,
                        "retained_artifact_bytes": artifact_bytes,
                        "runtime_seconds": runtime_seconds,
                        "upstream_date_modified": sorted(upstream_date_modified),
                        "retrieved_at": acquire.completed_at,
                        "upstream_last_modified": acquire.detail.get("upstream_last_modified"),
                        "original_publication_time": None,
                    }
                )
        temporary.replace(county_csv)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "contract": "nclimgrid-longitudinal-coverage-v1",
        "start_month": start,
        "end_month": end,
        "expected_month_count": len(expected),
        "captured_month_count": sum(item["status"] == "CAPTURED" for item in month_reports),
        "captured_months_by_tier": dict(
            Counter(
                str(item["selected_tier"]) for item in month_reports if item["status"] == "CAPTURED"
            )
        ),
        "not_attempted_months": [
            item["month"] for item in month_reports if item["status"] == "NOT_ATTEMPTED"
        ],
        "unavailable_months": [
            item["month"] for item in month_reports if item["status"] == "UNAVAILABLE"
        ],
        "failed_months": [item["month"] for item in month_reports if item["status"] == "FAILED"],
        "in_progress_months": [
            item["month"] for item in month_reports if item["status"] == "IN_PROGRESS"
        ],
        "review_required_months": [
            item["month"] for item in month_reports if item["status"] == "REVIEW_REQUIRED"
        ],
        "months_with_at_least_one_all_complete_county_by_measure": measure_history,
        "historical_publication_time": "UNAVAILABLE",
        "selected_retained_artifact_bytes": total_retained_bytes,
        "selected_normalized_partition_bytes": total_partition_bytes,
        "selected_run_runtime_seconds": total_runtime_seconds,
        "county_period_csv_bytes": county_csv.stat().st_size,
        "county_period_csv": str(county_csv),
        "months": month_reports,
    }


def write_report_json(report: dict[str, object], path: Path) -> None:
    """Write a deterministic JSON rendering of the governed report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
