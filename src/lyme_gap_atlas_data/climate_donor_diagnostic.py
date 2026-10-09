"""Proposed bounded donor callable; no authenticated workflow route is enabled."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import signal
import time
from pathlib import Path
from typing import Any

from . import climate_membership_diagnostic as bounds
from .climate_membership import DONOR_WAREHOUSE, export_donor_handoff

ARTIFACT_NAME = "january-reviewed-donor.json"
RECEIPT_NAME = "january-donor-diagnostic-receipt.json"
MAX_EXECUTION_SECONDS = 15
MAX_CLEANUP_SECONDS = 15
MAX_STATEMENTS = 6
EXPECTED_CONTEXT = (
    "OH_LYME_DEV_MIGRATION_DEPLOY_SVC",
    "OH_LYME_DEV_MIGRATION_DEPLOYER",
    "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
    DONOR_WAREHOUSE,
)


def pair_forecast(price: float) -> float:
    """Both bounded reads, minimum/resume bounds, two idle tails each, reserve."""
    producer = bounds.producer_forecast(price)
    consumer = (65 * 5.75 / 3600 + 1.35 / 30) * price
    return producer + consumer + 1


def producer(output: Path, code_sha: str, supplied_budget: str) -> dict[str, Any]:
    """One connection; no grant, mutation, role switch, fallback or paid retry."""
    from lyme_gap_atlas_shared.settings import SnowflakeSettings
    from lyme_gap_atlas_shared.snowflake import connection_parameters
    from snowflake.connector import connect

    started = time.monotonic()
    receipt: dict[str, Any] = {
        "status": "BLOCKED",
        "statements": 0,
        "statement_limit": MAX_STATEMENTS,
        "statement_timeout_seconds": 5,
        "runtime_limit_seconds": MAX_EXECUTION_SECONDS,
        "cleanup_limit_seconds": MAX_CLEANUP_SECONDS,
        "code_sha": code_sha,
        "warehouse_writes": False,
        "publication": False,
        "billing": {"actual_billed_usd": None, "state": "NOT_YET_AVAILABLE"},
        "cancellation_state": "NO_ACTIVE_STATEMENT",
    }
    connection = bounded = None
    old_handler = None
    alarm_signal: Any = getattr(signal, "SIGALRM", None)
    timer: Any = getattr(signal, "setitimer", None)
    real_timer = getattr(signal, "ITIMER_REAL", None)
    previous_retries = os.environ.get("MAX_CON_RETRY_ATTEMPTS")
    logger = logging.getLogger("snowflake.connector")
    previous_level = logger.level
    pending = output.with_name("pending-" + ARTIFACT_NAME)

    def cleanup_expired(_signal: int, _frame: Any) -> None:
        raise bounds.DiagnosticStop("DONOR_CLEANUP_LIMIT")

    def execution_expired(_signal: int, _frame: Any) -> None:
        # The pinned SDK installs SIGINT cancellation around execute(), tied to
        # its active request ID. No new connection or cancellation SQL is used.
        signal.signal(alarm_signal, cleanup_expired)
        timer(real_timer, max(0.001, started + 30 - time.monotonic()))
        if bounded is not None and bounded.active_statement:
            receipt["cancellation_state"] = "SDK_INTERRUPT_REQUESTED_NOT_CONFIRMED"
            signal.raise_signal(signal.SIGINT)
        raise bounds.DiagnosticStop("DONOR_RUNTIME_LIMIT")

    try:
        if re.fullmatch(r"[0-9a-f]{40}", code_sha) is None:
            raise bounds.DiagnosticStop("MEMBERSHIP_CODE_SHA")
        evidence = bounds.budget_evidence(supplied_budget)
        capability = evidence.get("standard_capability_evidence")
        if capability is None or not str(evidence.get("region", "")).startswith("AWS_"):
            raise bounds.DiagnosticStop("STANDARD_CAPABILITY_EVIDENCE_REQUIRED")
        receipt["price_evidence_sha256"] = hashlib.sha256(supplied_budget.encode()).hexdigest()
        receipt["prior_diagnostic_full_forecast_reserved_usd"] = (
            bounds.PRIOR_DIAGNOSTIC_FORECAST_USD
        )
        receipt["approved_total_forecast_usd"] = bounds.APPROVED_TOTAL_FORECAST_USD
        receipt["pair_forecast_reserved_usd"] = pair_forecast(evidence["unit_price_usd"])
        receipt["aggregate_forecast_ceiling_usd"] = (
            bounds.PRIOR_DIAGNOSTIC_FORECAST_USD + receipt["pair_forecast_reserved_usd"]
        )
        if receipt["aggregate_forecast_ceiling_usd"] > bounds.APPROVED_TOTAL_FORECAST_USD:
            raise bounds.DiagnosticStop("FORECAST_EXCEEDS_APPROVED_TOTAL_CAP")
        if alarm_signal is None or timer is None or real_timer is None:
            raise bounds.DiagnosticStop("RUNTIME_ENFORCEMENT_UNAVAILABLE")
        try:
            job_elapsed = time.time() - int(os.environ["JANUARY_DIAGNOSTIC_JOB_STARTED_UNIX"])
        except (KeyError, ValueError):
            raise bounds.DiagnosticStop("EARLY_JOB_CLOCK_REQUIRED") from None
        if not 0 <= job_elapsed <= bounds.MAX_SECONDS - 60 - 30:
            raise bounds.DiagnosticStop("INSUFFICIENT_JOB_TIME_FOR_RECEIPT")
        parameters = connection_parameters(SnowflakeSettings())
        if (
            tuple(parameters.get(key) for key in ("user", "role", "database"))
            != EXPECTED_CONTEXT[:3]
        ):
            raise bounds.DiagnosticStop("DONOR_CONFIGURED_IDENTITY_MISMATCH")
        parameters.update(
            warehouse=DONOR_WAREHOUSE,
            login_timeout=5,
            network_timeout=5,
            socket_timeout=5,
            backoff_policy=bounds.no_retry_backoff,
            session_parameters={
                "QUERY_TAG": "atlas-january-donor-diagnostic",
                "STATEMENT_TIMEOUT_IN_SECONDS": 5,
                "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS": 2,
                "ABORT_DETACHED_QUERY": True,
            },
        )
        remaining = MAX_EXECUTION_SECONDS - (time.monotonic() - started)
        if remaining <= 1:
            raise bounds.DiagnosticStop("DONOR_RUNTIME_LIMIT")
        old_handler = signal.signal(alarm_signal, execution_expired)
        timer(real_timer, remaining)
        os.environ["MAX_CON_RETRY_ATTEMPTS"] = "0"
        logger.setLevel(logging.CRITICAL)
        connection = connect(**parameters)
        with connection.cursor() as cursor:
            bounded = bounds.BoundedCursor(cursor, started, receipt)
            bounded.execute(
                "SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE(),"
                "CURRENT_REGION(),CURRENT_ACCOUNT()"
            )
            identity = bounded.fetchone()
            binding = {
                "account_locator_sha256": capability["account_locator_sha256"],
                "region": evidence["region"],
            }
            bounds.verify_donor_account_binding(binding, identity)
            if identity[:4] != EXPECTED_CONTEXT:
                raise bounds.DiagnosticStop("DONOR_EFFECTIVE_IDENTITY_MISMATCH")
            receipt["operator_identity_checks"] = "PASS"
            receipt["account_binding"] = binding
            bounded.execute("SHOW WAREHOUSES LIKE 'OH_LYME_DEV_INGEST_XS_WH'")
            columns = [str(c[0]).lower() for c in cursor.description]
            rows = [dict(zip(columns, row, strict=True)) for row in bounded.fetchall()]
            if len(rows) != 1 or rows[0].get("name") != DONOR_WAREHOUSE:
                raise bounds.DiagnosticStop("WAREHOUSE_VISIBILITY")
            bounds.validate_warehouse_cost(rows[0], evidence, identity[4], receipt)
            result = export_donor_handoff(
                bounded, pending, code_sha, binding["account_locator_sha256"], binding["region"]
            )
            bounded.check()
            receipt["donor"] = result
            receipt["status"] = "DONOR_EXPORT_PENDING_CLEANUP"
    except (Exception, KeyboardInterrupt) as error:
        receipt["status"] = "BLOCKED"
        receipt["failure"] = {
            "stage": bounded.stage if bounded is not None else "PRE_CONNECTION",
            "category": "DONOR_RUNTIME_LIMIT"
            if isinstance(error, KeyboardInterrupt)
            else bounds.category(error),
        }
    finally:
        if old_handler is not None:
            signal.signal(alarm_signal, cleanup_expired)
            timer(
                real_timer,
                max(
                    0.001,
                    min(started + 30, time.monotonic() + MAX_CLEANUP_SECONDS) - time.monotonic(),
                ),
            )
        if connection is not None:
            try:
                connection.close(retry=False)
                receipt["close_state"] = "CLOSED_NO_RETRY"
            except Exception:
                receipt["close_state"] = "UNAVAILABLE_OR_CLEANUP_LIMIT"
                receipt["status"] = "BLOCKED"
                receipt.setdefault(
                    "failure", {"stage": "CLEANUP", "category": "DONOR_CLEANUP_UNVERIFIED"}
                )
        if old_handler is not None:
            timer(real_timer, 0)
            signal.signal(alarm_signal, old_handler)
        if previous_retries is None:
            os.environ.pop("MAX_CON_RETRY_ATTEMPTS", None)
        else:
            os.environ["MAX_CON_RETRY_ATTEMPTS"] = previous_retries
        logger.setLevel(previous_level)
        if receipt["status"] == "DONOR_EXPORT_PENDING_CLEANUP":
            if receipt.get("close_state") == "CLOSED_NO_RETRY" and time.monotonic() - started < 30:
                try:
                    os.replace(pending, output)
                    receipt["status"] = "READ_ONLY_DONOR_EXPORT_SUCCEEDED"
                except OSError:
                    receipt["status"] = "BLOCKED"
                    receipt["failure"] = {
                        "stage": "LOCAL_OUTPUT",
                        "category": "DONOR_OUTPUT_UNAVAILABLE",
                    }
            else:
                receipt["status"] = "BLOCKED"
                receipt["failure"] = {"stage": "CLEANUP", "category": "DONOR_CLEANUP_UNVERIFIED"}
        pending.unlink(missing_ok=True)
        receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
        output.with_name(RECEIPT_NAME).write_text(
            json.dumps(receipt, sort_keys=True), encoding="utf-8"
        )
    return {
        "status": receipt["status"],
        "statements": receipt["statements"],
        "receipt_name": RECEIPT_NAME,
        "receipt_sha256": hashlib.sha256(output.with_name(RECEIPT_NAME).read_bytes()).hexdigest(),
    }
