"""Deterministic intelligence-daily run identifiers including same-day re-runs."""

from __future__ import annotations

from datetime import date
from uuid import NAMESPACE_URL, uuid5

# Attempt 1 plus two same-day re-runs. A fourth claim is refused.
MAX_DAILY_ATTEMPTS = 3
# Same-day attempt ids above the cap, through attempt 31, are refused.
_ATTEMPT_ID_PROBE = 32


def daily_run_namespace(source_id: str, day: date | str) -> str:
    day_text = day.isoformat() if isinstance(day, date) else day
    return f"atlas:intelligence:daily:{source_id}:{day_text}"


def _daily_run_id(source_id: str, day: date | str, reopen_attempt: int) -> str:
    namespace = daily_run_namespace(source_id, day)
    if reopen_attempt == 1:
        return str(uuid5(NAMESPACE_URL, namespace))
    return str(uuid5(NAMESPACE_URL, f"{namespace}:attempt-{reopen_attempt}"))


def daily_run_id(source_id: str, day: date | str, *, reopen_attempt: int = 1) -> str:
    if reopen_attempt < 1:
        raise ValueError("reopen_attempt must be at least 1")
    if reopen_attempt > MAX_DAILY_ATTEMPTS:
        raise PermissionError("INTELLIGENCE_DAILY_ATTEMPT_CAP")
    return _daily_run_id(source_id, day, reopen_attempt)


def prior_daily_run_id(source_id: str, day: date | str, reopen_attempt: int) -> str:
    if reopen_attempt <= 2:
        return daily_run_id(source_id, day, reopen_attempt=1)
    return daily_run_id(source_id, day, reopen_attempt=reopen_attempt - 1)


def reopen_attempt_for_run_id(source_id: str, day: date | str, run_id: str) -> int | None:
    for attempt in range(1, MAX_DAILY_ATTEMPTS + 1):
        if _daily_run_id(source_id, day, attempt) == run_id:
            return attempt
    return None


def daily_attempt_over_cap(source_id: str, day: date | str, run_id: str) -> bool:
    """True when ``run_id`` is a same-day attempt above the cap."""
    return any(
        _daily_run_id(source_id, day, attempt) == run_id
        for attempt in range(MAX_DAILY_ATTEMPTS + 1, _ATTEMPT_ID_PROBE)
    )
