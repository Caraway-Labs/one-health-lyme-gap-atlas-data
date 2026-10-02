"""Bounded, explicitly opted-in local failure collection; no exception inspection."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from .failure_evidence import collect_failure, validate_packet

MAX_PACKET_BYTES = 32_768


def write_packet(path: Path, packet: dict[str, Any]) -> None:
    """Create one packet exclusively in an existing operator-controlled directory.

    The caller owns directory ACLs/retention. Never create directories, overwrite
    earlier attempts, follow an existing output link, or persist rejected content.
    """
    validate_packet(packet)
    payload = (json.dumps(packet, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(payload) > MAX_PACKET_BYTES:
        raise ValueError("failure collection unavailable")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def collect_runtime_failure(context_path: Path | None, output_path: Path | None) -> str:
    """Read reviewed metadata only after failure. Return constant outcome codes.

    No paths, exception objects, manifest, SQL, environment or credentials enter
    the packet. A configured invocation gets at most one read and one write.
    """
    if context_path is None and output_path is None:
        return "DISABLED"
    if context_path is None or output_path is None:
        return "COLLECTION_UNAVAILABLE"
    try:
        if not stat.S_ISREG(context_path.lstat().st_mode):
            return "COLLECTION_UNAVAILABLE"
        descriptor = os.open(context_path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return "COLLECTION_UNAVAILABLE"
            payload = stream.read(MAX_PACKET_BYTES + 1)
        if len(payload) > MAX_PACKET_BYTES:
            return "REDACTION_REJECTED"
        try:
            context = json.loads(payload)
        except (ValueError, UnicodeError):
            return "REDACTION_REJECTED"
        if not isinstance(context, dict):
            return "REDACTION_REJECTED"
        if context.get("operation") != "SEMANTIC_RELEASE":
            return "REDACTION_REJECTED"
        return collect_failure(context, lambda packet: write_packet(output_path, packet))
    except Exception:
        return "COLLECTION_UNAVAILABLE"
