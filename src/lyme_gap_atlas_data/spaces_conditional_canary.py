"""Five-call private owned-object canary; never uses source/user object keys."""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from typing import Any

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from .settings import PipelineSettings
from .spaces_readiness import BUCKET, ENDPOINT, _validate


def verify_conditional_create(settings: PipelineSettings, *, client: Any) -> dict[str, object]:
    _validate(settings, ())
    prefix = f"dev/staging-canary/{uuid.uuid4()}/"
    key = prefix + "conditional.txt"
    original = b"atlas-private-canary-original"
    different = b"atlas-private-canary-different"
    try:
        client.head_object(Bucket=BUCKET, Key=key)
    except ClientError as error:
        if str(error.response.get("Error", {}).get("Code")) not in ("404", "NotFound", "NoSuchKey"):
            raise
    else:
        raise ValueError("Canary namespace collision; no writes performed")
    client.put_object(Bucket=BUCKET, Key=key, Body=original, ACL="private")
    rejected = False
    response_code = "SUCCESS"
    try:
        client.put_object(Bucket=BUCKET, Key=key, Body=different, ACL="private", IfNoneMatch="*")
    except ClientError as error:
        response_code = str(error.response.get("Error", {}).get("Code", "UNKNOWN"))
        rejected = response_code in ("412", "PreconditionFailed")
    response = client.get_object(Bucket=BUCKET, Key=key)
    try:
        actual = response["Body"].read(1025)
    finally:
        response["Body"].close()
    preserved = actual == original
    report: dict[str, object] = {
        "status": "CONDITIONAL_CREATE_VERIFIED" if rejected and preserved else "NOT_VERIFIED",
        "object_key": key,
        "conditional_response_code": response_code,
        "original_preserved": preserved,
        "readback_sha256": hashlib.sha256(actual).hexdigest(),
        "metadata_and_object_requests": 5,
        "source_download_bytes": 0,
        "snowflake_operations": 0,
    }
    receipt = json.dumps(report, sort_keys=True).encode()
    if len(receipt) > 1024:
        raise ValueError("Canary receipt exceeds bound")
    client.put_object(Bucket=BUCKET, Key=prefix + "receipt.json", Body=receipt, ACL="private")
    # Retain both tiny owned objects, including negative outcomes. No delete,
    # ACL mutation, source payload or unrelated key is ever involved.
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-canary", action="store_true")
    args = parser.parse_args()
    try:
        if not args.execute_canary:
            raise ValueError("Reviewed canary execution required")
        settings = PipelineSettings(_env_file="/opt/oh-lyme/pmc-runtime.env")  # type: ignore[call-arg]
        _validate(settings, ())
        if settings.spaces_access_key_id is None or settings.spaces_secret_access_key is None:
            raise ValueError("Existing Spaces identity required")
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
        report = verify_conditional_create(settings, client=client)
        print(json.dumps(report, sort_keys=True))
        return 0 if report["status"] == "CONDITIONAL_CREATE_VERIFIED" else 1
    except Exception:
        print(
            json.dumps({"status": "BLOCKED", "reason": "CANARY_PREREQUISITE_OR_PROVIDER_FAILURE"})
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
