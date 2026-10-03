from __future__ import annotations

import io
from typing import Any

import pytest
from botocore.exceptions import ClientError

from lyme_gap_atlas_data.settings import PipelineSettings
from lyme_gap_atlas_data.spaces_conditional_canary import verify_conditional_create
from lyme_gap_atlas_data.spaces_readiness import ENDPOINT


class Canary:
    def __init__(self, honor: bool) -> None:
        self.honor = honor
        self.objects: dict[str, bytes] = {}
        self.calls = 0

    def head_object(self, **kwargs: Any) -> None:
        self.calls += 1
        raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    def put_object(self, **kwargs: Any) -> None:
        self.calls += 1
        assert kwargs["ACL"] == "private"
        assert kwargs["Key"].startswith("dev/staging-canary/")
        if self.honor and kwargs.get("IfNoneMatch") == "*":
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        return {"Body": io.BytesIO(self.objects[kwargs["Key"]])}


@pytest.mark.parametrize("honor", [True, False])
def test_canary_proves_response_and_bytes_without_deletes(honor: bool) -> None:
    client = Canary(honor)
    report = verify_conditional_create(
        PipelineSettings(_env_file=None, spaces_endpoint=ENDPOINT), client=client
    )
    assert (report["status"] == "CONDITIONAL_CREATE_VERIFIED") is honor
    assert report["original_preserved"] is honor
    assert client.calls == 5 and len(client.objects) == 2
