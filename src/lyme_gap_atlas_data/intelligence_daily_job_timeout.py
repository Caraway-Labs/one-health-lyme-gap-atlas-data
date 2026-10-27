"""Platform timeout for the standing intelligence-feed-daily job.

``jobs[].timeout`` is a DigitalOcean duration string. An unset timeout
defaults to 30 minutes. ``1h30m`` is 5400 seconds. The scheduled-retry
deadline uses this same duration so the two cannot drift apart.
"""

from __future__ import annotations

import re
from typing import Any

# DigitalOcean's AppJobSpec documents ``1h30m``. A normal daily pass is about
# 40 minutes; a first pass where every source hits its watchdog is about 89
# minutes. A stuck run can hold its claim until this deadline.
DAILY_JOB_TIMEOUT = "1h30m"
_DURATION_PART = re.compile(r"(\d+)([hms])")
_DURATION_SECONDS = {"h": 3600, "m": 60, "s": 1}


def duration_seconds(value: Any) -> int | None:
    """Parse a DigitalOcean duration such as 1h30m or 5400s into seconds.

    DigitalOcean stores the submitted 1h30m as 5400s, so equal durations must
    compare equal. Returns None for anything that is not a plain h/m/s duration.
    """
    if not isinstance(value, str) or not value:
        return None
    parts = _DURATION_PART.findall(value)
    if not parts or "".join(f"{n}{u}" for n, u in parts) != value:
        return None
    return sum(int(n) * _DURATION_SECONDS[u] for n, u in parts)


def _deadline_seconds() -> int:
    parsed = duration_seconds(DAILY_JOB_TIMEOUT)
    if parsed is None:
        raise RuntimeError("INTELLIGENCE_DAILY_JOB_TIMEOUT_INVALID")
    return parsed


DAILY_JOB_DEADLINE_SECONDS = _deadline_seconds()
