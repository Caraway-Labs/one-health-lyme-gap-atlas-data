from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from lyme_gap_atlas_data.settings import PipelineSettings
from lyme_gap_atlas_data.spaces_readiness import BUCKET, ENDPOINT, inspect_spaces, main


@dataclass
class MetadataClient:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def head_bucket(self, **kwargs: Any) -> None:
        self.calls.append(("head_bucket", kwargs))

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list", kwargs))
        return {"Contents": [{"Key": "dev/existing", "Size": 20}], "IsTruncated": True}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("head", kwargs))
        return {"ContentLength": 20, "ETag": "etag"}


def settings(**changes: Any) -> PipelineSettings:
    return PipelineSettings(_env_file=None, spaces_endpoint=ENDPOINT, **changes)


def test_metadata_requests_are_bounded_and_truncation_is_explicit() -> None:
    client = MetadataClient()
    report = inspect_spaces(settings(), client=client, candidate_keys=["dev/existing"])
    assert client.calls == [
        ("head_bucket", {"Bucket": BUCKET}),
        ("list", {"Bucket": BUCKET, "Prefix": "dev/", "MaxKeys": 100}),
        ("head", {"Bucket": BUCKET, "Key": "dev/existing"}),
    ]
    assert report["listing_truncated"] is True
    assert report["metadata_requests"] == 3
    assert report["write_permission"] == "NOT_TESTED"
    assert report["byte_identity"] == "NOT_VERIFIED_BY_METADATA"


@pytest.mark.parametrize(
    "keys",
    [
        ["prod/object"],
        ["dev/../object"],
        ["dev//object"],
        ["dev/a"] * 2,
        [f"dev/{n}" for n in range(17)],
        ["dev/" + "x" * 1024],
    ],
)
def test_invalid_keys_make_no_requests(keys: list[str]) -> None:
    client = MetadataClient()
    with pytest.raises(ValueError):
        inspect_spaces(settings(), client=client, candidate_keys=keys)
    assert not client.calls


@pytest.mark.parametrize(
    "changes",
    [
        {"topx_env": "prod"},
        {"spaces_bucket": "other"},
        {"spaces_prefix": "prod"},
        {"spaces_region": "nyc3"},
    ],
)
def test_wrong_environment_makes_no_requests(changes: dict[str, str]) -> None:
    client = MetadataClient()
    with pytest.raises(ValueError):
        inspect_spaces(settings(**changes), client=client)
    assert not client.calls


def test_provider_failure_is_redacted(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setattr(
        "lyme_gap_atlas_data.spaces_readiness.PipelineSettings",
        lambda: settings(spaces_access_key_id="test", spaces_secret_access_key="test"),
    )

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("sensitive-provider-text")

    monkeypatch.setattr("lyme_gap_atlas_data.spaces_readiness.boto3.client", fail)
    assert main() == 1
    output = capsys.readouterr().out
    assert "BLOCKED" in output
    assert "sensitive-provider-text" not in output


def test_workflow_probe_job_has_no_snowflake_identity_or_ingestion_step() -> None:
    workflow = yaml.safe_load(
        (Path(__file__).parents[1] / ".github/workflows/run-ingestion.yml").read_text()
    )
    job = workflow["jobs"]["spaces_readiness"]
    assert job["environment"] == "dev"
    assert job["timeout-minutes"] == 5
    assert not any("SNOWFLAKE" in name for name in job["env"])
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "refs/heads/main" in commands
    assert 'test "$GITHUB_SHA" = "$REVIEWED_COMMIT"' in commands
    assert "python -m lyme_gap_atlas_data.spaces_readiness" in commands
    assert "source run" not in commands
    assert workflow["jobs"]["ingest"]["if"] == "inputs.operation != 'spaces-readiness'"
