from copy import deepcopy

import pytest

from lyme_gap_atlas_data.cdc_deployment import operating_policy_spec


def test_policy_spec_is_scoped_idempotent_and_omits_unneeded_watchdog_secrets() -> None:
    digest = "sha256:" + "a" * 64
    other = {"name": "catalog-discovery", "schedule": {"cron": "existing"}}
    spec = {
        "name": "oh-lyme-data-prod",
        "vpc": {"id": "existing"},
        "jobs": [
            other,
            {
                "name": "approved-source-ingestion",
                "run_command": "uv run atlas-data pipeline run-production-schedule",
                "image": {"digest": digest},
                "envs": [
                    {"key": "SNOWFLAKE_USER", "value": "encrypted-test"},
                    {"key": "SPACES_ACCESS_KEY_ID", "value": "do-not-copy-test"},
                ],
            },
        ],
    }
    before = deepcopy(spec)
    updated = operating_policy_spec(spec, digest)
    assert spec == before
    assert updated["jobs"][0] == other
    assert updated["vpc"] == spec["vpc"]
    assert updated["jobs"][1]["schedule"]["cron"] == "0 9 1 * *"
    assert updated["jobs"][2]["schedule"]["cron"] == "0 10 * * *"
    assert [env["key"] for env in updated["jobs"][2]["envs"]] == ["SNOWFLAKE_USER"]
    assert operating_policy_spec(updated, digest) == updated


def test_policy_spec_rejects_unverified_digest() -> None:
    with pytest.raises(ValueError, match="immutable digest"):
        operating_policy_spec({"name": "oh-lyme-data-prod"}, "latest")
