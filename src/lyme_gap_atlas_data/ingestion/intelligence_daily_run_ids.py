"""Deterministic intelligence-daily run identifiers including governed reopen attempts."""

from __future__ import annotations

from datetime import date
from uuid import NAMESPACE_URL, uuid5


def daily_run_namespace(source_id: str, day: date | str) -> str:
    day_text = day.isoformat() if isinstance(day, date) else day
    return f"atlas:intelligence:daily:{source_id}:{day_text}"


def daily_run_id(source_id: str, day: date | str, *, reopen_attempt: int = 1) -> str:
    if reopen_attempt < 1:
        raise ValueError("reopen_attempt must be at least 1")
    namespace = daily_run_namespace(source_id, day)
    if reopen_attempt == 1:
        return str(uuid5(NAMESPACE_URL, namespace))
    return str(uuid5(NAMESPACE_URL, f"{namespace}:attempt-{reopen_attempt}"))


def prior_daily_run_id(source_id: str, day: date | str, reopen_attempt: int) -> str:
    if reopen_attempt <= 2:
        return daily_run_id(source_id, day, reopen_attempt=1)
    return daily_run_id(source_id, day, reopen_attempt=reopen_attempt - 1)


def reopen_attempt_for_run_id(source_id: str, day: date | str, run_id: str) -> int | None:
    for attempt in range(1, 32):
        if daily_run_id(source_id, day, reopen_attempt=attempt) == run_id:
            return attempt
    return None
