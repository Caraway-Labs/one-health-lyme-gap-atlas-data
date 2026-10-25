"""Daily CDC admission, disabled execution, immutable versions and existing job reuse."""

import copy
import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from semantic_contracts import latest_daily_activation_sql

from lyme_gap_atlas_data import intelligence_polling as polling
from lyme_gap_atlas_data.ingestion import intelligence_runtime as runtime
from lyme_gap_atlas_data.ingestion.types import RunStatus
from lyme_gap_atlas_data.intelligence_items import identity_hash, validate_record
from lyme_gap_atlas_data.settings import PipelineSettings

ROOT = Path(__file__).parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("sid", runtime.PROD_SOURCE_DEFINITIONS)
def test_daily_version_is_only_explicit_activation_with_existing_rights(sid):
    old = json.loads((ROOT / f"config/intelligence/{sid}-source-v1.json").read_text())
    new = json.loads((ROOT / f"config/intelligence/{sid}-source-v2.json").read_text())
    validate_record("source", new)
    expected = copy.deepcopy(old)
    expected["registry_version"] = 2
    expected["state"] = "active"
    expected["approval"].update(
        decision_ref=runtime.DAILY_DECISION, reviewed_at="2026-10-21T21:16:00Z"
    )
    assert new == expected
    assert identity_hash(old) == runtime.PROD_SOURCE_SHA256[sid]
    assert identity_hash(new) == runtime.PROD_DAILY_SOURCE_SHA256[sid]
    assert script("register_eid_expedited_dev").reviewed_package(sid, 2) == (
        new,
        identity_hash(new),
    )


def daily_settings(monkeypatch, enabled=True):
    value = PipelineSettings(
        topx_env="prod",
        enable_production_execution=True,
        snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        intelligence_daily_enabled=enabled,
    )
    monkeypatch.setattr("lyme_gap_atlas_data.settings.PipelineSettings", lambda: value)


def test_disabled_daily_has_no_composition_claim_or_provider_io(monkeypatch):
    daily_settings(monkeypatch, False)
    monkeypatch.setattr(runtime, "canonical_pilot", lambda *a, **k: pytest.fail("must not compose"))
    assert polling.run_production_daily() == {
        "status": "DISABLED",
        "sources": [],
        "provider_requests": 0,
    }


def composed_sources(monkeypatch, states=None, failed=None):
    claimed = set()
    events = []

    def compose(definition, *, budget_seconds=300):
        sid = definition.source_id
        source = json.loads((ROOT / f"config/intelligence/{sid}-source-v2.json").read_text())
        source["state"] = (states or {}).get(sid, "active")

        def claim(run_id, source_id, sha):
            assert sha == runtime.PROD_DAILY_SOURCE_SHA256[sid] and source_id == sid
            events.append(("claim", sid))
            if run_id in claimed:
                return False
            claimed.add(run_id)
            return True

        def run(definition, *, tier, run_id):
            assert run_id in claimed
            events.append(("run", sid))
            return SimpleNamespace(
                status=RunStatus.FAILED if sid == failed else RunStatus.SUCCEEDED
            )

        definition = SimpleNamespace(extra={"intelligence_registry": source})
        return SimpleNamespace(store=SimpleNamespace(claim_daily_run=claim), run=run), definition

    monkeypatch.setattr(runtime, "canonical_pilot", compose)
    return events


def test_daily_claim_precedes_io_and_failure_does_not_retry_or_block_other_sources(monkeypatch):
    daily_settings(monkeypatch)
    events = composed_sources(monkeypatch, failed="cdc-eid-expedited")
    first = polling.run_production_daily()
    second = polling.run_production_daily()
    assert first["status"] == "FAILED"
    assert [e for e in events if e[0] == "run"] == [
        ("run", s) for s in runtime.PROD_SOURCE_DEFINITIONS
    ]
    assert all(row["outcome"] == "ALREADY_CLAIMED" for row in second["sources"])
    assert len([e for e in events if e[0] == "run"]) == len(runtime.PROD_SOURCE_DEFINITIONS)


