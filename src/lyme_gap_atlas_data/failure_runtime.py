"""Bounded, explicitly opted-in local failure collection; no exception inspection."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from .failure_evidence import collect_failure, validate_packet

MAX_PACKET_BYTES = 32_768


def _open_no_follow(path: Path) -> int:
    """Open the final path component without following links on Windows/POSIX."""
    if os.name != "nt":
        if not hasattr(os, "O_NOFOLLOW"):
            raise ValueError("failure collection unavailable")
        return os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))

    import ctypes
    import msvcrt
    from ctypes import wintypes

    class AttributeTag(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # GENERIC_READ, FILE_SHARE_READ (deny rename/write while open),
    # OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT. No privileges are adjusted.
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value or handle is None:
        raise ValueError("failure collection unavailable")
    try:
        info = AttributeTag()
        # FileAttributeTagInfo = 9; reject every reparse point before reading.
        if not kernel.GetFileInformationByHandleEx(
            handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            raise ValueError("failure collection unavailable")
        if info.attributes & 0x00000400:
            raise ValueError("failure collection unavailable")
        return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise


def _regular_with_identity(info: os.stat_result) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_ino != 0
        and not getattr(info, "st_file_attributes", 0) & 0x00000400
    )


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
    # Never unlink by pathname on failure: it may now name another writer's
    # replacement. An uncertain partial file is retained, never a collected receipt.
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)


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
        reviewed = context_path.lstat()
        if not _regular_with_identity(reviewed):
            return "COLLECTION_UNAVAILABLE"
        descriptor = _open_no_follow(context_path)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            current = context_path.lstat()
            if (
                not _regular_with_identity(opened)
                or not _regular_with_identity(current)
                or not os.path.samestat(reviewed, opened)
                or not os.path.samestat(current, opened)
            ):
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
