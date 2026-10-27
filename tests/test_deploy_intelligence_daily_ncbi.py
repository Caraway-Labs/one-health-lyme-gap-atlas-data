"""NCBI contact settings on the standing intelligence daily job."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).parents[1]
DIGEST = "sha256:" + "b" * 64
OLD_DIGEST = "sha256:" + "0" * 64
EMAIL = "test-email@example.invalid"
API_KEY = "fake-key-123"
STORED_EMAIL = "stored-contact@example.test"
STORED_KEY = "stored-key-sentinel"


def _module():
    spec = importlib.util.spec_from_file_location(
        "deploy_intelligence_daily_ncbi", ROOT / "scripts" / "deploy_intelligence_daily.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _baseline(module):
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
                "image": {
                    "registry_type": "DOCR",
                    "registry": "oh-lyme-data",
                    "repository": "pipeline",
                    "digest": OLD_DIGEST,
                },
                "envs": [{"key": key, "value": value} for key, value in env.items()],
            }
            for name in sorted(module.BASE)
        ],
    }


def _with_daily(module, spec, envs=None):
    daily = copy.deepcopy(spec["jobs"][0])
    daily["name"] = module.NAME
    daily["run_command"] = module.COMMAND
    daily["schedule"] = dict(module.DAILY_SCHEDULE)
    daily["image"]["digest"] = OLD_DIGEST
    if envs:
        daily["envs"] = [*daily["envs"], *envs]
    spec["jobs"].append(daily)
    return spec


def _secret(key, value):
    return {"key": key, "scope": "RUN_TIME", "type": "SECRET", "value": value}


def _entry(job, key):
    matches = [item for item in job["envs"] if item.get("key") == key]
    assert len(matches) == 1
    return matches[0]


def _clear_ncbi(monkeypatch):
    monkeypatch.delenv("NCBI_EMAIL", raising=False)
    monkeypatch.delenv("NCBI_API_KEY", raising=False)


def _assert_secret(entry, value):
    assert entry == _secret(entry["key"], value)


def _assert_no_secret_text(text):
    for secret in (EMAIL, API_KEY):
        for index in range(len(secret) - 5):
            assert secret[index : index + 6] not in text


def _phase_job(module, spec, phase):
    name = module.CHECK if phase == "preflight" else module.NAME
    return next(job for job in spec["jobs"] if job["name"] == name)


def _run_main(module, monkeypatch, spec, phase):
    app = {
        "spec": copy.deepcopy(spec),
        "active_deployment": {"id": "dep-1"},
        "in_progress_deployment": None,
    }
    calls = []

    def fake_update(updated, *, update_sources):
        calls.append(update_sources)
        app["spec"] = copy.deepcopy(updated)
        return SimpleNamespace(returncode=0, stderr="", stdout="[]")

    def fake_get(args):
        if args[:2] == ["apps", "get-deployment"]:
            deployment = copy.deepcopy(app)
            deployment["phase"] = "ACTIVE"
            deployment["progress"] = {
                "steps": [
                    {
                        "name": "deploy",
                        "steps": [
                            {
                                "name": "components",
                                "steps": [
                                    {
                                        "component_name": module.CHECK,
                                        "status": "SUCCESS",
                                        "steps": [{"status": "SUCCESS"}],
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
            preflight = next(
                job for job in deployment["spec"]["jobs"] if job["name"] == module.CHECK
            )
            preflight["image"]["digest"] = DIGEST
            preflight["run_command"] = module.COMMAND + " --preflight-only"
            return deployment
        return copy.deepcopy(app)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deploy",
            "--phase",
            phase,
            "--image-digest",
            DIGEST,
            "--credential-placement-approved",
        ],
    )
    monkeypatch.setattr(module, "get", fake_get)
    monkeypatch.setattr(module, "platform_update", fake_update)
    module.main()
    return app, calls


def test_email_only_refresh_places_secret_email_and_skips_missing_key(monkeypatch, capsys):
    module = _module()
    _clear_ncbi(monkeypatch)
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    spec = _with_daily(module, _baseline(module))
    before = copy.deepcopy(spec)
    rendered = module.refresh_operational_digests(spec, DIGEST)
    job = _phase_job(module, rendered, "refresh-digest")
    _assert_secret(_entry(job, "NCBI_EMAIL"), EMAIL)
    assert all(item.get("key") != "NCBI_API_KEY" for item in job["envs"])
    app, calls = _run_main(module, monkeypatch, before, "refresh-digest")
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["ncbi_email_present"] is True
    assert summary["ncbi_api_key_present"] is False
    assert calls == [False]
    _assert_no_secret_text(captured.out + captured.err)
    placed = _entry(_phase_job(module, app["spec"], "refresh-digest"), "NCBI_EMAIL")
    assert placed["type"] == "SECRET"


@pytest.mark.parametrize("phase", ["preflight", "activate", "refresh-digest"])
def test_email_and_key_are_runtime_secrets(phase, monkeypatch):
    module = _module()
    _clear_ncbi(monkeypatch)
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    monkeypatch.setenv("NCBI_API_KEY", API_KEY)
    spec = _baseline(module)
    if phase == "refresh-digest":
        spec = _with_daily(module, spec)
        rendered = module.refresh_operational_digests(spec, DIGEST)
    elif phase == "activate":
        spec = module.render(spec, DIGEST, "preflight")
        rendered = module.render(spec, DIGEST, "activate")
    else:
        rendered = module.render(spec, DIGEST, phase)
    job = _phase_job(module, rendered, phase)
    _assert_secret(_entry(job, "NCBI_EMAIL"), EMAIL)
    _assert_secret(_entry(job, "NCBI_API_KEY"), API_KEY)


def test_refresh_keeps_existing_key_and_replaces_email(monkeypatch):
    module = _module()
    _clear_ncbi(monkeypatch)
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    spec = _with_daily(
        module,
        _baseline(module),
        envs=[_secret("NCBI_EMAIL", STORED_EMAIL), _secret("NCBI_API_KEY", STORED_KEY)],
    )
    before_key = _secret("NCBI_API_KEY", STORED_KEY)
    rendered = module.refresh_operational_digests(spec, DIGEST)
    job = _phase_job(module, rendered, "refresh-digest")
    assert _entry(job, "NCBI_API_KEY") == before_key
    _assert_secret(_entry(job, "NCBI_EMAIL"), EMAIL)
    assert STORED_EMAIL not in {item.get("value") for item in job["envs"]}


def test_blank_api_key_is_skipped_and_not_written(monkeypatch):
    module = _module()
    _clear_ncbi(monkeypatch)
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    for blank in ("", "   "):
        monkeypatch.setenv("NCBI_API_KEY", blank)
        spec = _with_daily(module, _baseline(module))
        rendered = module.refresh_operational_digests(spec, DIGEST)
        job = _phase_job(module, rendered, "refresh-digest")
        assert all(item.get("key") != "NCBI_API_KEY" for item in job["envs"])
        assert all(item.get("value") != blank for item in job["envs"])


def test_blank_existing_api_key_is_not_left_on_the_job(monkeypatch):
    module = _module()
    _clear_ncbi(monkeypatch)
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    spec = _with_daily(
        module,
        _baseline(module),
        envs=[_secret("NCBI_API_KEY", "   ")],
    )
    rendered = module.refresh_operational_digests(spec, DIGEST)
    job = _phase_job(module, rendered, "refresh-digest")
    assert all(item.get("key") != "NCBI_API_KEY" for item in job["envs"])


@pytest.mark.parametrize("phase", ["preflight", "activate", "refresh-digest"])
@pytest.mark.parametrize("email", [None, "", "   "])
def test_missing_or_blank_email_stops_before_platform_update(phase, email, monkeypatch, capsys):
    module = _module()
    _clear_ncbi(monkeypatch)
    if email is not None:
        monkeypatch.setenv("NCBI_EMAIL", email)
    if phase == "refresh-digest":
        with pytest.raises(PermissionError, match=module.NCBI_EMAIL_REQUIRED):
            module.refresh_operational_digests(_with_daily(module, _baseline(module)), DIGEST)
    elif phase == "preflight":
        with pytest.raises(PermissionError, match=module.NCBI_EMAIL_REQUIRED):
            module.render(_baseline(module), DIGEST, "preflight")
    else:
        monkeypatch.setenv("NCBI_EMAIL", EMAIL)
        prepared = module.render(_baseline(module), DIGEST, "preflight")
        _clear_ncbi(monkeypatch)
        if email is not None:
            monkeypatch.setenv("NCBI_EMAIL", email)
        with pytest.raises(PermissionError, match=module.NCBI_EMAIL_REQUIRED):
            module.render(prepared, DIGEST, "activate")

    def fail_update(*_args, **_kwargs):
        raise AssertionError("platform update")

    def fake_get(*_args, **_kwargs):
        if phase != "refresh-digest":
            raise AssertionError("platform read")
        return {
            "spec": _with_daily(module, _baseline(module)),
            "active_deployment": {"id": "dep-1"},
            "in_progress_deployment": None,
        }

    monkeypatch.setattr(module, "platform_update", fail_update)
    monkeypatch.setattr(module, "get", fake_get)
    monkeypatch.setattr(
        sys,
        "argv",
        ["deploy", "--phase", phase, "--image-digest", DIGEST, "--credential-placement-approved"],
    )
    with pytest.raises(PermissionError, match=module.NCBI_EMAIL_REQUIRED) as error:
        module.main()
    captured = capsys.readouterr()
    combined = captured.out + captured.err + str(error.value)
    _assert_no_secret_text(combined)
    assert EMAIL not in combined
    assert API_KEY not in combined


def test_refresh_is_a_no_op_when_only_the_encrypted_email_differs(monkeypatch):
    module = _module()
    _clear_ncbi(monkeypatch)
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    spec = _with_daily(
        module,
        _baseline(module),
        envs=[_secret("NCBI_EMAIL", "EV[provider-encrypted]")],
    )
    for job in spec["jobs"]:
        job["image"]["digest"] = DIGEST
    # The standing job already carries the reviewed size and timeout after its first refresh.
    spec["jobs"][-1]["instance_size_slug"] = module.DAILY_JOB_INSTANCE_SIZE_SLUG
    spec["jobs"][-1]["timeout"] = module.DAILY_JOB_TIMEOUT
    before = copy.deepcopy(spec)
    rendered = module.refresh_operational_digests(spec, DIGEST)
    assert rendered == before
    assert spec == before

    calls = []
    monkeypatch.setattr(
        module,
        "platform_update",
        lambda *_args, **_kwargs: calls.append(True) or pytest.fail("platform update"),
    )
    monkeypatch.setattr(
        module,
        "get",
        lambda *_args, **_kwargs: {
            "spec": spec,
            "active_deployment": {"id": "dep-1"},
            "in_progress_deployment": None,
        },
    )
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
    module.main()
    assert calls == []


def test_digest_change_still_places_plaintext_over_encrypted_email(monkeypatch):
    module = _module()
    _clear_ncbi(monkeypatch)
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    spec = _with_daily(
        module,
        _baseline(module),
        envs=[_secret("NCBI_EMAIL", "EV[provider-encrypted]")],
    )
    rendered = module.refresh_operational_digests(spec, DIGEST)
    job = _phase_job(module, rendered, "refresh-digest")
    _assert_secret(_entry(job, "NCBI_EMAIL"), EMAIL)
    assert job["image"]["digest"] == DIGEST


def test_refresh_summary_presence_comes_from_readback(monkeypatch, capsys):
    module = _module()
    _clear_ncbi(monkeypatch)
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    monkeypatch.setenv("NCBI_API_KEY", API_KEY)
    spec = _with_daily(module, _baseline(module))
    state = {"spec": spec}

    def fake_update(updated, *, update_sources):
        readback = copy.deepcopy(updated)
        for job in readback["jobs"]:
            if job.get("name") != module.NAME:
                continue
            job["envs"] = [entry for entry in job["envs"] if entry.get("key") != "NCBI_API_KEY"]
            for entry in job["envs"]:
                if entry.get("key") == "NCBI_EMAIL":
                    entry["value"] = "EV[provider-encrypted]"
        state["spec"] = readback
        return SimpleNamespace(returncode=0, stderr="", stdout="[]")

    monkeypatch.setattr(module, "platform_update", fake_update)
    monkeypatch.setattr(
        module,
        "get",
        lambda *_args, **_kwargs: {
            "spec": copy.deepcopy(state["spec"]),
            "active_deployment": {"id": "dep-1"},
            "in_progress_deployment": None,
        },
    )
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
    module.main()
    summary = json.loads(capsys.readouterr().out)
    assert summary["ncbi_email_present"] is True
    assert summary["ncbi_api_key_present"] is False


def test_refresh_keeps_stored_email_when_process_env_has_none(monkeypatch):
    module = _module()
    _clear_ncbi(monkeypatch)
    stored = _secret("NCBI_EMAIL", STORED_EMAIL)
    spec = _with_daily(module, _baseline(module), envs=[stored])
    rendered = module.refresh_operational_digests(spec, DIGEST)
    job = _phase_job(module, rendered, "refresh-digest")
    assert _entry(job, "NCBI_EMAIL") == stored


def test_no_ncbi_value_or_fragment_is_printed(monkeypatch, capsys):
    module = _module()
    _clear_ncbi(monkeypatch)
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    monkeypatch.setenv("NCBI_API_KEY", API_KEY)
    spec = _with_daily(module, _baseline(module))
    module.refresh_operational_digests(spec, DIGEST)
    module.render(_baseline(module), DIGEST, "preflight")
    prepared = module.render(_baseline(module), DIGEST, "preflight")
    _run_main(module, monkeypatch, _with_daily(module, _baseline(module)), "refresh-digest")
    _run_main(module, monkeypatch, _baseline(module), "preflight")
    _run_main(module, monkeypatch, prepared, "activate")
    captured = capsys.readouterr()
    _assert_no_secret_text(captured.out + captured.err)


def test_provider_error_does_not_echo_ncbi_values(monkeypatch, capsys):
    module = _module()
    _clear_ncbi(monkeypatch)
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    monkeypatch.setenv("NCBI_API_KEY", API_KEY)
    spec = _with_daily(module, _baseline(module))

    def fake_update(updated, *, update_sources):
        echoed = json.dumps(updated)
        return SimpleNamespace(returncode=1, stderr=echoed, stdout="")

    monkeypatch.setattr(module, "platform_update", fake_update)
    monkeypatch.setattr(
        module,
        "get",
        lambda *_args, **_kwargs: {
            "spec": spec,
            "active_deployment": {"id": "dep-1"},
            "in_progress_deployment": None,
        },
    )
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
    with pytest.raises(RuntimeError) as error:
        module.main()
    captured = capsys.readouterr()
    _assert_no_secret_text(captured.out + captured.err + str(error.value))


def test_other_jobs_keep_envs_and_only_digests_change(monkeypatch):
    module = _module()
    _clear_ncbi(monkeypatch)
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    spec = _with_daily(module, _baseline(module))
    spec["jobs"][0]["envs"].append({"key": "UNRELATED_MARKER", "value": "keep-me"})
    before = {job["name"]: copy.deepcopy(job) for job in spec["jobs"]}
    rendered = module.refresh_operational_digests(spec, DIGEST)
    for job in rendered["jobs"]:
        if job["name"] == module.NAME:
            assert job["image"]["digest"] == DIGEST
            continue
        previous = before[job["name"]]
        assert job["envs"] == previous["envs"]
        assert job["image"]["digest"] == DIGEST
        previous["image"]["digest"] = DIGEST
        assert job == previous


def test_argv_cannot_supply_ncbi_values(monkeypatch, capsys):
    module = _module()
    _clear_ncbi(monkeypatch)
    monkeypatch.setattr(module, "platform_update", lambda *_a, **_k: pytest.fail("update"))
    monkeypatch.setattr(module, "get", lambda *_a, **_k: pytest.fail("read"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deploy",
            "--phase",
            "preflight",
            "--image-digest",
            DIGEST,
            "--credential-placement-approved",
            "--ncbi-email",
            EMAIL,
            API_KEY,
        ],
    )
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2
    captured = capsys.readouterr()
    _assert_no_secret_text(captured.out + captured.err)


def test_encrypted_readback_matches_without_requiring_the_plaintext(monkeypatch):
    module = _module()
    _clear_ncbi(monkeypatch)
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    app = {
        "spec": _baseline(module),
        "active_deployment": {"id": "dep-1"},
        "in_progress_deployment": None,
    }

    def fake_update(updated, *, update_sources):
        stored = copy.deepcopy(updated)
        for job in stored["jobs"]:
            for entry in job.get("envs", []):
                if (
                    entry.get("key") in module.NCBI_PLACEMENT_ALLOWLIST
                    and entry.get("type") == "SECRET"
                ):
                    entry["value"] = "EV[provider-encrypted]"
        app["spec"] = stored
        return SimpleNamespace(returncode=0, stderr="", stdout="[]")

    monkeypatch.setattr(module, "platform_update", fake_update)
    monkeypatch.setattr(module, "get", lambda *_args, **_kwargs: copy.deepcopy(app))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deploy",
            "--phase",
            "preflight",
            "--image-digest",
            DIGEST,
            "--credential-placement-approved",
        ],
    )
    module.main()
    job = _phase_job(module, app["spec"], "preflight")
    assert _entry(job, "NCBI_EMAIL")["value"] == "EV[provider-encrypted]"
    assert module.ncbi_presence(app["spec"])["ncbi_email_present"] is True
    assert module.ncbi_presence(app["spec"])["ncbi_api_key_present"] is False


def test_workflow_passes_ncbi_secrets_only_to_daily_deploy_steps():
    workflow = yaml.safe_load((ROOT / ".github/workflows/promote-prod.yml").read_text())
    expected_steps = {
        "Refresh only the immutable digest across all operational PROD jobs",
        "Deploy explicitly approved credential-scoped preflight (no source acquisition)",
        "Enable only the daily job after successful service preflight",
    }
    found = []
    for job_name, job in workflow["jobs"].items():
        job_env = job.get("env") or {}
        assert "NCBI_EMAIL" not in job_env
        assert "NCBI_API_KEY" not in job_env
        for step in job.get("steps") or []:
            env = step.get("env") or {}
            if "NCBI_EMAIL" in env or "NCBI_API_KEY" in env:
                found.append((job_name, step.get("name"), env))
    assert {(job_name, step_name) for job_name, step_name, _env in found} == {
        ("intelligence-daily", step_name) for step_name in expected_steps
    }
    for _job_name, _step_name, env in found:
        assert env["NCBI_EMAIL"] == "${{ secrets.NCBI_EMAIL }}"
        assert env["NCBI_API_KEY"] == "${{ secrets.NCBI_API_KEY }}"
        assert "NCBI" not in step_text(workflow, _step_name)
    raw = (ROOT / ".github/workflows/promote-prod.yml").read_text()
    assert raw.count("secrets.NCBI_EMAIL") == 3
    assert raw.count("secrets.NCBI_API_KEY") == 3
    daily = workflow["jobs"]["intelligence-daily"]
    assert not any("NCBI_API_KEY" in (step.get("run") or "") for step in daily["steps"])


def test_activate_copies_sibling_otel_and_does_not_print_it(monkeypatch, capsys):
    module = _module()
    _clear_ncbi(monkeypatch)
    monkeypatch.setenv("NCBI_EMAIL", EMAIL)
    spec = _baseline(module)
    registration = next(job for job in spec["jobs"] if job["name"] == "catalog-registration-01")
    registration["envs"] = [
        *registration["envs"],
        {
            "key": "OTEL_EXPORTER_OTLP_ENDPOINT",
            "scope": "RUN_TIME",
            "value": "https://otel.example.invalid/v1/traces",
        },
        {
            "key": "OTEL_EXPORTER_OTLP_HEADERS",
            "scope": "RUN_TIME",
            "type": "SECRET",
            "value": "DUMMY_OPAQUE_HEADER_SENTINEL",
        },
    ]
    rendered = module.render(spec, DIGEST, "activate")
    job = _phase_job(module, rendered, "activate")
    assert _entry(job, "OTEL_EXPORTER_OTLP_ENDPOINT")["value"].endswith("/v1/traces")
    assert _entry(job, "OTEL_EXPORTER_OTLP_HEADERS")["value"] == "DUMMY_OPAQUE_HEADER_SENTINEL"
    captured = capsys.readouterr()
    assert "DUMMY_OPAQUE_HEADER_SENTINEL" not in captured.out + captured.err
    without = module.render(_baseline(module), DIGEST, "activate")
    plain = _phase_job(module, without, "activate")
    assert all(entry.get("key") not in module.OTEL_ENV_KEYS for entry in plain["envs"])


def step_text(workflow, step_name):
    for job in workflow["jobs"].values():
        for step in job.get("steps") or []:
            if step.get("name") == step_name:
                return step.get("run") or ""
    return ""