@pytest.mark.parametrize("state", ["manual", "paused"])
def test_nonactive_source_suppresses_daily_without_claim_or_capture(monkeypatch, state):
    daily_settings(monkeypatch)
    events = composed_sources(monkeypatch, {s: state for s in runtime.PROD_SOURCE_DEFINITIONS})
    result = polling.run_production_daily()
    assert events == []
    assert all(r["outcome"] == "SCHEDULE_SUPPRESSED" for r in result["sources"])
    assert polling.run_production_daily(preflight_only=True)["status"] == "FAILED"


def test_preflight_requires_active_pins_and_has_no_claim_or_capture(monkeypatch):
    daily_settings(monkeypatch)
    events = composed_sources(monkeypatch)
    assert polling.run_production_daily(preflight_only=True)["status"] == "SUCCEEDED"
    assert events == []


def test_daily_canonical_pilot_uses_per_source_budget_seconds(monkeypatch):
    daily_settings(monkeypatch)
    seen: list[int] = []

    def capture_pilot(definition, *, budget_seconds=300):
        seen.append(budget_seconds)
        sid = definition.source_id
        source = json.loads((ROOT / f"config/intelligence/{sid}-source-v2.json").read_text())

        def run(definition, *, tier, run_id):
            return SimpleNamespace(status=RunStatus.SUCCEEDED)

        return (
            SimpleNamespace(
                store=SimpleNamespace(claim_daily_run=lambda *args: True),
                run=run,
            ),
            SimpleNamespace(extra={"intelligence_registry": source}),
        )

    monkeypatch.setattr(runtime, "canonical_pilot", capture_pilot)
    polling.run_production_daily()
    assert seen == [runtime.DAILY_SOURCE_BUDGET_SECONDS] * len(runtime.PROD_SOURCE_DEFINITIONS)
    # The watchdog must outlive budget expiry so the FAILED terminal write can happen.
    assert runtime.DAILY_SOURCE_WATCHDOG_SECONDS >= (
        runtime.DAILY_SOURCE_BUDGET_SECONDS + runtime.DEADLINE_GRACE_SECONDS
    )


def test_daily_uses_per_source_watchdog_not_pilot_default(monkeypatch):
    daily_settings(monkeypatch)
    seen: list[int] = []

    def capture_watchdog(state, *, seconds: int):
        seen.append(seconds)

        class _Ctx:
            def __enter__(self):
                return None

            def __exit__(self, *args):
                return False

        return _Ctx()

    monkeypatch.setattr(polling, "daily_hard_kill_watchdog", capture_watchdog)
    composed_sources(monkeypatch)
    polling.run_production_daily()
    assert seen == [runtime.DAILY_SOURCE_WATCHDOG_SECONDS] * len(runtime.PROD_SOURCE_DEFINITIONS)
    assert runtime.DAILY_SOURCE_WATCHDOG_SECONDS > 300


def platform_spec(module):
    env = {k: "EV[opaque-existing-reference]" for k in module.KEYS}
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
                    "digest": "sha256:" + "0" * 64,
                },
                "envs": [{"key": k, "value": v} for k, v in env.items()],
            }
            for name in sorted(module.BASE)
        ],
    }


@pytest.mark.parametrize("phase", ["preflight", "activate"])
def test_source_refresh_preserves_all_six_immutable_image_versions(phase, monkeypatch):
    monkeypatch.setenv("NCBI_EMAIL", "daily-contact@example.test")
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    module = script("deploy_intelligence_daily")
    original = platform_spec(module)
    for i, job in enumerate(original["jobs"]):
        job["image"]["digest"] = "sha256:" + str(i) * 64
    snapshot = copy.deepcopy(original)
    rendered = module.render(original, "sha256:" + "a" * 64, phase)
    assert original == snapshot
    assert [j for j in rendered["jobs"] if j["name"] in module.BASE] == snapshot["jobs"]
    assert rendered["jobs"][-1]["image"]["digest"] == "sha256:" + "a" * 64


