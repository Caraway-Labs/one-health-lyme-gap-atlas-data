"""The standing daily job runs on 1 GB; every other job keeps its size (#862)."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path
from runpy import run_path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
OLD_DIGEST = "sha256:" + "0" * 64
DIGEST = "sha256:" + "b" * 64
SMALL = "apps-s-1vcpu-0.5gb"
EMAIL = "size-contact@example.invalid"


def _module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "deploy_intelligence_daily_size", ROOT / "scripts" / "deploy_intelligence_daily.py"
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
    """Today's PROD shape: the standing daily job inherited the template's 512 MB size."""
    spec = _baseline(module)
    daily = copy.deepcopy(next(j for j in spec["jobs"] if j["name"] == "approved-source-ingestion"))
    daily.update(name=module.NAME, run_command=module.COMMAND, schedule=dict(module.DAILY_SCHEDULE))
    daily["envs"] = [
        *daily["envs"],
        {"key": "NCBI_EMAIL", "scope": "RUN_TIME", "type": "SECRET", "value": "EV[stored]"},
    ]
    spec["jobs"].append(daily)
    return spec


def _others(spec: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [job for job in spec["jobs"] if job["name"] != name]


def test_constant_is_the_approved_one_gigabyte_slug() -> None:
    assert _module().DAILY_JOB_INSTANCE_SIZE_SLUG == "apps-s-1vcpu-1gb"


def test_activate_sets_one_gigabyte_only_on_the_daily_job(monkeypatch) -> None:
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    module = _module()
    spec = _baseline(module)
    snapshot = copy.deepcopy(spec)
    pre = module.render(spec, DIGEST, "preflight")
    active = module.render(pre, DIGEST, "activate")
    daily = next(job for job in active["jobs"] if job["name"] == module.NAME)
    # (a) the activate-phase daily job runs on 1 GB.
    assert daily["instance_size_slug"] == "apps-s-1vcpu-1gb"
    # (b) every other job is identical to the input spec, size included.
    assert _others(active, module.NAME) == snapshot["jobs"]
    assert all(job["instance_size_slug"] == SMALL for job in _others(active, module.NAME))
    # The short-lived preflight component keeps the inherited size.
    check = next(job for job in pre["jobs"] if job["name"] == module.CHECK)
    assert check["instance_size_slug"] == SMALL
    assert spec == snapshot


def test_refresh_digest_raises_only_the_daily_job_to_one_gigabyte(monkeypatch) -> None:
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    module = _module()
    live = _live_spec(module)
    snapshot = copy.deepcopy(live)
    refreshed = module.refresh_operational_digests(live, DIGEST)
    assert live == snapshot
    assert module.daily_job_size(refreshed) == "apps-s-1vcpu-1gb"
    before_others = _others(snapshot, module.NAME)
    after_others = _others(refreshed, module.NAME)
    assert [j["name"] for j in after_others] == [j["name"] for j in before_others]
    for old, new in zip(before_others, after_others, strict=True):
        # Only the image digest may change on other jobs; size and the rest stay identical.
        assert {**old, "image": None} == {**new, "image": None}
        assert new["instance_size_slug"] == SMALL
    assert module.other_job_sizes(refreshed) == module.other_job_sizes(snapshot)


def test_refresh_digest_is_idempotent_once_the_daily_job_is_sized(monkeypatch) -> None:
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    module = _module()
    once = module.refresh_operational_digests(_live_spec(module), DIGEST)
    assert module.refresh_operational_digests(once, DIGEST) == once


def test_refresh_digest_rejects_a_size_change_on_any_other_job(monkeypatch) -> None:
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    module = _module()
    original_sync = module.sync_daily_job_size

    def resize_everything(spec: dict[str, Any]) -> dict[str, Any]:
        result = original_sync(spec)
        for job in result["jobs"]:
            job["instance_size_slug"] = module.DAILY_JOB_INSTANCE_SIZE_SLUG
        return result

    monkeypatch.setattr(module, "sync_daily_job_size", resize_everything)
    with pytest.raises(PermissionError, match="OTHER_JOB_SIZE_CHANGED"):
        module.refresh_operational_digests(_live_spec(module), DIGEST)


def _run_refresh_main(module: Any, monkeypatch, spec: dict[str, Any], mutate=None) -> dict:
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


def test_daily_only_promote_path_writes_one_gigabyte_and_proves_readback(
    monkeypatch, capsys
) -> None:
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    module = _module()
    live = _live_spec(module)
    result = _run_refresh_main(module, monkeypatch, live)
    assert len(result["updates"]) == 1
    assert module.daily_job_size(result["app"]["spec"]) == "apps-s-1vcpu-1gb"
    assert module.other_job_sizes(result["app"]["spec"]) == module.other_job_sizes(live)
    assert '"daily_instance_size_slug": "apps-s-1vcpu-1gb"' in capsys.readouterr().out


def test_refresh_main_fails_when_the_platform_does_not_keep_the_size(monkeypatch) -> None:
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    module = _module()

    def revert(spec: dict[str, Any]) -> None:
        for job in spec["jobs"]:
            if job["name"] == module.NAME:
                job["instance_size_slug"] = SMALL

    with pytest.raises(PermissionError, match="POST_DEPLOY_SIZE_MISMATCH"):
        _run_refresh_main(module, monkeypatch, _live_spec(module), mutate=revert)


def test_refresh_main_fails_when_another_job_size_changes(monkeypatch) -> None:
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    module = _module()

    def resize_other(spec: dict[str, Any]) -> None:
        spec["jobs"][0]["instance_size_slug"] = "apps-s-1vcpu-2gb"

    with pytest.raises(PermissionError, match="OTHER_JOB_SIZE_CHANGED"):
        _run_refresh_main(module, monkeypatch, _live_spec(module), mutate=resize_other)


def test_manual_once_job_inherits_the_daily_job_size_from_baseline(monkeypatch) -> None:
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    once = run_path(str(ROOT / "scripts" / "prod_intelligence_daily_job_spec.py"))
    module = _module()
    baseline = module.refresh_operational_digests(_live_spec(module), DIGEST)
    built = once["build_operation_spec"](baseline, preflight_only=False)
    manual = next(job for job in built["jobs"] if job["name"] == once["MANUAL_JOB"])
    # (c) the bounded run-once job copies the live daily job, so it runs on 1 GB too.
    assert manual["instance_size_slug"] == "apps-s-1vcpu-1gb"
    assert manual["kind"] == "PRE_DEPLOY"
    for job in built["jobs"]:
        if job["name"] in module.BASE:
            assert job["instance_size_slug"] == SMALL
