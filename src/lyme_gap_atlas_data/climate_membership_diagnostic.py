"""One bounded, read-only diagnostic of the existing January exporter."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import shutil
import signal
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .climate_membership import (
    ARTIFACT_NAME,
    MembershipBlocked,
    freeze_membership,
    read_donor_handoff,
)

RECEIPT_NAME = "january-membership-diagnostic-receipt.json"
MAX_STATEMENTS = 40
MAX_SECONDS = 300
MAX_EXECUTION_SECONDS = 50
# Preserve the completed run's full reservation; do not infer charges from elapsed time.
PRIOR_DIAGNOSTIC_FORECAST_USD = 6.836666666666667
APPROVED_TOTAL_FORECAST_USD = 10
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024


class DiagnosticStop(ValueError):
    """Finite reason; never a driver message."""


def no_retry_backoff():  # type: ignore[no-untyped-def]
    """Connector consumes once when creating context; fail before retry increment."""
    yield 0
    raise DiagnosticStop("AUTOMATIC_RETRY_PROHIBITED")


def budget_evidence(document: str) -> dict[str, Any]:
    try:
        value = json.loads(document)
    except (ValueError, TypeError):
        raise DiagnosticStop("BILLING_PRICE_RECEIPT_REQUIRED") from None
    if (
        not isinstance(value, dict)
        or not {
            "unit_price_usd",
            "evidence_reference",
            "verified_by",
            "verified_at",
        }.issubset(value)
        or set(value)
        - {
            "unit_price_usd",
            "evidence_reference",
            "verified_by",
            "verified_at",
            "region",
            "standard_capability_evidence",
        }
    ):
        raise DiagnosticStop("BILLING_PRICE_RECEIPT_REQUIRED")
    price = value["unit_price_usd"]
    if type(price) not in (int, float) or not math.isfinite(price) or not 0 < price <= 20:
        raise DiagnosticStop("BILLING_PRICE_OUTSIDE_APPROVED_CEILING")
    reference = value["evidence_reference"]
    if isinstance(reference, str) and reference.startswith("https://"):
        url = urlsplit(reference)
        if (
            url.netloc not in {"www.snowflake.com", "docs.snowflake.com"}
            or url.query
            or url.fragment
            or url.username
            or url.password
            or any(ord(c) < 33 for c in reference)
            or not isinstance(value.get("region"), str)
            or re.fullmatch(r"(?:AWS|AZURE|GCP)_[A-Z0-9_]+", value["region"]) is None
        ):
            raise DiagnosticStop("OFFICIAL_FORECAST_REFERENCE_REQUIRED")
        value["basis"] = "OFFICIAL_PUBLIC_PRICE_FORECAST_NOT_ACCOUNT_INVOICE"
    else:
        raise DiagnosticStop("PUBLIC_PRICING_ONLY_NO_PRIVATE_BILLING_INPUT")
    for key in ("verified_by",):
        if (
            not isinstance(value[key], str)
            or re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", value[key]) is None
        ):
            raise DiagnosticStop("BILLING_PRICE_RECEIPT_REQUIRED")
    try:
        verified = datetime.fromisoformat(value["verified_at"].replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise DiagnosticStop("BILLING_PRICE_RECEIPT_REQUIRED") from None
    if verified.tzinfo is None or not 0 <= (datetime.now(UTC) - verified).total_seconds() <= 604800:
        raise DiagnosticStop("BILLING_PRICE_RECEIPT_STALE")
    if "standard_capability_evidence" in value:
        capability = value["standard_capability_evidence"]
        if (
            not isinstance(capability, dict)
            or set(capability)
            != {
                "edition",
                "cloud",
                "account_locator_sha256",
                "verified_by",
                "verified_at",
                "evidence_reference",
            }
            or capability.get("edition") != "STANDARD"
            or capability.get("cloud") != "AWS"
            or re.fullmatch(r"[0-9a-f]{64}", str(capability.get("account_locator_sha256"))) is None
            or not isinstance(capability.get("verified_by"), str)
            or re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", str(capability.get("verified_by"))) is None
            or capability.get("evidence_reference") != "OWNER_SNOWSIGHT_ACCOUNT_DETAILS"
        ):
            raise DiagnosticStop("STANDARD_CAPABILITY_EVIDENCE_REQUIRED")
        try:
            checked = datetime.fromisoformat(capability["verified_at"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise DiagnosticStop("STANDARD_CAPABILITY_EVIDENCE_REQUIRED") from None
        # The owner assertion is bound to the live account and warehouse below.
        # An elapsed day alone does not invalidate that account-scoped assertion.
        if checked.tzinfo is None or (datetime.now(UTC) - checked).total_seconds() < 0:
            raise DiagnosticStop("STANDARD_CAPABILITY_EVIDENCE_INVALID_TIME")
    return value


def producer_forecast(price: float) -> float:
    """Reserve the full bounded donor session, including its own idle tail."""
    return (60 * 5.75 / 3600 + 1.35 / 30) * price


def budget_runtime(price: float) -> int:
    # Gen2 XS: 1.35 credits/hour; cloud services: 4.4, without daily adjustment.
    # Retain the approved 15-second allowance and two one-minute warehouse idle
    # tails (1.35/30 credits), even though Standard needs no extra property GET.
    remaining_compute_usd = (
        APPROVED_TOTAL_FORECAST_USD - PRIOR_DIAGNOSTIC_FORECAST_USD - producer_forecast(price) - 1
    )
    seconds = math.floor(((remaining_compute_usd / price - 1.35 / 30) * 3600) / 5.75) - 15
    if seconds < 30:
        raise DiagnosticStop("FORECAST_EXCEEDS_APPROVED_TOTAL_CAP")
    return min(MAX_EXECUTION_SECONDS, seconds)


def stage_for(sql: str) -> str:
    if "CURRENT_USER" in sql:
        return "IDENTITY"
    if "r.source_manifest" in sql:
        return "ANNUAL_DONOR"
    if "CURRENT_RELEASE_V" in sql:
        return "CURRENT_RELEASE_RECHECK"
    if "SEMANTIC_RELEASE_POINTER" in sql:
        return "POINTER_RECHECK"
    if "RAW_ARTIFACTS" in sql:
        return "ARTIFACT_RECEIPT"
    if "INGESTION_RUNS" in sql:
        return "SELECTED_RUN"
    if "ORDER BY capture_record_id" in sql:
        return "ORDERED_MEMBERSHIP"
    if "GOVERNED_SOURCE_RECORD_REVISIONS" in sql:
        return "MEMBERSHIP_COUNT"
    return "PREFLIGHT"


def category(error: Exception) -> str:
    if getattr(error, "errno", None) == 2003:
        return "OBJECT_OR_ACCESS_UNAVAILABLE"
    if isinstance(error, DiagnosticStop):
        return str(error)
    if isinstance(error, MembershipBlocked):
        return str(error) if re.fullmatch(r"MEMBERSHIP_[A-Z_]+", str(error)) else "CONTRACT_FAILURE"
    return "READ_DEPENDENCY_UNAVAILABLE"


class BoundedCursor:
    def __init__(self, cursor: Any, started: float, receipt: dict[str, Any]):
        self.cursor, self.started, self.receipt = cursor, started, receipt
        self.stage = "PREFLIGHT"
        self.prior_query_id: str | None = None
        self.active_statement = False

    def check(self) -> float:
        remaining = float(self.receipt.get("runtime_limit_seconds", MAX_EXECUTION_SECONDS)) - (
            time.monotonic() - self.started
        )
        if remaining <= 1:
            raise DiagnosticStop("RUNTIME_LIMIT")
        return remaining

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        remaining = self.check()
        if self.receipt["statements"] >= min(
            MAX_STATEMENTS, self.receipt.get("statement_limit", MAX_STATEMENTS)
        ):
            raise DiagnosticStop("STATEMENT_LIMIT")
        if not sql.startswith(("SELECT ", "SHOW ")):
            raise DiagnosticStop("READ_ONLY_REQUIRED")
        self.stage = stage_for(sql)
        self.receipt["statements"] += 1
        self.prior_query_id = safe_query_id(getattr(self.cursor, "sfqid", None))
        try:
            self.active_statement = True
            self.cursor.execute(
                sql,
                params,
                timeout=min(15, self.receipt.get("statement_timeout_seconds", 15), int(remaining)),
            )
        except Exception as error:
            self.receipt.setdefault(
                "failure",
                {
                    "stage": self.stage,
                    "category": category(error),
                    "query_id": failure_query_id(error, self.cursor, self.prior_query_id),
                },
            )
            raise DiagnosticStop("READ_FAILED") from None
        finally:
            self.active_statement = False
        self.receipt.setdefault("query_ids", []).append(
            safe_query_id(getattr(self.cursor, "sfqid", None))
        )

    def fetchone(self) -> Any:
        self.check()
        self.reject_remote_batches()
        return self.cursor.fetchone()

    def fetchall(self) -> Any:
        self.check()
        self.reject_remote_batches()
        return self.cursor.fetchall()

    def fetchmany(self, size: int) -> Any:
        self.check()
        self.reject_remote_batches()
        return self.cursor.fetchmany(size)

    def reject_remote_batches(self) -> None:
        # Supported public ResultBatch metadata, checked before any iterator can
        # launch prefetch/download. The pinned SDK's chunk retry loop differs
        # from request retries; this diagnostic permits inline result data only.
        batches = self.cursor.get_result_batches()
        if any(batch.compressed_size is not None for batch in batches or []):
            raise DiagnosticStop("REMOTE_RESULT_BATCH_REQUIRES_SEPARATE_REVIEW")


def safe_query_id(value: Any) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f-]{36}", value) else None


def failure_query_id(error: Exception, cursor: Any, prior: str | None) -> str | None:
    direct = safe_query_id(getattr(error, "sfqid", None))
    current = safe_query_id(getattr(cursor, "sfqid", None))
    return direct or (current if current != prior else None)


def verify_donor_account_binding(donor: dict[str, Any], identity: Any) -> None:
    if (
        not isinstance(identity, tuple)
        or len(identity) != 6
        or not isinstance(identity[5], str)
        or hashlib.sha256(identity[5].upper().encode()).hexdigest()
        != donor.get("account_locator_sha256")
        or identity[4] != donor.get("region")
    ):
        raise DiagnosticStop("MEMBERSHIP_DONOR_ACCOUNT_BINDING")


def validate_warehouse_cost(
    warehouse: dict[str, Any], evidence: dict[str, Any], region: str, receipt: dict[str, Any]
) -> None:
    """Shared observed XS bounds; Standard entitlement never fabricates settings."""
    capability = evidence.get("standard_capability_evidence")
    generation = str(warehouse.get("generation")).upper()
    cost_fields = (
        "size",
        "type",
        "generation",
        "max_cluster_count",
        "min_cluster_count",
        "enable_query_acceleration",
        "auto_suspend",
    )
    safe_strings = {
        "X-Small",
        "STANDARD",
        "1",
        "GEN_1",
        "GEN1",
        "2",
        "GEN_2",
        "GEN2",
        "true",
        "false",
        "TRUE",
        "FALSE",
        "60",
    }
    receipt["warehouse_cost_observation"] = {
        key: {
            "present": key in warehouse,
            "python_type": type(warehouse.get(key)).__name__,
            "value": value
            if value is None
            or type(value) in (bool, int, float)
            or isinstance(value, str)
            and value in safe_strings
            else "UNRECOGNIZED_REDACTED",
        }
        for key in cost_fields
        for value in (warehouse.get(key),)
    }
    try:
        suspend_verified = 0 < int(warehouse.get("auto_suspend", 0)) <= 60
    except (TypeError, ValueError, OverflowError):
        suspend_verified = False
    checks = {
        "size": warehouse.get("size") == "X-Small",
        "type": warehouse.get("type") == "STANDARD",
        "generation": generation in ("1", "GEN_1", "GEN1", "2", "GEN_2", "GEN2"),
        "max_cluster_count": type(warehouse.get("max_cluster_count")) is int
        and warehouse.get("max_cluster_count") == 1,
        "enable_query_acceleration": warehouse.get("enable_query_acceleration") is False,
        "auto_suspend": suspend_verified,
    }
    if capability:
        # Edition entitlement bounds costs; this is NOT a conversion of
        # missing/zero SHOW fields into observed settings. Contradictory
        # positive settings still fail closed.
        clusters = warehouse.get("max_cluster_count")
        minimum = warehouse.get("min_cluster_count")
        acceleration = warehouse.get("enable_query_acceleration")
        checks["max_cluster_count"] = clusters is None or (
            type(clusters) is int and clusters in (0, 1)
        )
        checks["min_cluster_count"] = minimum is None or (
            type(minimum) is int and minimum in (0, 1)
        )
        checks["enable_query_acceleration"] = acceleration is None or acceleration is False
        receipt["edition_cost_capabilities"] = {
            "basis": "OWNER_VERIFIED_STANDARD_EDITION",
            "multicluster": "UNAVAILABLE",
            "query_acceleration": "UNAVAILABLE",
            "compute_cluster_cost_bound": 1,
            "references": [
                "https://docs.snowflake.com/en/user-guide/warehouses-multicluster",
                "https://docs.snowflake.com/en/user-guide/query-acceleration-service",
            ],
        }
    receipt["warehouse_cost_failed_fields"] = [key for key, passed in checks.items() if not passed]
    if receipt["warehouse_cost_failed_fields"]:
        raise DiagnosticStop("WAREHOUSE_COST_ASSUMPTIONS_UNVERIFIED")
    cloud = str(region).split("_", 1)[0]
    if cloud not in {"AWS", "AZURE", "GCP"}:
        raise DiagnosticStop("WAREHOUSE_CLOUD_RATE_UNVERIFIED")
    receipt["published_warehouse_credits_per_hour"] = (
        1 if generation in ("1", "GEN_1", "GEN1") else 1.25 if cloud == "AZURE" else 1.35
    )
    receipt["consumption_reference"] = (
        "https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf"
    )
    receipt["warehouse_assumptions"] = {
        key: warehouse.get(key)
        for key in ("size", "type", "generation", "max_cluster_count", "auto_suspend")
    }


def diagnostic(output: Path, code_sha: str, supplied_budget: str) -> dict[str, Any]:
    """No second connection, role switch, new object, source acquisition or retry."""
    from lyme_gap_atlas_shared.settings import SnowflakeSettings
    from lyme_gap_atlas_shared.snowflake import connection_parameters
    from snowflake.connector import connect

    receipt: dict[str, Any] = {
        "status": "BLOCKED",
        "statements": 0,
        "warehouse_writes": False,
        "billing": {"actual_billed_usd": None, "state": "NOT_YET_AVAILABLE"},
        "usage_rows": [],
        "usage_state": "NOT_QUERIED",
        "code_sha": code_sha,
    }
    started = time.monotonic()
    connection = None
    bounded = None
    old_handler = None
    alarm_signal = getattr(signal, "SIGALRM", None)
    set_timer = getattr(signal, "setitimer", None)
    real_timer = getattr(signal, "ITIMER_REAL", None)
    previous_retries = os.environ.get("MAX_CON_RETRY_ATTEMPTS")
    connector_logger = logging.getLogger("snowflake.connector")
    previous_log_level = connector_logger.level
    pending_output = output.with_name("pending-" + ARTIFACT_NAME)
    try:
        donor_path = os.environ.get("JANUARY_DONOR_HANDOFF_PATH", "")
        donor_digest = os.environ.get("JANUARY_DONOR_HANDOFF_SHA256", "")
        if not donor_path:
            raise DiagnosticStop("MEMBERSHIP_DONOR_HANDOFF_REQUIRED")
        path = Path(donor_path)
        checkout = Path.cwd().resolve()
        # Keep the lexical boundary under canonical checkout: resolving it could
        # follow a symlink outward and silently redefine the permitted directory.
        allowed = checkout / "docs/contracts/climate/reviewed-donors"
        candidate = path.resolve()
        if (
            path.suffix != ".json"
            or candidate.suffix != ".json"
            or not candidate.is_relative_to(allowed)
        ):
            raise DiagnosticStop("MEMBERSHIP_DONOR_HANDOFF_PATH")
        donor = read_donor_handoff(candidate, donor_digest)
        receipt["reviewed_donor_handoff_sha256"] = donor_digest
        receipt["donor_bundle_sha256"] = donor["bundle_sha256"]
        evidence = budget_evidence(supplied_budget)
        try:
            job_started = int(os.environ["JANUARY_DIAGNOSTIC_JOB_STARTED_UNIX"])
        except (KeyError, ValueError):
            raise DiagnosticStop("EARLY_JOB_CLOCK_REQUIRED") from None
        job_elapsed = time.time() - job_started
        remaining_job = math.floor(MAX_SECONDS - job_elapsed - 60)
        if job_elapsed < 0 or remaining_job < 30:
            raise DiagnosticStop("INSUFFICIENT_JOB_TIME_FOR_RECEIPT")
        runtime_limit = min(budget_runtime(evidence["unit_price_usd"]), remaining_job)
        receipt["job_elapsed_seconds_at_launch"] = round(job_elapsed, 3)
        receipt["cleanup_upload_reserved_seconds"] = 60
        receipt["runtime_limit_seconds"] = runtime_limit
        receipt["price_evidence_sha256"] = hashlib.sha256(supplied_budget.encode()).hexdigest()
        receipt["forecast_basis"] = evidence["basis"]
        receipt["billing"]["actual_billed_unit_price_usd"] = None
        receipt["compute_and_cloud_services_forecast_ceiling_usd"] = (
            (runtime_limit + 15) * 5.75 / 3600 + 1.35 / 30
        ) * evidence["unit_price_usd"]
        receipt["noncompute_reserve_usd"] = 1
        receipt["prior_diagnostic_full_forecast_reserved_usd"] = PRIOR_DIAGNOSTIC_FORECAST_USD
        receipt["producer_forecast_reserved_usd"] = producer_forecast(evidence["unit_price_usd"])
        receipt["approved_total_forecast_usd"] = APPROVED_TOTAL_FORECAST_USD
        receipt["aggregate_forecast_ceiling_usd"] = (
            PRIOR_DIAGNOSTIC_FORECAST_USD
            + receipt["producer_forecast_reserved_usd"]
            + receipt["compute_and_cloud_services_forecast_ceiling_usd"]
            + 1
        )
        if shutil.disk_usage(output.parent).free < 1024**3:
            raise DiagnosticStop("TEMP_DISK_HEADROOM")
        if alarm_signal is None or set_timer is None or real_timer is None:
            raise DiagnosticStop("RUNTIME_ENFORCEMENT_UNAVAILABLE")

        def alarm_handler(_signal: int, _frame: Any) -> None:
            raise DiagnosticStop("RUNTIME_LIMIT")

        old_handler = signal.signal(alarm_signal, alarm_handler)
        set_timer(real_timer, runtime_limit)
        parameters = connection_parameters(SnowflakeSettings())
        parameters.update(
            login_timeout=15,
            network_timeout=15,
            socket_timeout=15,
            backoff_policy=no_retry_backoff,
            session_parameters={
                "QUERY_TAG": "atlas-january-membership-diagnostic",
                "STATEMENT_TIMEOUT_IN_SECONDS": 15,
                "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": 5,
                "ABORT_DETACHED_QUERY": True,
            },
        )
        os.environ["MAX_CON_RETRY_ATTEMPTS"] = "0"
        connector_logger.setLevel(logging.CRITICAL)
        connection = connect(**parameters)
        with connection.cursor() as cursor:
            bounded = BoundedCursor(cursor, started, receipt)
            capability = evidence.get("standard_capability_evidence")
            bounded.execute(
                "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),"
                "CURRENT_WAREHOUSE(),CURRENT_REGION(),CURRENT_ACCOUNT()"
            )
            identity = bounded.fetchone()
            if identity[:4] != (
                "OH_LYME_DEV_PIPELINE_SVC",
                "OH_LYME_DEV_RUNTIME",
                "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
                "OH_LYME_DEV_INGEST_XS_WH",
            ):
                raise DiagnosticStop("IDENTITY_MISMATCH")
            receipt["effective_context"] = list(identity[:5])
            verify_donor_account_binding(donor, identity)
            receipt["donor_account_binding"] = {
                "account_locator_sha256": donor["account_locator_sha256"],
                "region": donor["region"],
            }
            region = identity[4]
            if "region" in evidence and evidence["region"] != region:
                raise DiagnosticStop("PUBLIC_PRICE_REGION_MISMATCH")
            if capability:
                if (
                    len(identity) != 6
                    or not isinstance(identity[5], str)
                    or hashlib.sha256(identity[5].upper().encode()).hexdigest()
                    != capability["account_locator_sha256"]
                    or not str(region).startswith(capability["cloud"] + "_")
                ):
                    raise DiagnosticStop("STANDARD_CAPABILITY_ACCOUNT_MISMATCH")
                receipt["standard_capability_evidence"] = capability
            bounded.execute("SHOW WAREHOUSES LIKE 'OH_LYME_DEV_INGEST_XS_WH'")
            columns = [str(c[0]).lower() for c in cursor.description]
            rows = [dict(zip(columns, row, strict=True)) for row in bounded.fetchall()]
            if len(rows) != 1:
                raise DiagnosticStop("WAREHOUSE_VISIBILITY")
            warehouse = rows[0]
            if warehouse.get("name") != "OH_LYME_DEV_INGEST_XS_WH":
                raise DiagnosticStop("WAREHOUSE_VISIBILITY")
            validate_warehouse_cost(warehouse, evidence, region, receipt)
            receipt["storage_assumptions"] = {
                "incremental_warehouse_bytes": 0,
                "minimum_free_temp_bytes": 1024**3,
                "artifact_max_bytes": MAX_ARTIFACT_BYTES,
                "retention_days": 14,
                "source_downloads": False,
            }
            receipt["status"] = "READING_EXISTING_MEMBERSHIP"
            result = freeze_membership(bounded, pending_output, code_sha, donor)
            if pending_output.stat().st_size > MAX_ARTIFACT_BYTES:
                raise DiagnosticStop("ARTIFACT_SIZE_LIMIT")
            bounded.check()
            os.replace(pending_output, output)
            receipt["membership"] = result
            receipt["status"] = "READ_ONLY_EXPORT_SUCCEEDED"
    except Exception as error:
        receipt["status"] = "BLOCKED"
        receipt.setdefault(
            "failure",
            {
                "stage": bounded.stage if bounded else "PRE_CONNECTION",
                "category": category(error),
                "query_id": failure_query_id(error, bounded.cursor, bounded.prior_query_id)
                if bounded
                else safe_query_id(getattr(error, "sfqid", None)),
            },
        )
    finally:
        # One bounded usage read in the same session. History is not an invoice.
        if (
            connection is not None
            and bounded is not None
            and "warehouse_assumptions" in receipt
            and time.monotonic() - started
            < receipt.get("runtime_limit_seconds", MAX_EXECUTION_SECONDS) - 16
            and receipt["statements"] < MAX_STATEMENTS
        ):
            try:
                with connection.cursor() as usage_cursor:
                    usage = BoundedCursor(usage_cursor, started, receipt)
                    usage.execute(
                        "SELECT QUERY_ID,EXECUTION_STATUS,TOTAL_ELAPSED_TIME,BYTES_SCANNED,"
                        "CREDITS_USED_CLOUD_SERVICES FROM TABLE(INFORMATION_SCHEMA."
                        "QUERY_HISTORY_BY_SESSION(RESULT_LIMIT=>40)) "
                        "WHERE QUERY_TAG='atlas-january-membership-diagnostic' "
                        "ORDER BY START_TIME"
                    )
                    receipt["usage_rows"] = [
                        dict(
                            zip(
                                (
                                    "query_id",
                                    "execution_status",
                                    "elapsed_ms",
                                    "bytes_scanned",
                                    "cloud_services_credits",
                                ),
                                row,
                                strict=True,
                            )
                        )
                        for row in usage.fetchall()
                    ]
                    receipt["usage_state"] = "SESSION_QUERY_HISTORY_NOT_BILLED_CHARGES"
            except Exception:
                receipt["usage_state"] = "UNAVAILABLE_NO_RETRY"
        if connection is not None:
            try:
                connection.close(retry=False)
            except Exception:
                receipt["close_state"] = "UNAVAILABLE"
        if old_handler is not None and set_timer is not None and alarm_signal is not None:
            set_timer(real_timer, 0)
            signal.signal(alarm_signal, old_handler)
        if previous_retries is None:
            os.environ.pop("MAX_CON_RETRY_ATTEMPTS", None)
        else:
            os.environ["MAX_CON_RETRY_ATTEMPTS"] = previous_retries
        connector_logger.setLevel(previous_log_level)
        pending_output.unlink(missing_ok=True)
        receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
        output.with_name(RECEIPT_NAME).write_text(
            json.dumps(receipt, sort_keys=True, default=str), encoding="utf-8"
        )
    # Effective principal and query IDs are retained only in the internal artifact.
    return {
        "status": receipt["status"],
        "statements": receipt["statements"],
        "elapsed_seconds": receipt["elapsed_seconds"],
        "receipt_name": RECEIPT_NAME,
        "receipt_sha256": hashlib.sha256(output.with_name(RECEIPT_NAME).read_bytes()).hexdigest(),
    }
