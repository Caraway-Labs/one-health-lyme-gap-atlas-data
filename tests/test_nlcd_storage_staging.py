from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

import lyme_gap_atlas_data.nlcd_storage_staging as staging
from lyme_gap_atlas_data.settings import PipelineSettings
from lyme_gap_atlas_data.spaces_readiness import ENDPOINT


class Source:
    def __init__(self, members: list[dict[str, Any]]) -> None:
        self.members = {m["key"]: m for m in members}
        self.gets = 0

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        m = self.members[kwargs["Key"]]
        assert kwargs["VersionId"] == m["version_id"]
        assert kwargs["RequestPayer"] == "requester"
        return {"ContentLength": m["bytes"], "VersionId": m["version_id"], "ETag": m["etag"]}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.gets += 1
        return {**self.head_object(**kwargs), "Body": io.BytesIO(b"data")}


class Destination:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, dict[str, str]]] = {}
        self.puts = 0
        self.corrupt = False

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        if kwargs["Key"] not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        body, meta = self.objects[kwargs["Key"]]
        return {"ContentLength": len(body), "Metadata": meta}

    def put_object(self, **kwargs: Any) -> None:
        assert kwargs["IfNoneMatch"] == "*" and kwargs["ACL"] == "private"
        assert kwargs["Key"] not in self.objects
        value = kwargs["Body"]
        body = value if isinstance(value, bytes) else value.read()
        assert len(body) == kwargs["ContentLength"]
        self.objects[kwargs["Key"]] = (body, kwargs.get("Metadata", {}))
        self.puts += 1

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        body = self.objects[kwargs["Key"]][0]
        return {"ContentLength": len(body), "Body": io.BytesIO(b"bad!" if self.corrupt else body)}


@pytest.fixture
def case(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, ...]:
    members = [
        {
            "bucket": "usgs-landcover",
            "key": f"product{n}.tif",
            "bytes": 4,
            "version_id": f"v{n}",
            "etag": "etag",
        }
        for n in range(6)
    ]
    digest = hashlib.sha256(
        json.dumps(members, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    monkeypatch.setattr(staging, "MANIFEST_SHA256", digest)
    monkeypatch.setattr(staging, "SOURCE_BYTES", 24)
    return members, Source(members), Destination(), tmp_path


def run(case: tuple[Any, ...], **changes: Any) -> dict[str, Any]:
    members, source, destination, path = case
    return staging.stage_members(
        members,
        settings=PipelineSettings(_env_file=None, spaces_endpoint=ENDPOINT),
        source=source,
        destination=destination,
        scratch=path,
        non_transfer_cost_bound_usd=0,
        **changes,
    )


def test_staging_verifies_all_bytes_and_resume_avoids_source_download(
    case: tuple[Any, ...],
) -> None:
    first = run(case)
    assert first["status"] == "STAGED_AND_READBACK_VERIFIED"
    assert first["source_download_bytes"] == 24 and first["requests"] == 33
    assert case[1].gets == 6 and case[2].puts == 7
    assert len(case[2].objects) == 7
    second = run(case)
    assert second["source_download_bytes"] == 0
    assert all(item["reused"] for item in second["members"])
    assert case[1].gets == 6 and case[2].puts == 7


def test_existing_mismatch_never_overwrites_or_downloads(case: tuple[Any, ...]) -> None:
    key = staging.PREFIX + "product0.tif"
    case[2].objects[key] = (b"data", {})
    with pytest.raises(ValueError, match="Existing destination"):
        run(case)
    assert case[1].gets == 0 and case[2].puts == 0


def test_destination_checksum_failure_never_publishes_manifest(case: tuple[Any, ...]) -> None:
    case[2].corrupt = True
    with pytest.raises(ValueError, match="SHA-256"):
        run(case)
    assert len(case[2].objects) == 1
    assert staging.PREFIX + "manifest.json" not in case[2].objects


def test_manifest_drift_stops_before_requests(case: tuple[Any, ...]) -> None:
    case[0][0]["version_id"] = "changed"
    with pytest.raises(ValueError, match="Unreviewed"):
        run(case)
    assert case[1].gets == 0 and case[2].puts == 0


def test_limits_stop_before_next_request_and_on_long_body() -> None:
    limits = staging.Limits(clock=lambda: 0)
    for _ in range(staging.MAX_REQUESTS):
        limits.request()
    with pytest.raises(ValueError, match="Request ceiling"):
        limits.request()
    with pytest.raises(ValueError, match="exceeds manifest"):
        staging._stream_hash(io.BytesIO(b"12345"), 4, staging.Limits(), source=True)
    with pytest.raises(ValueError, match="Incomplete"):
        staging._stream_hash(io.BytesIO(b"123"), 4, staging.Limits(), source=True)


def test_elapsed_limit_and_budget_reject_without_transfer(case: tuple[Any, ...]) -> None:
    now = [0.0]
    limits = staging.Limits(clock=lambda: now[0])
    now[0] = staging.MAX_SECONDS
    with pytest.raises(ValueError, match="Elapsed"):
        run(case, limits=limits)
    members, source, destination, path = case
    with pytest.raises(ValueError, match="non-transfer"):
        staging.stage_members(
            members,
            settings=PipelineSettings(_env_file=None, spaces_endpoint=ENDPOINT),
            source=source,
            destination=destination,
            scratch=path,
            non_transfer_cost_bound_usd=float("nan"),
        )
    assert source.gets == 0 and destination.puts == 0


def test_committed_manifest_is_exact() -> None:
    path = Path(__file__).parents[1] / "config/annual-nlcd-2025-staging-manifest.json"
    members = staging.load_manifest(path)
    assert len(members) == 6
    assert sum(m["bytes"] for m in members) == staging.SOURCE_BYTES
    assert all(m["version_id"] and m["bucket"] == "usgs-landcover" for m in members)
