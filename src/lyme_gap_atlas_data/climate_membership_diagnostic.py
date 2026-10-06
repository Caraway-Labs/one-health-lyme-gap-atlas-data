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

from .climate_membership import ARTIFACT_NAME, MembershipBlocked, freeze_membership

RECEIPT_NAME = "january-membership-diagnostic-receipt.json"
MAX_STATEMENTS = 40
MAX_SECONDS = 300
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
    if not isinstance(value, dict) or set(value) != {
        "unit_price_usd",
        "evidence_reference",
        "verified_by",
        "verified_at",
    }:
        raise DiagnosticStop("BILLING_PRICE_RECEIPT_REQUIRED")
    price = value["unit_price_usd"]
    if type(price) not in (int, float) or not math.isfinite(price) or not 0 < price <= 20:
        raise DiagnosticStop("BILLING_PRICE_OUTSIDE_APPROVED_CEILING")
    for key in ("evidence_reference", "verified_by"):
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
    return value


def stage_for(sql: str) -> str:
    if "CURRENT_USER" in sql:
        return "IDENTITY"
    if "r.source_manifest" in sql:
        return "ANNUAL_DONOR"
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

    def check(self) -> float:
        remaining = MAX_SECONDS - (time.monotonic() - self.started)
        if remaining <= 1:
            raise DiagnosticStop("RUNTIME_LIMIT")
        return remaining

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        remaining = self.check()
        if self.receipt["statements"] >= MAX_STATEMENTS:
            raise DiagnosticStop("STATEMENT_LIMIT")
        if not sql.startswith(("SELECT ", "SHOW ")):
            raise DiagnosticStop("READ_ONLY_REQUIRED")
        self.stage = stage_for(sql)
        self.receipt["statements"] += 1
        try:
            self.cursor.execute(sql, params, timeout=min(15, int(remaining)))
        except Exception as error:
            self.receipt.setdefault(
                "failure",
                {
                    "stage": self.stage,
                    "category": category(error),
                    "query_id": safe_query_id(getattr(error, "sfqid", None))
                    or safe_query_id(getattr(self.cursor, "sfqid", None)),
                },
            )
            raise DiagnosticStop("READ_FAILED") from None
        self.receipt.setdefault("query_ids", []).append(
            safe_query_id(getattr(self.cursor, "sfqid", None))
        )

    def fetchone(self) -> Any:
        self.check()
        return self.cursor.fetchone()

    def fetchall(self) -> Any:
        self.check()
        return self.cursor.fetchall()

    def fetchmany(self, size: int) -> Any:
        self.check()
        return self.cursor.fetchmany(size)


def safe_query_id(value: Any) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f-]{36}", value) else None


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
        evidence = budget_evidence(supplied_budget)
        receipt["price_evidence_sha256"] = hashlib.sha256(supplied_budget.encode()).hexdigest()
        receipt["compute_estimate_ceiling_usd"] = 0.20 * evidence["unit_price_usd"]
        receipt["noncompute_reserve_usd"] = 1
        if shutil.disk_usage(output.parent).free < 1024**3:
            raise DiagnosticStop("TEMP_DISK_HEADROOM")
        if alarm_signal is None or set_timer is None or real_timer is None:
            raise DiagnosticStop("RUNTIME_ENFORCEMENT_UNAVAILABLE")

        def alarm_handler(_signal: int, _frame: Any) -> None:
            raise DiagnosticStop("RUNTIME_LIMIT")

        old_handler = signal.signal(alarm_signal, alarm_handler)
        set_timer(real_timer, MAX_SECONDS)
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
            bounded.execute(
                "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE()"
            )
            identity = bounded.fetchone()
            if identity != (
                "OH_LYME_DEV_PIPELINE_SVC",
                "OH_LYME_DEV_RUNTIME",
                "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
                "OH_LYME_DEV_INGEST_XS_WH",
            ):
                raise DiagnosticStop("IDENTITY_MISMATCH")
            receipt["effective_context"] = list(identity)
            bounded.execute("SHOW WAREHOUSES LIKE 'OH_LYME_DEV_INGEST_XS_WH'")
            columns = [str(c[0]).lower() for c in cursor.description]
            rows = [dict(zip(columns, row, strict=True)) for row in bounded.fetchall()]
            if len(rows) != 1:
                raise DiagnosticStop("WAREHOUSE_VISIBILITY")
            warehouse = rows[0]
            # Gen2/rate cannot be guessed from X-Small; require explicit Gen1 evidence.
            if (
                warehouse.get("size") != "X-Small"
                or warehouse.get("type") != "STANDARD"
                or str(warehouse.get("generation")).upper() not in ("1", "GEN_1", "GEN1")
                or warehouse.get("max_cluster_count") != 1
                or warehouse.get("enable_query_acceleration") is not False
                or not 0 < int(warehouse.get("auto_suspend", 0)) <= 60
            ):
                raise DiagnosticStop("WAREHOUSE_COST_ASSUMPTIONS_UNVERIFIED")
            receipt["warehouse_assumptions"] = {
                key: warehouse[key]
                for key in ("size", "type", "generation", "max_cluster_count", "auto_suspend")
            }
            receipt["storage_assumptions"] = {
                "incremental_warehouse_bytes": 0,
                "minimum_free_temp_bytes": 1024**3,
                "artifact_max_bytes": MAX_ARTIFACT_BYTES,
                "retention_days": 14,
                "source_downloads": False,
            }
            receipt["status"] = "READING_EXISTING_MEMBERSHIP"
            result = freeze_membership(bounded, pending_output, code_sha)
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
                "query_id": safe_query_id(getattr(error, "sfqid", None))
                or safe_query_id(getattr(bounded.cursor, "sfqid", None) if bounded else None),
            },
        )
    finally:
        # One bounded usage read in the same session. History is not an invoice.
        if (
            connection is not None
            and bounded is not None
            and "warehouse_assumptions" in receipt
            and time.monotonic() - started < MAX_SECONDS - 16
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
