"""Private file handoff: AWS credentials stay on capture host, Spaces on upload host."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, BinaryIO, cast

from .nlcd_storage_staging import MANIFEST_SHA256, SOURCE_BYTES, Limits, _stream_hash


def _validate_members(members: Sequence[Mapping[str, Any]]) -> None:
    canonical = json.dumps(list(members), sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(canonical).hexdigest() != MANIFEST_SHA256:
        raise ValueError("Unreviewed capture manifest")


def _path(directory: Path, member: Mapping[str, Any]) -> Path:
    path = directory / Path(str(member["key"])).name
    if path.is_symlink() or path.resolve().parent != directory.resolve():
        raise ValueError("Unsafe relay member path")
    return path


def capture_members(
    members: Sequence[Mapping[str, Any]],
    *,
    source: Any,
    directory: Path,
    limits: Limits | None = None,
) -> dict[str, Any]:
    """Capture only fixed source assets; never needs Spaces/Snowflake identity."""
    _validate_members(members)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Private existing capture directory required")
    budget = limits or Limits()
    receipt_path = directory / "capture-receipt.json"
    if receipt_path.is_symlink():
        raise ValueError("Unsafe receipt path")
    previous = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    if previous and previous.get("manifest_sha256") != MANIFEST_SHA256:
        raise ValueError("Existing capture manifest mismatch")
    receipts = dict(previous.get("members", {}))
    for member in members:
        path = _path(directory, member)
        budget.request()
        head = source.head_object(
            Bucket=member["bucket"],
            Key=member["key"],
            VersionId=member["version_id"],
            RequestPayer="requester",
        )
        if (head.get("ContentLength"), head.get("VersionId"), head.get("ETag")) != (
            member["bytes"],
            member["version_id"],
            member["etag"],
        ):
            raise ValueError("Capture source identity drift")
        if path.exists():
            existing = receipts.get(member["key"])
            if not existing or existing.get("source") != dict(member):
                raise ValueError("Unreceipted existing capture; never overwrite")
            with path.open("rb") as body:
                digest = _stream_hash(body, int(member["bytes"]), budget, source=False)
            if digest != existing.get("sha256"):
                raise ValueError("Existing capture digest mismatch")
            continue
        if shutil.disk_usage(directory).free < int(member["bytes"]) + 256_000_000:
            raise ValueError("Capture disk reserve insufficient")
        partial = path.with_suffix(path.suffix + ".part")
        if partial.is_symlink():
            raise ValueError("Unsafe partial capture")
        budget.request()
        response = source.get_object(
            Bucket=member["bucket"],
            Key=member["key"],
            VersionId=member["version_id"],
            RequestPayer="requester",
        )
        if (response.get("ContentLength"), response.get("VersionId"), response.get("ETag")) != (
            member["bytes"],
            member["version_id"],
            member["etag"],
        ):
            response["Body"].close()
            raise ValueError("Capture GET identity drift")
        with partial.open("wb") as output:
            digest = _stream_hash(
                response["Body"],
                int(member["bytes"]),
                budget,
                source=True,
                output=cast(BinaryIO, output),
            )
        partial.replace(path)
        receipts[member["key"]] = {"source": dict(member), "sha256": digest}
        receipt = {
            "manifest_sha256": MANIFEST_SHA256,
            "members": receipts,
            "requests_this_attempt": budget.requests,
            "source_download_bytes_this_attempt": budget.source_bytes,
        }
        temporary_receipt = directory / "capture-receipt.json.part"
        if temporary_receipt.is_symlink():
            raise ValueError("Unsafe partial receipt")
        temporary_receipt.write_text(json.dumps(receipt, sort_keys=True))
        temporary_receipt.replace(receipt_path)
    return {
        "status": "CAPTURE_COMPLETE",
        "manifest_sha256": MANIFEST_SHA256,
        "members": receipts,
        "source_bytes": SOURCE_BYTES,
        "requests_this_attempt": budget.requests,
        "source_download_bytes_this_attempt": budget.source_bytes,
    }


class VerifiedDirectorySource:
    """AWS-shaped reader of captured files; no AWS client/credentials on relay host."""

    is_private_relay = True

    def __init__(self, members: Sequence[Mapping[str, Any]], directory: Path) -> None:
        _validate_members(members)
        if directory.is_symlink():
            raise ValueError("Unsafe relay directory")
        receipt_path = directory / "capture-receipt.json"
        if receipt_path.is_symlink():
            raise ValueError("Unsafe relay receipt")
        receipt = json.loads(receipt_path.read_text())
        expected = {str(member["key"]): dict(member) for member in members}
        if receipt.get("manifest_sha256") != MANIFEST_SHA256 or set(
            receipt.get("members", {})
        ) != set(expected):
            raise ValueError("Incomplete relay capture")
        self.directory = directory
        self.receipts = receipt["members"]
        for key, member in expected.items():
            item = self.receipts[key]
            if item.get("source") != member or len(item.get("sha256", "")) != 64:
                raise ValueError("Relay source identity mismatch")

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        item = self.receipts[kwargs["Key"]]
        member = item["source"]
        if kwargs["Bucket"] != member["bucket"] or kwargs["VersionId"] != member["version_id"]:
            raise ValueError("Wrong relay source version")
        path = _path(self.directory, member)
        if path.stat().st_size != member["bytes"]:
            raise ValueError("Incomplete relay file")
        with path.open("rb") as body:
            actual = _stream_hash(body, member["bytes"], Limits(), source=False)
        if actual != item["sha256"]:
            raise ValueError("Relay SHA-256 mismatch")
        return {
            "ContentLength": member["bytes"],
            "VersionId": member["version_id"],
            "ETag": member["etag"],
            "CaptureSHA256": item["sha256"],
        }

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        info = self.head_object(**kwargs)
        member = self.receipts[kwargs["Key"]]["source"]
        return {**info, "Body": _path(self.directory, member).open("rb")}
