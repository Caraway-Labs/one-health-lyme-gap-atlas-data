from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

import lyme_gap_atlas_data.mrlc_storage_staging as mrlc
from lyme_gap_atlas_data.settings import PipelineSettings
from lyme_gap_atlas_data.spaces_readiness import ENDPOINT


class Response:
    status_code = 200

    def __init__(self, member: dict[str, Any], body: bytes = b"") -> None:
        self.headers = {
            "Content-Length": str(member["bytes"]),
            "ETag": member["etag"],
            "Last-Modified": member["last_modified"],
        }
        self.raw = io.BytesIO(body)

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: Any) -> None:
        self.raw.close()


class HTTP:
    def __init__(self, members: list[Any], bodies: dict[str, bytes]) -> None:
        self.members = {m["url"]: m for m in members}
        self.bodies = bodies
        self.heads = 0
        self.gets = 0
        self.drift: str | None = None

    def head(self, url: str, **kwargs: Any) -> Response:
        self.heads += 1
        assert kwargs["allow_redirects"] is False
        response = Response(self.members[url])
        if url == self.drift:
            response.headers["ETag"] = "changed"
        return response

    def get(self, url: str, **kwargs: Any) -> Response:
        self.gets += 1
        assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
        assert kwargs["headers"]["If-Match"] == self.members[url]["etag"]
        assert kwargs["headers"]["If-Unmodified-Since"] == self.members[url]["last_modified"]
        return Response(self.members[url], self.bodies[url])


class Destination:
    def __init__(self) -> None:
        self.objects: dict[str, Any] = {}
        self.puts = 0
        self.heads = 0
        self.corrupt = False

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self.heads += 1
        if kwargs["Key"] not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        body, metadata = self.objects[kwargs["Key"]]
        return {"ContentLength": len(body), "Metadata": metadata}

    def put_object(self, **kwargs: Any) -> None:
        self.puts += 1
        assert kwargs["ACL"] == "private"
        body = kwargs["Body"]
        payload = body if isinstance(body, bytes) else body.read()
        assert len(payload) == kwargs["ContentLength"]
        self.objects[kwargs["Key"]] = (payload, kwargs.get("Metadata", {}))

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        body, metadata = self.objects[kwargs["Key"]]
        if self.corrupt:
            body = b"X" + body[1:]
        return {"ContentLength": len(body), "Body": io.BytesIO(body)}


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    members, bodies = [], {}
    for product in ("LndCov", "FctImp", "LndChg"):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for suffix in ("tif", "xml", "tif.aux.xml"):
                archive.writestr(f"Annual_NLCD_{product}_2025_CU_C1V2.{suffix}", b"fixture")
        payload = buffer.getvalue()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            inventory = [
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
        url = f"https://www.mrlc.gov/Annual_NLCD_{product}_2025_CU_C1V2.zip"
        members.append(
            {
                "product": product,
                "url": url,
                "bytes": len(payload),
                "etag": '"fixture"',
                "last_modified": "fixture-date",
                "members": inventory,
            }
        )
        bodies[url] = payload
    monkeypatch.setattr(
        mrlc, "MANIFEST_SHA256", hashlib.sha256(mrlc.canonical(members)).hexdigest()
    )
    monkeypatch.setattr(mrlc, "PACKAGE_BYTES", sum(m["bytes"] for m in members))
    directory = tmp_path / "capture"
    directory.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return members, HTTP(members, bodies), Destination(), directory, scratch


def run_capture(case: tuple[Any, ...]) -> dict[str, Any]:
    members, http, destination, directory, scratch = case
    return mrlc.capture(members, directory=directory, http=http, limits=mrlc.PackageLimits())


def run_stage(case: tuple[Any, ...]) -> dict[str, Any]:
    members, http, destination, directory, scratch = case
    return mrlc.stage(
        members,
        directory=directory,
        scratch=scratch,
        settings=PipelineSettings(_env_file=None, spaces_endpoint=ENDPOINT),
        destination=destination,
        limits=mrlc.PackageLimits(),
    )


def test_capture_stage_resume_preserves_package_and_member_lineage(case: tuple[Any, ...]) -> None:
    members, http, destination, directory, scratch = case
    report = run_capture(case)
    assert report["source_bytes_this_attempt"] == sum(m["bytes"] for m in members)
    assert http.heads == 3 and http.gets == 3
    assert len(report["packages"]) == 3
    assert all(len(record["members"]) == 3 for record in report["packages"].values())
    assert run_capture(case)["source_bytes_this_attempt"] == 0 and http.gets == 3
    staged = run_stage(case)
    assert staged["status"] == "MRLC_STAGED_AND_READBACK_VERIFIED"
    assert staged["requests"] == 12 and destination.puts == 4
    assert staged["snowflake_operations"] == 0
    assert staged["source_download_bytes_this_upload_attempt"] == 0
    assert (
        "OFFICIAL_MRLC_HTTPS_ZIP"
        in destination.objects[staged["destination_manifest_key"]][0].decode()
    )
    assert run_stage(case)["requests"] == 8 and destination.puts == 4


def test_late_source_drift_prevents_all_downloads(case: tuple[Any, ...]) -> None:
    members, http, destination, directory, scratch = case
    http.drift = members[-1]["url"]
    with pytest.raises(ValueError, match="HTTP identity"):
        run_capture(case)
    assert http.heads == 3 and http.gets == 0
    assert not (directory / "mrlc-capture.lock").exists()


@pytest.mark.parametrize("phase", ["capture", "stage"])
def test_exclusive_locks_precede_requests(case: tuple[Any, ...], phase: str) -> None:
    members, http, destination, directory, scratch = case
    owner = directory if phase == "capture" else scratch
    name = "mrlc-capture.lock" if phase == "capture" else "mrlc-staging.lock"
    (owner / name).write_text("another-session")
    with pytest.raises(FileExistsError):
        (run_capture if phase == "capture" else run_stage)(case)
    assert http.heads == http.gets == destination.heads == destination.puts == 0
    assert (owner / name).read_text() == "another-session"


def test_late_unreceipted_file_prevents_capture_requests(case: tuple[Any, ...]) -> None:
    members, http, destination, directory, scratch = case
    mrlc.member_path(directory, members[-1]).write_bytes(b"unreceipted")
    with pytest.raises(ValueError, match="Unreceipted"):
        run_capture(case)
    assert http.heads == http.gets == 0


@pytest.mark.parametrize("tamper", ["package", "member-receipt"])
def test_capture_tampering_blocks_all_destination_requests(
    case: tuple[Any, ...], tamper: str
) -> None:
    members, http, destination, directory, scratch = case
    run_capture(case)
    if tamper == "package":
        path = mrlc.member_path(directory, members[-1])
        data = path.read_bytes()
        path.write_bytes(b"X" + data[1:])
    else:
        path = directory / "mrlc-capture-receipt.json"
        receipt = json.loads(path.read_text())
        receipt["packages"][members[-1]["url"]]["members"][0]["sha256"] = "0" * 64
        path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="digest mismatch|archive-member receipt"):
        run_stage(case)
    assert destination.heads == destination.puts == 0


