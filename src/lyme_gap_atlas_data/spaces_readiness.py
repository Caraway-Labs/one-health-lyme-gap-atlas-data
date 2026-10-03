"""Bounded DEV object metadata inspection, independent of ingestion and Snowflake."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from typing import Any

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]

from .settings import PipelineSettings

ENDPOINT = "https://sfo3.digitaloceanspaces.com"
BUCKET = "one-health-lyme-gap-atlas-data-dev"
PREFIX = "dev/"
MAX_KEYS = 100
MAX_HEADS = 16


def _validate(settings: PipelineSettings, candidate_keys: Sequence[str]) -> None:
    if (
        settings.topx_env != "dev"
        or settings.spaces_endpoint != ENDPOINT
        or settings.spaces_bucket != BUCKET
        or settings.spaces_prefix != "dev"
        or settings.spaces_region != "sfo3"
    ):
        raise ValueError("Unexpected DEV Spaces configuration")
    if (
        len(candidate_keys) > MAX_HEADS
        or len(set(candidate_keys)) != len(candidate_keys)
        or any(
            not key.startswith(PREFIX)
            or len(key.encode()) > 1024
            or any(part in ("", ".", "..") for part in key.split("/"))
            or any(ord(character) < 32 for character in key)
            for key in candidate_keys
        )
    ):
        raise ValueError("Invalid bounded DEV candidate keys")


def inspect_spaces(
    settings: PipelineSettings, *, client: Any, candidate_keys: Sequence[str] = ()
) -> dict[str, object]:
    """One bucket HEAD, one bounded LIST and at most sixteen object HEADs.

    A truncated listing is not proof of absence. Metadata reads never establish
    upload permission or byte identity; ETags are not asserted to be SHA-256.
    """
    _validate(settings, candidate_keys)
    client.head_bucket(Bucket=BUCKET)
    listing = client.list_objects_v2(Bucket=BUCKET, Prefix=PREFIX, MaxKeys=MAX_KEYS)
    objects = listing.get("Contents", [])
    if len(objects) > MAX_KEYS or any(not item["Key"].startswith(PREFIX) for item in objects):
        raise ValueError("Unexpected bounded listing response")
    listed = [{"key": item["Key"], "bytes": item["Size"]} for item in objects]
    candidates = []
    for key in candidate_keys:
        response = client.head_object(Bucket=BUCKET, Key=key)
        candidates.append(
            {
                "key": key,
                "bytes": response["ContentLength"],
                "etag": response.get("ETag"),
                "version_id": response.get("VersionId"),
                "sha256": response.get("ChecksumSHA256"),
            }
        )
    return {
        "status": "READ_METADATA_VERIFIED",
        "bucket": BUCKET,
        "prefix": PREFIX,
        "listing_truncated": bool(listing.get("IsTruncated", False)),
        "listed_objects": listed,
        "candidate_objects": candidates,
        "metadata_requests": 2 + len(candidate_keys),
        "payload_bytes_downloaded": 0,
        "write_permission": "NOT_TESTED",
        "byte_identity": "NOT_VERIFIED_BY_METADATA",
    }


def main() -> int:
    try:
        settings = PipelineSettings()
        keys = json.loads(os.environ.get("SPACES_CANDIDATE_KEYS_JSON", "[]"))
        if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
            raise ValueError("Candidate keys must be a JSON string array")
        _validate(settings, keys)
        if settings.spaces_access_key_id is None or settings.spaces_secret_access_key is None:
            raise ValueError("Missing existing Spaces runtime identity")
        client = boto3.client(
            "s3",
            endpoint_url=ENDPOINT,
            region_name="sfo3",
            aws_access_key_id=settings.spaces_access_key_id.get_secret_value(),
            aws_secret_access_key=settings.spaces_secret_access_key.get_secret_value(),
            config=Config(
                connect_timeout=5,
                read_timeout=10,
                retries={"total_max_attempts": 1},
                s3={"addressing_style": "virtual"},
            ),
        )
        report = inspect_spaces(settings, client=client, candidate_keys=keys)
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception:
        # Provider exception text and configuration may contain sensitive data.
        print(json.dumps({"status": "BLOCKED", "reason": "CONFIG_OR_METADATA_CHECK_FAILED"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