def test_baseline_alignment_pins_operational_jobs():
    module = script("deploy_intelligence_daily")
    original = platform_spec(module)
    target = "sha256:" + "b" * 64
    aligned = module.with_baseline_digests(original, target)
    assert len(aligned["jobs"]) == len(original["jobs"])
    for job in aligned["jobs"]:
        assert job["image"]["digest"] == target
    assert module.baseline_needs_digest_alignment(original, target)
    assert not module.baseline_needs_digest_alignment(aligned, target)


def test_baseline_alignment_pins_active_daily_job_when_present():
    module = script("deploy_intelligence_daily")
    original = platform_spec(module)
    daily = copy.deepcopy(original["jobs"][0])
    daily["name"] = module.NAME
    daily["image"]["digest"] = "sha256:" + "c" * 64
    original["jobs"].append(daily)
    target = "sha256:" + "b" * 64
    aligned = module.with_baseline_digests(original, target)
    daily_job = next(j for j in aligned["jobs"] if j["name"] == module.NAME)
    assert daily_job["image"]["digest"] == target
    assert module.baseline_needs_digest_alignment(original, target)


def test_refresh_digest_requires_active_daily_job():
    module = script("deploy_intelligence_daily")
    original = platform_spec(module)
    with pytest.raises(PermissionError, match="REFRESH_REQUIRES_ACTIVE_JOB"):
        module.refresh_operational_digests(original, "sha256:" + "b" * 64)


def test_main_aligns_baseline_digest_before_preflight(monkeypatch):
    monkeypatch.setenv("NCBI_EMAIL", "daily-contact@example.test")
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    module = script("deploy_intelligence_daily")
    original = platform_spec(module)
    old_digest = "sha256:" + "0" * 64
    new_digest = "sha256:" + "b" * 64
    for job in original["jobs"]:
        job["image"]["digest"] = old_digest
    app = {"spec": original, "active_deployment": {"id": "dep-1"}}
    calls: list[bool] = []

    def fake_update(spec, *, update_sources):
        calls.append(update_sources)
        if not update_sources:
            app["spec"] = copy.deepcopy(spec)
        else:
            app["spec"] = copy.deepcopy(spec)
        return SimpleNamespace(returncode=0, stderr="", stdout="[]")

    def fake_get(_args):
        return copy.deepcopy(app)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deploy",
            "--phase",
            "preflight",
            "--image-digest",
            new_digest,
            "--credential-placement-approved",
        ],
    )
    monkeypatch.setattr(module, "get", fake_get)
    monkeypatch.setattr(module, "platform_update", fake_update)
    module.main()
    assert calls == [False, True]
    for job in app["spec"]["jobs"]:
        if job["name"] in module.BASE:
            assert job["image"]["digest"] == new_digest


@pytest.mark.parametrize("kind", ["services", "workers", "static_sites", "functions"])
def test_source_refresh_rejects_other_components_before_update(kind):
    module = script("deploy_intelligence_daily")
    original = platform_spec(module)
    original[kind] = [{"name": "unrelated", "github": {"repo": "owner/repo"}}]
    with pytest.raises(PermissionError, match="IMMUTABLE_SOURCES_REQUIRED"):
        module.render(original, "sha256:" + "a" * 64, "preflight")


@pytest.mark.parametrize("kind", ["git", "github", "gitlab", "bitbucket"])
def test_source_refresh_rejects_git_job_even_with_an_image(kind):
    module = script("deploy_intelligence_daily")
    original = platform_spec(module)
    original["jobs"][0][kind] = {"repo": "owner/repo"}
    with pytest.raises(PermissionError, match="IMMUTABLE_SOURCES_REQUIRED"):
        module.render(original, "sha256:" + "a" * 64, "preflight")


@pytest.mark.parametrize(
    "field,value",
    [
        ("tag", "latest"),
        ("deploy_on_push", {"enabled": True}),
        ("digest", ""),
        ("digest", "sha256:invalid"),
        ("registry_type", "GHCR"),
        ("registry", "other"),
        ("repository", "other"),
    ],
)
def test_source_refresh_rejects_mutable_or_unexpected_image_sources(field, value):
    module = script("deploy_intelligence_daily")
    original = platform_spec(module)
    original["jobs"][0]["image"][field] = value
    with pytest.raises(PermissionError, match="IMMUTABLE_SOURCES_REQUIRED"):
        module.render(original, "sha256:" + "a" * 64, "preflight")


