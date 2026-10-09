"""Bounded DEV object metadata inspection, independent of ingestion and Snowflake."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from typing import Any

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from .settings import PipelineSettings

ENDPOINT = "https://sfo3.digitaloceanspaces.com"
BUCKET = "one-health-lyme-gap-atlas-data-dev"
PREFIX = "dev/"
JANUARY_PREFIX = "dev/diagnostics/january-2025/"
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


def inspect_january_donor_storage(settings: PipelineSettings, *, client: Any) -> dict[str, object]:
    """Read the existing bucket ACL and expiration rule; never modify either."""
    _validate(settings, ())
    client.head_bucket(Bucket=BUCKET)
    acl = client.get_bucket_acl(Bucket=BUCKET)
    grants = acl.get("Grants", [])
    owner_id = acl.get("Owner", {}).get("ID")
    private = (
        isinstance(owner_id, str)
        and bool(owner_id)
        and len(grants) == 1
        and grants[0].get("Grantee", {}).get("Type") == "CanonicalUser"
        and grants[0].get("Grantee", {}).get("ID") == owner_id
        and grants[0].get("Permission") == "FULL_CONTROL"
    )
    try:
        client.get_bucket_policy(Bucket=BUCKET)
        policy_absent = False
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        policy_absent = code in {"NoSuchBucketPolicy", "NoSuchBucketPolicyException"}
    try:
        versioning = client.get_bucket_versioning(Bucket=BUCKET)
        never_versioned = isinstance(versioning, dict) and set(versioning) <= {"ResponseMetadata"}
    except ClientError:
        never_versioned = False
    try:
        lifecycle = client.get_bucket_lifecycle_configuration(Bucket=BUCKET)
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code == "NoSuchLifecycleConfiguration":
            lifecycle = {"Rules": []}
        else:
            return {
                "status": "BLOCKED",
                "reason": "LIFECYCLE_METADATA_INACCESSIBLE",
                "bucket": BUCKET,
                "prefix": JANUARY_PREFIX,
                "private_bucket_acl": private,
                "retention_days": None,
                "metadata_requests": 5,
                "payload_bytes_downloaded": 0,
                "write_permission": "NOT_TESTED",
            }
    matches = [
        rule
        for rule in lifecycle.get("Rules", [])
        if rule.get("Status") == "Enabled"
        and rule.get("Filter", {}).get("Prefix", rule.get("Prefix")) == JANUARY_PREFIX
        and type(rule.get("Expiration", {}).get("Days")) is int
        and 0 < rule["Expiration"]["Days"] <= 14
    ]
    reason = (
        "BUCKET_ACL_NOT_OWNER_ONLY"
        if not private
        else "BUCKET_POLICY_PRESENT_OR_UNVERIFIED"
        if not policy_absent
        else "BUCKET_VERSIONING_PRESENT_OR_UNVERIFIED"
        if not never_versioned
        else "JANUARY_EXPIRY_RULE_MISSING_OR_TOO_LONG"
        if not matches
        else None
    )
    return {
        "status": "PRIVATE_JANUARY_STORAGE_VERIFIED"
        if private and policy_absent and never_versioned and matches
        else "BLOCKED",
        "reason": reason,
        "bucket": BUCKET,
        "prefix": JANUARY_PREFIX,
        "private_bucket_acl": private,
        "bucket_policy_absent": policy_absent,
        "bucket_never_versioned": never_versioned,
        "retention_days": min((r["Expiration"]["Days"] for r in matches), default=None),
        "metadata_requests": 5,
        "payload_bytes_downloaded": 0,
        "write_permission": "NOT_TESTED",
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
        if os.environ.get("JANUARY_DONOR_STORAGE_PREFLIGHT") == "true" and keys:
            raise ValueError("January storage preflight accepts no object keys")
        report = (
            inspect_january_donor_storage(settings, client=client)
            if os.environ.get("JANUARY_DONOR_STORAGE_PREFLIGHT") == "true"
            else inspect_spaces(settings, client=client, candidate_keys=keys)
        )
        print(json.dumps(report, sort_keys=True))
        return 0 if report["status"] != "BLOCKED" else 1
    except Exception:
        # Provider exception text and configuration may contain sensitive data.
        print(json.dumps({"status": "BLOCKED", "reason": "CONFIG_OR_METADATA_CHECK_FAILED"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
