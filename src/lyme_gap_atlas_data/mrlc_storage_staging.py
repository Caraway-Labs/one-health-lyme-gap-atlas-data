"""Reviewed public MRLC package capture/relay; no S3 source or Snowflake calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import threading
import uuid
import zipfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

import boto3  # type: ignore[import-untyped]
import requests
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from .nlcd_storage_staging import CHUNK_BYTES, MAX_SECONDS, Limits, _stream_hash
from .settings import PipelineSettings
from .spaces_readiness import BUCKET, ENDPOINT, _validate

MANIFEST_SHA256 = "efc10176621a16b8d28bf714cb667d72b467cbfae1434c79243ef1558993db5a"
PACKAGE_BYTES = 4_269_391_159
PREFIX = f"dev/source-staging/annual-nlcd-mrlc-c1v2/2025/{MANIFEST_SHA256}/"
TRANSFER_BOUND_USD = PACKAGE_BYTES / 1024**3 * 0.20 + 0.01
MAX_CENTRAL_BYTES = 65_536
MAX_ZIP_MEMBERS = 16


class PackageLimits(Limits):
    def account(self, length: int, *, source: bool) -> None:
        super().account(length, source=source)
        total = self.source_bytes if source else self.destination_bytes
        if total > PACKAGE_BYTES + (0 if source else 65_536):
            raise ValueError("MRLC byte ceiling exceeded")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def validate_manifest(members: Sequence[Mapping[str, Any]]) -> None:
    if hashlib.sha256(canonical(list(members))).hexdigest() != MANIFEST_SHA256:
        raise ValueError("Unreviewed MRLC distribution")


def member_path(directory: Path, member: Mapping[str, Any]) -> Path:
    path = directory / str(member["url"]).rsplit("/", 1)[-1]
    if path.is_symlink() or path.resolve().parent != directory.resolve():
        raise ValueError("Unsafe package path")
    return path


def identity(response: Any, member: Mapping[str, Any]) -> None:
    if response.status_code != 200 or (
        response.headers.get("Content-Length"),
        response.headers.get("ETag"),
        response.headers.get("Last-Modified"),
    ) != (str(member["bytes"]), member["etag"], member["last_modified"]):
        raise ValueError("MRLC HTTP identity drift or denied route")
    if response.headers.get("Content-Encoding", "identity") != "identity":
        raise ValueError("Unexpected transport encoding")


def validate_zip_layout(body: BinaryIO, expected_bytes: int, expected_count: int) -> None:
    """Bound every directory read before the stdlib ZIP parser sees the file.

    This contract accepts single-disk classic ZIP and the fixed ZIP64 EOCD
    form, including ZIP64 at small file sizes. Extensible ZIP64 records,
    concatenated archives, trailing data and directory signatures are excluded.
    """
    body.seek(0, os.SEEK_END)
    length = body.tell()
    if length != expected_bytes or not 0 < expected_count <= MAX_ZIP_MEMBERS:
        raise ValueError("ZIP file/count bound mismatch")
    tail_size = min(length, 65_535 + 22)
    body.seek(length - tail_size)
    tail = body.read(tail_size)
    index = tail.rfind(b"PK\x05\x06")
    if index < 0 or len(tail) - index < 22:
        raise ValueError("Missing bounded ZIP EOCD")
    _, disk, cd_disk, disk_count, count, size, offset, comment = struct.unpack(
        "<4s4H2LH", tail[index : index + 22]
    )
    end_offset = length - tail_size + index
    if end_offset + 22 + comment != length or disk != 0 or cd_disk != 0:
        raise ValueError("Invalid or multi-disk ZIP EOCD")
    directory_end = end_offset
    locator = b""
    if end_offset >= 20:
        body.seek(end_offset - 20)
        locator = body.read(20)
    if locator.startswith(b"PK\x06\x07"):
        _, zip_disk, zip_offset, disks = struct.unpack("<4sLQL", locator)
        if zip_disk != 0 or disks != 1 or zip_offset != end_offset - 20 - 56:
            raise ValueError("Invalid ZIP64 locator offset/disks")
        body.seek(zip_offset)
        record = body.read(56)
        if len(record) != 56 or record[:4] != b"PK\x06\x06":
            raise ValueError("Invalid bounded ZIP64 EOCD")
        record_size = struct.unpack_from("<Q", record, 4)[0]
        if record_size != 44:
            raise ValueError("ZIP64 extensible record outside contract")
        _, _, z_disk, z_cd_disk, z_disk_count, z_count, z_size, z_offset = struct.unpack(
            "<HHLLQQQQ", record[12:]
        )
        if z_disk != 0 or z_cd_disk != 0 or z_disk_count != z_count:
            raise ValueError("ZIP64 multi-disk/count mismatch")
        for classic, sentinel, extended in (
            (disk_count, 0xFFFF, z_disk_count),
            (count, 0xFFFF, z_count),
            (size, 0xFFFFFFFF, z_size),
            (offset, 0xFFFFFFFF, z_offset),
        ):
            if classic != sentinel and classic != extended:
                raise ValueError("Classic/ZIP64 directory mismatch")
        count, disk_count, size, offset = z_count, z_disk_count, z_size, z_offset
        directory_end = zip_offset
    elif count == 0xFFFF or disk_count == 0xFFFF or size == 0xFFFFFFFF or offset == 0xFFFFFFFF:
        raise ValueError("Missing ZIP64 locator")
    if (
        count != expected_count
        or disk_count != count
        or not 46 * count <= size <= MAX_CENTRAL_BYTES
        or offset < 0
        or offset + size != directory_end
    ):
        raise ValueError("ZIP central-directory size/count/offset bound")
    body.seek(offset)
    directory = body.read(size)
    if len(directory) != size:
        raise ValueError("Truncated bounded central directory")
    cursor = entries = 0
    while cursor < size:
        if size - cursor < 46 or directory[cursor : cursor + 4] != b"PK\x01\x02":
            raise ValueError("Invalid bounded central-directory entry")
        name, extra, entry_comment = struct.unpack_from("<3H", directory, cursor + 28)
        entry_disk = struct.unpack_from("<H", directory, cursor + 34)[0]
        cursor += 46 + name + extra + entry_comment
        entries += 1
        if cursor > size or entries > expected_count or entry_disk != 0:
            raise ValueError("Central-directory entry size/count/disk bound")
    if entries != expected_count:
        raise ValueError("Central-directory entry count mismatch")
    body.seek(0)


def archive_inventory(path: Path, member: Mapping[str, Any], limits: Limits) -> list[Any]:
    with path.open("rb") as body:
        limits.check()
        validate_zip_layout(body, int(member["bytes"]), len(member["members"]))
        return _archive_inventory(body, member, limits)


def _archive_inventory(body: BinaryIO, member: Mapping[str, Any], limits: Limits) -> list[Any]:
    result = []
    with zipfile.ZipFile(body) as archive:
        actual: list[dict[str, Any]] = [
            {
                "name": m.filename,
                "bytes": m.file_size,
                "compressed_bytes": m.compress_size,
                "crc32": f"{m.CRC:08x}",
                "method": m.compress_type,
                "flags": m.flag_bits,
                "external_attr": m.external_attr,
            }
            for m in archive.infolist()
        ]
        if actual != member["members"]:
            raise ValueError("ZIP member inventory drift")
        for entry in actual:
            name = entry["name"]
            if name in ("", ".", "..") or Path(name).name != name or "\\" in name or ":" in name:
                raise ValueError("Unsafe ZIP member")
            with archive.open(name) as member_body:
                # Complete reads also verify the ZIP CRC. No member is extracted.
                digest = local_hash(member_body, int(entry["bytes"]), limits)
            result.append({**entry, "sha256": digest})
    return result


def local_hash(body: Any, expected: int, limits: Limits) -> str:
    digest = hashlib.sha256()
    count = 0
    while True:
        limits.check()
        chunk = body.read(min(CHUNK_BYTES, expected - count + 1))
        if not chunk:
            break
        count += len(chunk)
        if count > expected:
            raise ValueError("Local member exceeds bound")
        digest.update(chunk)
    if count != expected:
        raise ValueError("Incomplete local member")
    return digest.hexdigest()


def captured(
    members: Sequence[Mapping[str, Any]], directory: Path, limits: Limits
) -> dict[str, Any]:
    receipt_path = directory / "mrlc-capture-receipt.json"
    if receipt_path.is_symlink():
        raise ValueError("Unsafe capture receipt")
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    if receipt and receipt.get("manifest_sha256") != MANIFEST_SHA256:
        raise ValueError("Capture receipt manifest mismatch")
    records = dict(receipt.get("packages", {}))
    for member in members:
        path = member_path(directory, member)
        partial = path.with_suffix(".zip.part")
        if partial.is_symlink():
            raise ValueError("Unsafe partial capture")
        record = records.get(member["url"])
        if path.exists():
            if not record or record.get("source") != dict(member):
                raise ValueError("Unreceipted existing package")
            with path.open("rb") as body:
                digest = local_hash(body, int(member["bytes"]), limits)
            if digest != record.get("sha256"):
                raise ValueError("Capture digest mismatch")
            if archive_inventory(path, member, limits) != record.get("members"):
                raise ValueError("Captured archive-member receipt mismatch")
        elif record:
            raise ValueError("Missing receipted package")
    if (directory / "mrlc-capture-receipt.json.part").is_symlink():
        raise ValueError("Unsafe partial receipt")
    return records


def capture(
    members: Sequence[Mapping[str, Any]], *, directory: Path, http: Any, limits: Limits
) -> dict[str, Any]:
    validate_manifest(members)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Private capture directory required")
    lock = directory / "mrlc-capture.lock"
    with lock.open("x") as owned:
        try:
            records = captured(members, directory, limits)
            # All identities and existing files pass before the first body GET.
            for member in members:
                limits.request()
                with http.head(
                    member["url"],
                    timeout=(5, 30),
                    allow_redirects=False,
                    headers={"Accept-Encoding": "identity"},
                ) as response:
                    identity(response, member)
            missing_bytes = sum(m["bytes"] for m in members if m["url"] not in records)
            if shutil.disk_usage(directory).free < missing_bytes + 256_000_000:
                raise ValueError("Capture disk reserve insufficient")
            for member in members:
                if member["url"] in records:
                    continue
                path = member_path(directory, member)
                partial = path.with_suffix(".zip.part")
                limits.request()
                retrieved_at = datetime.now(UTC).isoformat()
                with http.get(
                    member["url"],
                    stream=True,
                    timeout=(5, 30),
                    allow_redirects=False,
                    headers={
                        "Accept-Encoding": "identity",
                        "If-Match": member["etag"],
                        "If-Unmodified-Since": member["last_modified"],
                    },
                ) as response:
                    identity(response, member)
                    with partial.open("wb") as output:
                        digest = _stream_hash(
                            response.raw,
                            int(member["bytes"]),
                            limits,
                            source=True,
                            output=output,
                        )
                if limits.source_bytes > PACKAGE_BYTES:
                    raise ValueError("Package transfer cap exceeded")
                inventory = archive_inventory(partial, member, limits)
                path = partial.replace(path)
                records[member["url"]] = {
                    "source": dict(member),
                    "sha256": digest,
                    "members": inventory,
                    "retrieval_started_utc": retrieved_at,
                    "retrieval_verified_utc": datetime.now(UTC).isoformat(),
                    "capture_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                }
                report = {
                    "manifest_sha256": MANIFEST_SHA256,
                    "packages": records,
                    "requests_this_attempt": limits.requests,
                    "source_bytes_this_attempt": limits.source_bytes,
                }
                temporary = directory / "mrlc-capture-receipt.json.part"
                temporary.write_bytes(canonical(report))
                temporary.replace(directory / "mrlc-capture-receipt.json")
            return {
                "status": "MRLC_CAPTURE_COMPLETE",
                "packages": records,
                "requests_this_attempt": limits.requests,
                "source_bytes_this_attempt": limits.source_bytes,
            }
        finally:
            owned.close()
            lock.unlink()


def missing_head(destination: Any, key: str, limits: Limits) -> Any:
    limits.request()
    try:
        return destination.head_object(Bucket=BUCKET, Key=key)
    except ClientError as exc:
        if str(exc.response.get("Error", {}).get("Code")) not in ("404", "NoSuchKey", "NotFound"):
            raise
        return None


def stage(
    members: Sequence[Mapping[str, Any]],
    *,
    directory: Path,
    scratch: Path,
    settings: PipelineSettings,
    destination: Any,
    limits: Limits,
) -> dict[str, Any]:
    validate_manifest(members)
    _validate(settings, ())
    if TRANSFER_BOUND_USD + 9 > 10:
        raise ValueError("Total approved ceiling exceeded")
    if any(path.is_symlink() or not path.is_dir() for path in (scratch, directory)):
        raise ValueError("Private existing directories required")
    lock = scratch / "mrlc-staging.lock"
    with lock.open("x") as owned:
        try:
            records = captured(members, directory, limits)
            if set(records) != {m["url"] for m in members}:
                raise ValueError("Incomplete capture")
            state = scratch / "mrlc-staging-session.json"
            if state.is_symlink():
                raise ValueError("Unsafe session state")
            if state.exists():
                session = json.loads(state.read_text())
                if session.get("manifest_sha256") != MANIFEST_SHA256:
                    raise ValueError("Wrong session manifest")
                identifier = str(uuid.UUID(session["session_id"]))
                if identifier != session["session_id"]:
                    raise ValueError("Wrong session UUID")
            else:
                identifier = str(uuid.uuid4())
                with state.open("x") as output:
                    json.dump(
                        {"manifest_sha256": MANIFEST_SHA256, "session_id": identifier}, output
                    )
            prefix = PREFIX + identifier + "/"
            targets = []
            for member in members:
                path = member_path(directory, member)
                key = prefix + path.name
                record = records[member["url"]]
                target = missing_head(destination, key, limits)
                if target is not None and (
                    target.get("ContentLength") != member["bytes"]
                    or target.get("Metadata", {}).get("sha256") != record["sha256"]
                    or target.get("Metadata", {}).get("manifest-sha256") != MANIFEST_SHA256
                ):
                    raise ValueError("Existing destination mismatch; never overwrite")
                targets.append((member, path, key, record, target))
            staged = []
            for member, path, key, record, target in targets:
                if target is None:
                    # No temp spool: preflight hash and destination readback bind bytes.
                    limits.request()
                    with path.open("rb") as body:
                        destination.put_object(
                            Bucket=BUCKET,
                            Key=key,
                            Body=body,
                            ContentLength=member["bytes"],
                            ACL="private",
                            Metadata={
                                "sha256": record["sha256"],
                                "manifest-sha256": MANIFEST_SHA256,
                            },
                        )
                limits.request()
                response = destination.get_object(Bucket=BUCKET, Key=key)
                if response.get("ContentLength") != member["bytes"]:
                    response["Body"].close()
                    raise ValueError("Destination size mismatch")
                digest = _stream_hash(response["Body"], member["bytes"], limits, source=False)
                if digest != record["sha256"]:
                    raise ValueError("Destination SHA-256 mismatch")
                staged.append({**record, "destination_key": key})
            immutable = canonical(
                {
                    "distribution": "OFFICIAL_MRLC_HTTPS_ZIP",
                    "staging_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "manifest_sha256": MANIFEST_SHA256,
                    "packages": staged,
                }
            )
            if len(immutable) > 65_536:
                raise ValueError("Final manifest exceeds bound")
            key = prefix + "manifest.json"
            if missing_head(destination, key, limits) is None:
                limits.request()
                destination.put_object(
                    Bucket=BUCKET,
                    Key=key,
                    Body=immutable,
                    ContentLength=len(immutable),
                    ACL="private",
                )
            limits.request()
            response = destination.get_object(Bucket=BUCKET, Key=key)
            if response.get("ContentLength") != len(immutable):
                response["Body"].close()
                raise ValueError("Manifest size mismatch")
            digest = _stream_hash(response["Body"], len(immutable), limits, source=False)
            if digest != hashlib.sha256(immutable).hexdigest():
                raise ValueError("Manifest digest mismatch")
            report = {
                "status": "MRLC_STAGED_AND_READBACK_VERIFIED",
                "packages": staged,
                "requests": limits.requests,
                "destination_verification_bytes": limits.destination_bytes,
                "destination_manifest_key": key,
                "destination_manifest_sha256": digest,
                "source_download_bytes_this_upload_attempt": 0,
                "forecast_bound_usd": 9 + TRANSFER_BOUND_USD,
                "measured_bill_usd": None,
                "snowflake_operations": 0,
            }
            (scratch / "mrlc-staging-receipt.json").write_bytes(canonical(report))
            return report
        finally:
            owned.close()
            lock.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--scratch", type=Path)
    parser.add_argument("--capture-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    watchdog = threading.Timer(MAX_SECONDS, lambda: os._exit(124))
    watchdog.daemon = True
    watchdog.start()
    try:
        if not args.execute:
            raise ValueError("Reviewed execution required")
        members = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
        validate_manifest(members)
        if TRANSFER_BOUND_USD + 9 > 10:
            raise ValueError("Total approved ceiling exceeded")
        limits = PackageLimits()
        if args.capture_only:
            with requests.Session() as http:
                http.trust_env = False  # No implicit netrc/proxy credentials.
                # Existing HTTP adapter has zero retries; redirects are refused.
                report = capture(members, directory=args.directory, http=http, limits=limits)
        else:
            if args.scratch is None:
                raise ValueError("Private scratch required")
            settings = PipelineSettings(_env_file="/opt/oh-lyme/pmc-runtime.env")  # type: ignore[call-arg]
            _validate(settings, ())
            if settings.spaces_access_key_id is None or settings.spaces_secret_access_key is None:
                raise ValueError("Existing DEV Spaces identity unavailable")
            destination = boto3.client(
                "s3",
                endpoint_url=ENDPOINT,
                region_name="sfo3",
                aws_access_key_id=settings.spaces_access_key_id.get_secret_value(),
                aws_secret_access_key=settings.spaces_secret_access_key.get_secret_value(),
                config=Config(
                    connect_timeout=5, read_timeout=30, retries={"total_max_attempts": 1}
                ),
            )
            report = stage(
                members,
                directory=args.directory,
                scratch=args.scratch,
                settings=settings,
                destination=destination,
                limits=limits,
            )
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception:
        print(
            json.dumps({"status": "BLOCKED", "reason": "MRLC_PREREQUISITE_OR_VERIFICATION_FAILED"})
        )
        return 1
    finally:
        watchdog.cancel()


if __name__ == "__main__":
    raise SystemExit(main())