def test_daily_platform_render_preserves_six_jobs_and_reuses_only_required_refs(monkeypatch):
    monkeypatch.setenv("NCBI_EMAIL", "daily-contact@example.test")
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    m = script("deploy_intelligence_daily")
    spec = platform_spec(m)
    old = copy.deepcopy(spec)
    pre = m.render(spec, "sha256:" + "a" * 64, "preflight")
    assert spec == old and pre["jobs"][:-1] == old["jobs"]
    assert pre["jobs"][-1]["name"] == m.CHECK and "schedule" not in pre["jobs"][-1]
    active = m.render(pre, "sha256:" + "a" * 64, "activate")
    # DigitalOcean rejects component names longer than 32 characters.
    assert len(m.NAME + "-preflight") > 32
    assert all(1 <= len(j["name"]) <= 32 for s in (pre, active) for j in s["jobs"])
    assert active["jobs"][:-1] == old["jobs"] and active["jobs"][-1]["name"] == m.NAME
    assert active["jobs"][-1]["schedule"] == {"cron": "15 18 * * *", "time_zone": "America/Denver"}
    assert {e["key"] for e in active["jobs"][-1]["envs"]} == m.KEYS | {
        "INTELLIGENCE_DAILY_ENABLED",
        "NCBI_EMAIL",
    }
    email = next(e for e in active["jobs"][-1]["envs"] if e["key"] == "NCBI_EMAIL")
    assert email["scope"] == "RUN_TIME" and email["type"] == "SECRET"
    assert "NCBI_API_KEY" not in {e["key"] for e in active["jobs"][-1]["envs"]}


def test_missing_placement_approval_prevents_any_platform_access(monkeypatch):
    m = script("deploy_intelligence_daily")
    monkeypatch.setattr(
        sys, "argv", ["deploy", "--phase", "preflight", "--image-digest", "sha256:" + "a" * 64]
    )
    monkeypatch.setattr(m, "get", lambda *a: pytest.fail("no platform access before approval"))
    with pytest.raises(PermissionError, match="CREDENTIAL_APPROVAL_REQUIRED"):
        m.main()


@pytest.mark.parametrize(
    ("detail", "category"),
    [
        ("secret env value must not be encrypted", "ENCRYPTED_SECRET_REJECTED"),
        ("should be at most 32 chars long", "COMPONENT_NAME_TOO_LONG"),
        ("unknown provider error", "UNCLASSIFIED"),
    ],
)
def test_platform_error_exposes_only_closed_metadata(detail, category):
    m = script("deploy_intelligence_daily")
    message = m.update_failure(
        "Error: PUT https://api.digitalocean.com/v2/apps/example: 400 "
        '(request "c3041e18-5aa5-4b2c-bbc5-9ef53bc828d0") '
        + detail
        + "\nSNOWFLAKE_PRIVATE_KEY_B64=private-key-secret EV[encrypted-secret]"
    )
    assert message.split(" validation=", 1)[0] == (
        "INTELLIGENCE_DAILY_PLATFORM_UPDATE_FAILED_INSPECT_OUTCOME status=400 "
        "request_id=c3041e18-5aa5-4b2c-bbc5-9ef53bc828d0 category=" + category
    )
    assert "private-key-secret" not in message
    assert "encrypted-secret" not in message
    assert m.update_failure("private-key-secret").split(" validation=", 1)[0] == (
        "INTELLIGENCE_DAILY_PLATFORM_UPDATE_FAILED_INSPECT_OUTCOME "
        "status=UNKNOWN request_id=UNKNOWN category=UNCLASSIFIED"
    )


