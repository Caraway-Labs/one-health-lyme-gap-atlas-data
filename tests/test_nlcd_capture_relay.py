from __future__ import annotations

import json
from typing import Any

import pytest

import lyme_gap_atlas_data.nlcd_capture_relay as relay
import lyme_gap_atlas_data.nlcd_storage_staging as staging
from lyme_gap_atlas_data.settings import PipelineSettings
from lyme_gap_atlas_data.spaces_readiness import ENDPOINT


@pytest.fixture
def case(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> tuple[Any, ...]:
    import test_nlcd_storage_staging as helpers

    return helpers.case.__wrapped__(monkeypatch, tmp_path)


@pytest.fixture
def captured(case: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    monkeypatch.setattr(relay, "MANIFEST_SHA256", staging.MANIFEST_SHA256)
    monkeypatch.setattr(relay, "SOURCE_BYTES", staging.SOURCE_BYTES)
    members, source, destination, path = case
    capture = path / "capture"
    capture.mkdir()
    report = relay.capture_members(members, source=source, directory=capture)
    return members, source, destination, path, capture, report


def test_capture_receipts_and_private_relay_need_no_remote_aws(captured: tuple[Any, ...]) -> None:
    members, source, destination, path, capture, report = captured
    assert report["status"] == "CAPTURE_COMPLETE"
    assert source.gets == 6 and report["source_download_bytes_this_attempt"] == 24
    again = relay.capture_members(members, source=source, directory=capture)
    assert again["source_download_bytes_this_attempt"] == 0 and source.gets == 6
    scratch = path / "upload"
    scratch.mkdir()
    result = staging.stage_members(
        members,
        source=relay.VerifiedDirectorySource(members, capture),
        destination=destination,
        scratch=scratch,
        settings=PipelineSettings(_env_file=None, spaces_endpoint=ENDPOINT),
        non_transfer_cost_bound_usd=0,
    )
    assert result["status"] == "STAGED_AND_READBACK_VERIFIED"
    assert source.gets == 6


def test_tampered_relay_file_blocks_before_upload(captured: tuple[Any, ...]) -> None:
    members, source, destination, path, capture, report = captured
    (capture / "product0.tif").write_bytes(b"bad!")
    scratch = path / "upload"
    scratch.mkdir()
    with pytest.raises(ValueError, match="Relay SHA-256"):
        staging.stage_members(
            members,
            source=relay.VerifiedDirectorySource(members, capture),
            destination=destination,
            scratch=scratch,
            settings=PipelineSettings(_env_file=None, spaces_endpoint=ENDPOINT),
            non_transfer_cost_bound_usd=0,
        )
    assert destination.puts == 0


def test_incomplete_capture_is_not_uploadable(captured: tuple[Any, ...]) -> None:
    members, source, destination, path, capture, report = captured
    receipt = capture / "capture-receipt.json"
    content = json.loads(receipt.read_text())
    del content["members"][members[0]["key"]]
    receipt.write_text(json.dumps(content))
    with pytest.raises(ValueError, match="Incomplete relay"):
        relay.VerifiedDirectorySource(members, capture)


def test_exclusive_session_refuses_concurrent_upload(case: tuple[Any, ...]) -> None:
    members, source, destination, path = case
    (path / "nlcd-staging.lock").write_text("owned-existing-session")
    with pytest.raises(FileExistsError):
        staging.stage_members(
            members,
            source=source,
            destination=destination,
            scratch=path,
            settings=PipelineSettings(_env_file=None, spaces_endpoint=ENDPOINT),
            non_transfer_cost_bound_usd=0,
        )
    assert source.gets == 0 and destination.puts == 0
    assert (path / "nlcd-staging.lock").read_text() == "owned-existing-session"
