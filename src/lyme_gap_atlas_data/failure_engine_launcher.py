"""Fixed opt-in child supervision; the plan CLI never calls this module."""

from __future__ import annotations

import logging
import multiprocessing
import os
import time
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

from .failure_engine_proof import CONNECTION, make_plan, plan_hash, run_proof


def _child(channel: Any, cancel: Any, plan: dict[str, Any], approved: str, user: str) -> None:
    # No private driver diagnostics reach the parent's stdout/stderr or receipt.
    with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
        logging.disable(logging.CRITICAL)
        try:
            import snowflake.connector

            connection = snowflake.connector.connect(
                connection_name=CONNECTION,
                authenticator="PROGRAMMATIC_ACCESS_TOKEN",
                paramstyle="pyformat",
                login_timeout=15,
                network_timeout=30,
                socket_timeout=30,
            )
            receipt = run_proof(
                connection,
                plan,
                approved_plan_sha256=approved,
                expected_user=user,
                cancelled=cancel.is_set,
            )
        except BaseException:
            receipt = {"state": "CHILD_FAILURE", "cleanup": "UNKNOWN"}
        try:
            channel.send(receipt)
        finally:
            channel.close()


def _supervise(target: Any, args: tuple[Any, ...], *, seconds: float = 600) -> dict[str, Any]:
    """Only the Process instance created here may be terminated; no PID discovery."""
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    cancel = context.Event()
    process = context.Process(target=target, args=(send, cancel, *args), daemon=True)
    deadline = time.monotonic() + seconds
    result: dict[str, Any] = {"state": "CHILD_FAILURE", "cleanup": "UNKNOWN"}
    try:
        process.start()
        send.close()
        while process.is_alive():
            remaining = deadline - time.monotonic()
            # Stop normal operations after half the envelope; reserve cleanup.
            if remaining <= seconds / 2:
                cancel.set()
            if remaining <= min(10, seconds / 10):
                result = {"state": "OUTER_TIMEOUT", "cleanup": "UNKNOWN"}
                break
            if receive.poll(min(0.05, remaining)):
                result = receive.recv()
                break
        if result["state"] == "CHILD_FAILURE" and receive.poll():
            result = receive.recv()
    except (EOFError, OSError):
        result = {"state": "CHILD_FAILURE", "cleanup": "UNKNOWN"}
    finally:
        cancel.set()
        if process.pid is not None:
            allowance = seconds / 100 if result.get("state") == "OUTER_TIMEOUT" else 5
            process.join(max(0, min(allowance, (deadline - time.monotonic()) / 2)))
            if process.is_alive():
                process.terminate()
                process.join(max(0, min(1, deadline - time.monotonic())))
            if process.is_alive():
                process.kill()
                process.join(max(0, deadline - time.monotonic()))
            if process.is_alive():
                result = {"state": "TERMINATION_UNKNOWN", "cleanup": "UNKNOWN"}
            elif process.exitcode != 0 and result.get("state") == "PASS":
                result = {"state": "CHILD_FAILURE", "cleanup": "UNKNOWN"}
        receive.close()
        send.close()
    return {
        "receipt": result,
        "server_query_cancellation": "UNKNOWN",
        "independent_execution_verification": "UNKNOWN",
    }


def launch_proof(
    plan: dict[str, Any],
    *,
    approved_plan_sha256: str | None = None,
    expected_user: str | None = None,
) -> dict[str, Any]:
    """Explicit future owner-authorized invocation only; never used by default CLI."""
    if not approved_plan_sha256 or not expected_user:
        return {"state": "NOT_AUTHORIZED"}
    try:
        if plan != make_plan(plan["code_commit"]) or plan_hash(plan) != approved_plan_sha256:
            return {"state": "PLAN_REJECTED"}
    except Exception:
        return {"state": "PLAN_REJECTED"}
    return _supervise(_child, (plan, approved_plan_sha256, expected_user))
