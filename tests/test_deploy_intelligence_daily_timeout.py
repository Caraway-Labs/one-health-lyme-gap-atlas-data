"""The standing daily job may run for 1h30m; every other job keeps its timeout."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
OLD_DIGEST = "sha256:" + "0" * 64
DIGEST = "sha256:" + "b" * 64
SMALL = "apps-s-1vcpu-0.5gb"
EMAIL = "timeout-contact@example.invalid"


def _module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "deploy_intelligence_daily_timeout", ROOT / "scripts" / "deploy_intelligence_daily.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _image(digest: str) -> dict[str, str]:
    return {
        "registry_type": "DOCR",
        "registry": "oh-lyme-data",
        "repository": "pipeline",
        "digest": digest,
    }


def _baseline(module: Any) -> dict[str, Any]:
    env = {key: "EV[opaque-existing-reference]" for key in module.KEYS}
    env.update(
        TOPX_ENV="prod",
        ENABLE_PRODUCTION_EXECUTION="true",
        SNOWFLAKE_ROLE="OH_LYME_PROD_RUNTIME",
        SNOWFLAKE_DATABASE="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        SNOWFLAKE_WAREHOUSE="OH_LYME_PROD_INGEST_XS_WH",
        SNOWFLAKE_AUTH_METHOD="key_pair",
    )
    return {
        "name": "oh-lyme-data-prod",
        "jobs": [
            {
                "name": name,
                "kind": "SCHEDULED",
                "run_command": "existing-" + name,
                "schedule": {"cron": "0 9 1 * *", "time_zone": "America/Denver"},
                "image": _image(OLD_DIGEST),
                "instance_count": 1,
                "instance_size_slug": SMALL,
                "envs": [{"key": k, "value": v} for k, v in sorted(env.items())],
            }
            for name in sorted(module.BASE)
        ],
    }


def _live_spec(module: Any) -> dict[str, Any]:
    """Today's PROD shape: the standing daily job has no timeout, so DO uses 30 minutes."""
    spec = _baseline(module)
    daily = copy.deepcopy(next(j for j in spec["jobs"] if j["name"] == "approved-source-ingestion"))
    daily.update(name=module.NAME, run_command=module.COMMAND, schedule=dict(module.DAILY_SCHEDULE))
    daily["envs"] = [
        *daily["envs"],
        {"key": "NCBI_EMAIL", "scope": "RUN_TIME", "type": "SECRET", "value": "EV[stored]"},
    ]
    spec["jobs"].append(daily)
    return spec


def test_constant_is_the_documented_duration_string() -> None:
    assert _module().DAILY_JOB_TIMEOUT == "1h30m"


def test_activate_sets_timeout_only_on_the_daily_job(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    module = _module()
    spec = _baseline(module)
    snapshot = copy.deepcopy(spec)
    pre = module.render(spec, DIGEST, "preflight")
    active = module.render(pre, DIGEST, "activate")
    daily = next(job for job in active["jobs"] if job["name"] == module.NAME)
    assert daily["timeout"] == "1h30m"
    assert daily["instance_size_slug"] == "apps-s-1vcpu-1gb"
    assert daily["schedule"] == {"cron": "15 18 * * *", "time_zone": "America/Denver"}
    assert "termination" not in daily
    check = next(job for job in pre["jobs"] if job["name"] == module.CHECK)
    assert "timeout" not in check
    assert "termination" not in check
    others = [job for job in active["jobs"] if job["name"] != module.NAME]
    assert others == snapshot["jobs"]
    assert all("timeout" not in job for job in others)
    assert spec == snapshot


def test_sync_daily_job_timeout_changes_only_that_field_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    module = _module()
    live = _live_spec(module)
    before = copy.deepcopy(live)
    once = module.sync_daily_job_timeout(live)
    assert live == before
    expected = copy.deepcopy(before)
    for job in expected["jobs"]:
        if job["name"] == module.NAME:
            job["timeout"] = "1h30m"
    assert once == expected
    assert module.sync_daily_job_timeout(once) == once
    assert module.other_job_timeouts(once) == module.other_job_timeouts(before)


def _run_refresh_main(
    module: Any,
    monkeypatch: pytest.MonkeyPatch,
    spec: dict[str, Any],
    mutate: Any = None,
) -> dict[str, Any]:
    app = {"spec": copy.deepcopy(spec), "active_deployment": {"id": "dep-1"}}
    updates: list[dict[str, Any]] = []

    def fake_update(updated: dict[str, Any], *, update_sources: bool) -> SimpleNamespace:
        assert update_sources is False
        installed = copy.deepcopy(updated)
        if mutate:
            mutate(installed)
        updates.append(copy.deepcopy(updated))
        app["spec"] = installed
        return SimpleNamespace(returncode=0, stderr="", stdout="[]")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deploy",
            "--phase",
            "refresh-digest",
            "--image-digest",
            DIGEST,
            "--credential-placement-approved",
        ],
    )
    monkeypatch.setattr(module, "get", lambda _args: copy.deepcopy(app))
    monkeypatch.setattr(module, "platform_update", fake_update)
    module.main()
    return {"app": app, "updates": updates}


def test_daily_only_promote_writes_the_timeout_and_proves_readback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    module = _module()
    live = _live_spec(module)
    result = _run_refresh_main(module, monkeypatch, live)
    assert len(result["updates"]) == 1
    submitted = result["updates"][0]
    expected = copy.deepcopy(live)
    for job in expected["jobs"]:
        job["image"]["digest"] = DIGEST
        if job["name"] == module.NAME:
            job["instance_size_slug"] = module.DAILY_JOB_INSTANCE_SIZE_SLUG
            job["timeout"] = "1h30m"

    # NCBI placement may add the process email. Compare timeout and untouched fields
    # after removing contact entries that the refresh is allowed to place.
    def _strip_ncbi(spec: dict[str, Any]) -> dict[str, Any]:
        cleaned = copy.deepcopy(spec)
        for job in cleaned["jobs"]:
            job["envs"] = [
                entry
                for entry in job.get("envs", [])
                if entry.get("key") not in module.NCBI_PLACEMENT_ALLOWLIST
            ]
        return cleaned

    assert _strip_ncbi(submitted) == _strip_ncbi(expected)
    assert module.daily_job_timeout(result["app"]["spec"]) == "1h30m"
    assert module.other_job_timeouts(result["app"]["spec"]) == module.other_job_timeouts(live)
    assert '"daily_job_timeout": "1h30m"' in capsys.readouterr().out


@pytest.mark.parametrize(
    "installed",
    [
        None,
        "30m",
        "90m",
        "1h",
    ],
)
def test_refresh_main_fails_when_the_live_timeout_is_missing_or_different(
    monkeypatch: pytest.MonkeyPatch, installed: str | None
) -> None:
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    module = _module()

    def revert(spec: dict[str, Any]) -> None:
        for job in spec["jobs"]:
            if job["name"] == module.NAME:
                if installed is None:
                    job.pop("timeout", None)
                else:
                    job["timeout"] = installed

    with pytest.raises(PermissionError, match="POST_DEPLOY_TIMEOUT_MISMATCH"):
        _run_refresh_main(module, monkeypatch, _live_spec(module), mutate=revert)