def test_readback_corruption_blocks_completion_manifest(case: tuple[Any, ...]) -> None:
    members, http, destination, directory, scratch = case
    run_capture(case)
    destination.corrupt = True
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        run_stage(case)
    assert destination.puts == 1
    assert not any(key.endswith("manifest.json") for key in destination.objects)
    assert not (scratch / "mrlc-staging-receipt.json").exists()


def test_byte_and_elapsed_ceilings(case: tuple[Any, ...]) -> None:
    limit = mrlc.PackageLimits()
    with pytest.raises(ValueError, match="MRLC byte ceiling"):
        limit.account(mrlc.PACKAGE_BYTES + 1, source=True)
    ticks = iter([0, 1800])
    limit = mrlc.PackageLimits(clock=lambda: next(ticks))
    with pytest.raises(ValueError, match="Elapsed"):
        mrlc.local_hash(io.BytesIO(b"x"), 1, limit)


def test_manifest_drift_is_rejected_before_requests(case: tuple[Any, ...]) -> None:
    members, http, destination, directory, scratch = case
    members[-1]["bytes"] += 1
    with pytest.raises(ValueError, match="Unreviewed"):
        run_capture(case)
    assert http.heads == http.gets == 0


def test_zip_member_expansion_drift_is_rejected(case: tuple[Any, ...]) -> None:
    members, http, destination, directory, scratch = case
    path = directory / "fixture.zip"
    path.write_bytes(http.bodies[members[0]["url"]])
    members[0]["members"][-1]["bytes"] += 1
    with pytest.raises(ValueError, match="ZIP member inventory"):
        mrlc.archive_inventory(path, members[0], mrlc.PackageLimits())


def test_existing_destination_mismatch_is_never_overwritten(case: tuple[Any, ...]) -> None:
    members, http, destination, directory, scratch = case
    run_capture(case)
    staged = run_stage(case)
    key = staged["packages"][-1]["destination_key"]
    payload, metadata = destination.objects[key]
    metadata["sha256"] = "0" * 64
    destination.puts = 0
    with pytest.raises(ValueError, match="never overwrite"):
        run_stage(case)
    assert destination.puts == 0


def test_crc_corruption_cannot_create_capture_receipt(case: tuple[Any, ...]) -> None:
    members, http, destination, directory, scratch = case
    url = members[0]["url"]
    payload = bytearray(http.bodies[url])
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        info = archive.infolist()[0]
        offset = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    payload[offset + 2] ^= 1
    http.bodies[url] = bytes(payload)
    with pytest.raises((zipfile.BadZipFile, ValueError)):
        run_capture(case)
    assert not (directory / "mrlc-capture-receipt.json").exists()
