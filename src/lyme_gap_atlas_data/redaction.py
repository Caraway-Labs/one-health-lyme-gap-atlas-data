"""Redact request evidence before it can enter a log or governance ledger."""

from collections.abc import Mapping
from typing import Any

SENSITIVE_NAMES = {"authorization", "x-api-key", "x-app-token", "password", "token", "secret"}


def redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: "[REDACTED]" if key.lower() in SENSITIVE_NAMES else item for key, item in value.items()
    }