def test_platform_json_error_stdout_matches_actual_doctl_channel():
    m = script("deploy_intelligence_daily")
    # Actual doctl v1.160.1 local mock response: JSON stdout, empty stderr.
    output = json.dumps(
        {
            "errors": [
                {
                    "detail": "PUT https://api.digitalocean.com/v2/apps/example: 403 "
                    '(request "c3041e18-5aa5-4b2c-bbc5-9ef53bc828d0") not authorized '
                    "SNOWFLAKE_PRIVATE_KEY_B64=private-key-secret EV[encrypted-secret]"
                }
            ]
        }
    )
    assert m.update_failure("", output).split(" validation=", 1)[0] == (
        "INTELLIGENCE_DAILY_PLATFORM_UPDATE_FAILED_INSPECT_OUTCOME status=403 "
        "request_id=c3041e18-5aa5-4b2c-bbc5-9ef53bc828d0 category=AUTHORIZATION_REJECTED"
    )
    for unexpected in ("private-key-secret", "[]", '{"errors":[null,{}, {"detail":123}]}'):
        assert (
            m.update_failure("", unexpected)
            .split(" validation=", 1)[0]
            .endswith("status=UNKNOWN request_id=UNKNOWN category=UNCLASSIFIED")
        )


def activation_connection():
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE INTELLIGENCE_SOURCE_VERSIONS (source_id TEXT,registry_version INTEGER,"
        "registry_sha256 TEXT,registry_document TEXT)"
    )
    con.execute("ATTACH DATABASE ':memory:' AS GOVERNANCE")
    con.execute(
        "CREATE TABLE GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS (source_id TEXT,"
        "registry_version INTEGER,registry_sha256 TEXT,registry_document TEXT)"
    )
    return con


def insert_version(con, sid, version, change=None, sha=None):
    source = json.loads(
        (ROOT / f"config/intelligence/{sid}-source-v{min(version, 2)}.json").read_text()
    )
    source["registry_version"] = version
    if change == "paused":
        source["state"] = "paused"
    if change == "unapproved":
        source["approval"]["status"] = "pending"
    if change == "untrusted":
        source["trust_review"]["status"] = "pending"
    checksum = (
        sha
        or (runtime.PROD_SOURCE_SHA256 if version == 1 else runtime.PROD_DAILY_SOURCE_SHA256)[sid]
    )
    con.execute(
        "INSERT INTO GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS VALUES (?,?,?,?)",
        (sid, version, checksum, json.dumps(source)),
    )


def actual_activation_predicate():
    sql = latest_daily_activation_sql()
    inner = sql.split("    WHERE NOT COALESCE((", 1)[1].split("        ),FALSE)", 1)[0]
    gate = (
        "NOT EXISTS (SELECT 1 FROM GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS newer "
        "WHERE newer.source_id = s.source_id AND newer.registry_version > s.registry_version "
        "AND NOT COALESCE((" + inner + "),FALSE))"
    )
    return re.sub(
        r"(newer|s)\.registry_document:(\w+)(?::(\w+))?::VARCHAR",
        lambda m: (
            f"json_extract({m[1]}.registry_document,'$.{m[2]}" + (f".{m[3]}" if m[3] else "") + "')"
        ),
        gate,
    )


@pytest.mark.parametrize("sid", runtime.PROD_SOURCE_DEFINITIONS)
def test_actual_view_sql_keeps_prior_capture_when_daily_activation_has_no_capture(sid):
    con = activation_connection()
    insert_version(con, sid, 1)
    insert_version(con, sid, 2)
    rows = con.execute(
        "SELECT s.registry_version FROM GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS s "
        "WHERE s.registry_version=1 AND " + actual_activation_predicate()
    ).fetchall()
    assert rows == [(1,)]  # No v2 capture was created; the working v1 entry survives.


@pytest.mark.parametrize(
    "change,version,sha",
    [
        ("paused", 2, None),
        ("unapproved", 2, None),
        ("untrusted", 2, None),
        (None, 3, None),
        (None, 2, "f" * 64),
    ],
)
def test_actual_view_sql_fails_closed_for_unreviewed_or_revoked_transitions(change, version, sha):
    con = activation_connection()
    sid = "cdc-outbreaks"
    insert_version(con, sid, 1)
    insert_version(con, sid, version, change, sha)
    assert (
        con.execute(
            "SELECT s.registry_version FROM GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS s "
            "WHERE s.registry_version=1 AND " + actual_activation_predicate()
        ).fetchall()
        == []
    )


