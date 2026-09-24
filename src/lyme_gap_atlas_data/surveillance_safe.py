"""Value-level checks for safe surveillance result projections."""

from __future__ import annotations

import re

_SENSITIVE_FILE = re.compile(
    r"(?:^|[/\\])[^/\\]*(?:private[-_]?key|credential|secret|token)"
    r"[^/\\]*\.(?:p8|pem|key|p12|pfx|json|txt|env)$",
    re.IGNORECASE,
)
_SENSITIVE_EXTENSION = re.compile(r"\.(?:p8|pem|key|p12|pfx)$", re.IGNORECASE)
_PATH_START = re.compile(r"^(?:[A-Za-z]:[/\\]|[/\\]{2}|/|\.\.?[/\\]|~[/\\])")


def has_sensitive_path(value: str) -> bool:
    """Reject credential-like paths while permitting ordinary opaque IDs."""
    if "/" not in value and "\\" not in value:
        return False
    if _SENSITIVE_FILE.search(value):
        return True
    if _PATH_START.search(value) and _SENSITIVE_EXTENSION.search(value):
        return True
    return bool(
        _PATH_START.search(value)
        and re.search(
            r"(?:^|[/\\])(?:secrets?|credentials?|tokens?)(?:[/\\]|$)",
            value,
            re.IGNORECASE,
        )
    )
