"""Storage-only, version-pinned 2025 mosaic staging. Never connects to Snowflake."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, BinaryIO, cast

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from .settings import PipelineSettings
from .spaces_readiness import BUCKET, ENDPOINT, _validate

MANIFEST_SHA256 = "f413c5a2e5477c4af1ed5daa053d8a80428deb859cbfec53a8d031685919f2f4"
SOURCE_BYTES = 4_335_339_528
CHUNK_BYTES = 8 * 1024 * 1024
MAX_REQUESTS = 34
MAX_SECONDS = 1800
PREFIX = f"dev/source-staging/annual-nlcd-c1v2/2025/{MANIFEST_SHA256}/"


def load_manifest(path: Path) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8-sig"))
    digest = hashlib.sha256(
        json.dumps(members, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != MANIFEST_SHA256:
        raise ValueError("Unreviewed source manifest")
    return members


class Limits:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.started = clock()
        self.requests = 0
        self.source_bytes = 0
        self.destination_bytes = 0

    def check(self) -> None:
        if self.clock() - self.started >= MAX_SECONDS:
            raise ValueError("Elapsed time ceiling reached")

    def request(self) -> None:
        self.check()
        if self.requests >= MAX_REQUESTS:
            raise ValueError("Request ceiling reached")
        self.requests += 1

    def account(self, length: int, *, source: bool) -> None:
        self.check()
        if source:
            self.source_bytes += length
            total = self.source_bytes
        else:
            self.destination_bytes += length
            total = self.destination_bytes
        if total > SOURCE_BYTES + (0 if source else 65_536):
            raise ValueError("Transfer byte ceiling reached")


def _stream_hash(
    body: Any, expected: int, limits: Limits, *, source: bool, output: BinaryIO | None = None
) -> str:
    digest = hashlib.sha256()
    count = 0
    try:
        while True:
            limits.check()
            chunk = body.read(min(CHUNK_BYTES, expected - count + 1))
            if not chunk:
                break
            limits.account(len(chunk), source=source)
            count += len(chunk)
            if count > expected:
                raise ValueError("Object byte count exceeds manifest")
            digest.update(chunk)
            if output is not None:
                output.write(chunk)
    finally:
        body.close()
    if count != expected:
        raise ValueError("Incomplete object body")
    return digest.hexdigest()


def stage_members(
    members: Sequence[Mapping[str, Any]],
    *,
    settings: PipelineSettings,
    source: Any,
    destination: Any,
    scratch: Path,
    non_transfer_cost_bound_usd: float,
    limits: Limits | None = None,
) -> dict[str, Any]:
    """One sequential attempt, no multipart/retries, full destination readback.

    Caller must establish a bounded non-transfer cost before execution. This is
    an exposure forecast, not a billing reservation or a measured invoice.
    SDK clients must disable automatic retries and have bounded timeouts.
    """
    _validate(settings, ())
    if not 0 <= non_transfer_cost_bound_usd <= 9:
        raise ValueError("Unverified or excessive non-transfer cost bound")
    canonical = json.dumps(list(members), sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(canonical).hexdigest() != MANIFEST_SHA256:
        raise ValueError("Unreviewed source manifest")
    # Conservative combined transfer rate above current AWS/Spaces marginal
    # rates, plus $0.01 request allowance, separate from caller's runtime/storage.
    transfer_bound = SOURCE_BYTES / (1024**3) * 0.20 + 0.01
    if transfer_bound + non_transfer_cost_bound_usd > 10:
        raise ValueError("Total exposure exceeds approved $10 ceiling")
    if shutil.disk_usage(scratch).free < max(int(m["bytes"]) for m in members) + 256_000_000:
        raise ValueError("Insufficient bounded scratch disk")
    budget = limits or Limits()
    targets = []
    # Check every source/target identity before downloading any source bodies.
    for member in members:
        key = PREFIX + Path(str(member["key"])).name
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
            raise ValueError("Source identity drift")
        budget.request()
        try:
            target = destination.head_object(Bucket=BUCKET, Key=key)
        except ClientError as error:
            if str(error.response.get("Error", {}).get("Code")) not in (
                "404",
                "NoSuchKey",
                "NotFound",
            ):
                raise
            target = None
        if target is not None:
            metadata = target.get("Metadata", {})
            if (
                target.get("ContentLength") != member["bytes"]
                or metadata.get("source-version") != member["version_id"]
                or metadata.get("manifest-sha256") != MANIFEST_SHA256
                or len(metadata.get("sha256", "")) != 64
            ):
                raise ValueError("Existing destination identity mismatch; never overwrite")
        targets.append((member, key, target))
    receipts = []
    for member, key, target in targets:
        length = int(member["bytes"])
        if target is None:
            with tempfile.TemporaryFile(dir=scratch) as temporary:
                budget.request()
                response = source.get_object(
                    Bucket=member["bucket"],
                    Key=member["key"],
                    VersionId=member["version_id"],
                    RequestPayer="requester",
                )
                if (
                    response.get("ContentLength") != length
                    or response.get("VersionId") != member["version_id"]
                ):
                    response["Body"].close()
                    raise ValueError("Source GET identity drift")
                digest = _stream_hash(
                    response["Body"], length, budget, source=True, output=cast(BinaryIO, temporary)
                )
                temporary.seek(0)
                budget.request()
                # Conditional create prevents replacing another capture. If the
                # provider rejects this feature, stop; never retry without it.
                destination.put_object(
                    Bucket=BUCKET,
                    Key=key,
                    Body=temporary,
                    ContentLength=length,
                    IfNoneMatch="*",
                    ACL="private",
                    Metadata={
                        "sha256": digest,
                        "source-version": member["version_id"],
                        "manifest-sha256": MANIFEST_SHA256,
                    },
                )
        else:
            digest = target["Metadata"]["sha256"]
        budget.request()
        verified = destination.get_object(Bucket=BUCKET, Key=key)
        if verified.get("ContentLength") != length:
            verified["Body"].close()
            raise ValueError("Destination size mismatch")
        actual = _stream_hash(verified["Body"], length, budget, source=False)
        if actual != digest:
            raise ValueError("Destination SHA-256 mismatch")
        receipts.append(
            {
                "source": dict(member),
                "destination_key": key,
                "sha256": digest,
                "bytes": length,
                "reused": target is not None,
            }
        )
    report = {
        "status": "STAGED_AND_READBACK_VERIFIED",
        "members": receipts,
        "manifest_sha256": MANIFEST_SHA256,
        "requests": budget.requests,
        "source_download_bytes": budget.source_bytes,
        "destination_verification_bytes": budget.destination_bytes,
        "forecast_bound_usd": transfer_bound + non_transfer_cost_bound_usd,
        "measured_bill_usd": None,
        "snowflake_operations": 0,
    }
    payload = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    immutable = json.dumps(
        {
            "manifest_sha256": MANIFEST_SHA256,
            "members": [
                {k: v for k, v in receipt.items() if k != "reused"} for receipt in receipts
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    if len(immutable) > 65_536:
        raise ValueError("Receipt exceeds bound")
    receipt_key = PREFIX + "manifest.json"
    budget.request()
    try:
        destination.head_object(Bucket=BUCKET, Key=receipt_key)
    except ClientError as error:
        if str(error.response.get("Error", {}).get("Code")) not in ("404", "NoSuchKey", "NotFound"):
            raise
        budget.request()
        destination.put_object(
            Bucket=BUCKET,
            Key=receipt_key,
            Body=immutable,
            ContentLength=len(immutable),
            IfNoneMatch="*",
            ACL="private",
        )
    budget.request()
    receipt_response = destination.get_object(Bucket=BUCKET, Key=receipt_key)
    if receipt_response.get("ContentLength") != len(immutable):
        receipt_response["Body"].close()
        raise ValueError("Existing receipt mismatch")
    if (
        _stream_hash(receipt_response["Body"], len(immutable), budget, source=False)
        != hashlib.sha256(immutable).hexdigest()
    ):
        raise ValueError("Receipt digest mismatch")
    report["requests"] = budget.requests
    report["destination_verification_bytes"] = budget.destination_bytes
    report["destination_manifest_key"] = receipt_key
    payload = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    (scratch / "nlcd-staging-receipt.json").write_bytes(payload)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--non-transfer-cost-bound-usd", type=float, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if not args.execute:
            raise ValueError("Explicit reviewed execution required")
        settings = PipelineSettings()
        _validate(settings, ())
        members = load_manifest(args.manifest)
        session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE"))
        if session.get_credentials() is None:
            raise ValueError("Existing AWS identity unavailable")
        if settings.spaces_access_key_id is None or settings.spaces_secret_access_key is None:
            raise ValueError("Existing Spaces runtime identity unavailable")
        config = Config(
            connect_timeout=5,
            read_timeout=30,
            retries={"total_max_attempts": 1},
            s3={"addressing_style": "virtual"},
        )
        source = session.client("s3", region_name="us-west-2", config=config)
        destination = boto3.client(
            "s3",
            endpoint_url=ENDPOINT,
            region_name="sfo3",
            config=config,
            aws_access_key_id=settings.spaces_access_key_id.get_secret_value(),
            aws_secret_access_key=settings.spaces_secret_access_key.get_secret_value(),
        )
        report = stage_members(
            members,
            settings=settings,
            source=source,
            destination=destination,
            scratch=args.scratch,
            non_transfer_cost_bound_usd=args.non_transfer_cost_bound_usd,
        )
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception:
        print(
            json.dumps(
                {"status": "BLOCKED", "reason": "STAGING_PREREQUISITE_OR_VERIFICATION_FAILED"}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
