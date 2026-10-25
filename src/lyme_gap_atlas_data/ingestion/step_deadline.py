"""Wall-clock checkpoint shared by a PubMed walk's Snowflake and HTTP steps.

This module stays free of the ingestion runtime so the Entrez adapter can note
the deadline without an import cycle through storage.
"""

from __future__ import annotations

import contextvars
from typing import Any

# Set only while a PubMed walk is inside its wall-clock deadline. RSS runs leave it unset.
_STEP_DEADLINE: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "intelligence_step_deadline", default=None
)


def active_step_deadline() -> Any:
    """Deadline for the current PubMed walk, or None outside that walk."""
    return _STEP_DEADLINE.get()


def bind_step_deadline(deadline: Any) -> contextvars.Token[Any]:
    return _STEP_DEADLINE.set(deadline)


def reset_step_deadline(token: contextvars.Token[Any]) -> None:
    _STEP_DEADLINE.reset(token)


def note_step_deadline() -> None:
    """Re-arm and refuse when a PubMed step is already past its deadline.

    Snowflake's connector replaces the one-shot alarm for the duration of a
    query and clears it afterward. The next Snowflake or HTTP step calls this
    so the walk cannot continue on the daily budget after that alarm is gone.
    """
    deadline = active_step_deadline()
    if deadline is not None:
        deadline.checkpoint()