def test_actual_view_window_deduplicates_same_source_item_across_activation_versions():
    sql = latest_daily_activation_sql()
    window = sql.split("QUALIFY ROW_NUMBER() OVER (", 1)[1].split(") = 1;", 1)[0]
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE captures (item_id TEXT,revision_id TEXT,source_id TEXT,"
        "registry_version INTEGER,transport TEXT,retrieved_at INTEGER,capture_id TEXT)"
    )
    con.executemany(
        "INSERT INTO captures VALUES (?,?,?,?,?,?,?)",
        [
            ("item", "rev", "cdc-outbreaks", 1, "rss", 1, "old"),
            ("item", "rev", "cdc-outbreaks", 2, "rss", 2, "new"),
        ],
    )
    assert con.execute(
        "SELECT registry_version FROM (SELECT c.*,ROW_NUMBER() OVER ("
        + window
        + ") AS n FROM captures c) WHERE n=1"
    ).fetchall() == [(2,)]


@pytest.mark.parametrize(
    "existing,guard,insert,expected",
    [(False, 1, 1, True), (True, 1, 1, False), (False, 0, 1, None), (False, 1, 0, None)],
)
def test_daily_claim_transaction_is_durable_or_fails_closed(existing, guard, insert, expected):
    from datetime import UTC, datetime
    from uuid import NAMESPACE_URL, uuid5

    from lyme_gap_atlas_data.ingestion.intelligence_checkpoints import (
        IntelligenceSnowflakeCheckpoints,
    )

    events = []

    class Cursor:
        rowcount = 1

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params=None):
            events.append(sql)
            if "INTELLIGENCE_DAILY_STALE_RUNNING" in sql:
                self.rowcount = 0
            elif sql.startswith("UPDATE"):
                self.rowcount = guard
            elif sql.startswith("INSERT"):
                self.rowcount = insert

        def fetchall(self):
            return [("existing",)] if existing else []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def cursor(self):
            return Cursor()

        def autocommit(self, value):
            events.append(("autocommit", value))

        def commit(self):
            events.append("COMMIT")

        def rollback(self):
            events.append("ROLLBACK")

    store = object.__new__(IntelligenceSnowflakeCheckpoints)
    store.feed_retention = SimpleNamespace(environment="PROD")
    store._connection_factory = Connection
    sid = "cdc-eid-expedited"
    run_id = str(
        uuid5(
            NAMESPACE_URL, f"atlas:intelligence:daily:{sid}:{datetime.now(UTC).date().isoformat()}"
        )
    )
    if expected is None:
        with pytest.raises(PermissionError):
            store.claim_daily_run(run_id, sid, runtime.PROD_DAILY_SOURCE_SHA256[sid])
        assert events[-1] == "ROLLBACK" and "COMMIT" not in events
    else:
        assert store.claim_daily_run(run_id, sid, runtime.PROD_DAILY_SOURCE_SHA256[sid]) is expected
        assert events[-1] == ("COMMIT" if expected else "ROLLBACK")
        assert any(str(e).startswith("INSERT") for e in events) is expected


def test_daily_claim_rejects_unknown_source_before_connection():
    from lyme_gap_atlas_data.ingestion.intelligence_checkpoints import (
        IntelligenceSnowflakeCheckpoints,
    )

    store = object.__new__(IntelligenceSnowflakeCheckpoints)
    store.feed_retention = SimpleNamespace(environment="PROD")
    store._connection_factory = lambda: pytest.fail("unexpected SQL")
    with pytest.raises(PermissionError):
        store.claim_daily_run("unapproved", "other-source", "0" * 64)


def test_production_workflow_boolean_expressions_are_syntactically_balanced():
    import ast

    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/promote-prod.yml").read_text())
    for job in workflow["jobs"].values():
        for node in [job, *job.get("steps", [])]:
            expression = node.get("if", "")
            if expression.startswith("${{"):
                source = expression.removeprefix("${{").removesuffix("}}")
                source = source.replace("&&", "and").replace("||", "or").strip()
                ast.parse(source, mode="eval")
