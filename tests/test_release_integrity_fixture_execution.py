"""Review, immutable artifacts and interrupted install guards; no Snowflake credentials."""

import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

ROOT = Path(__file__).parents[1]


def module(monkeypatch, name):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.mark.parametrize("publication_granted", [None, "reader", "runtime"])
def test_publication_only_privilege_cannot_pass_service_acceptance(
    monkeypatch, publication_granted
):
    matrix = module(monkeypatch, "release_integrity_fixture_matrix")
    fixture = SimpleNamespace(receipt={"cases": []}, save=MagicMock())
    sql, params = "CALL fixture_publish(%s)", ("complete-valid-staged-artifact",)
    calls = []

    def query(session, label, statement, arguments):
        calls.append(session)
        assert (statement, arguments) == (sql, params)
        if session == publication_granted:
            return [("published",)]
        error = RuntimeError("fixture permission denial")
        error.sqlstate = "42501"
        raise error

    fixture.query = query
    sessions = (("reader", "reader"), ("runtime", "runtime"))
    if publication_granted:
        with pytest.raises(AssertionError, match="did not fail closed"):
            matrix.verify_publication_denials(fixture, sessions, sql, params)
    else:
        matrix.verify_publication_denials(fixture, sessions, sql, params)
        assert calls == ["reader", "runtime"]
        assert len(fixture.receipt["cases"]) == 2


def test_publication_validation_error_is_not_permission_evidence(monkeypatch):
    matrix = module(monkeypatch, "release_integrity_fixture_matrix")
    fixture = SimpleNamespace(receipt={"cases": []}, save=MagicMock())
    fixture.query = MagicMock(side_effect=ValueError("input validation failed"))
    with pytest.raises(AssertionError, match="other than access denial"):
        matrix.verify_publication_denials(fixture, (("reader", "reader"),), "CALL valid()", ())
    assert not fixture.receipt["cases"]


@pytest.mark.parametrize("control", [None, [], [("signature", "(VARCHAR,VARCHAR)")]])
def test_hidden_procedure_error_requires_visible_exact_signature_control(monkeypatch, control):
    matrix = module(monkeypatch, "release_integrity_fixture_matrix")
    error = RuntimeError("redacted unknown procedure")
    error.errno = 2141

    def denied():
        raise error

    if control:
        matrix.require_permission_denied(
            denied, "hidden procedure", procedure_control=lambda: control
        )
    else:
        with pytest.raises(AssertionError):
            matrix.require_permission_denied(
                denied,
                "hidden procedure",
                procedure_control=(lambda: control) if control is not None else None,
            )


def test_failed_procedure_positive_control_is_not_access_denial(monkeypatch):
    matrix = module(monkeypatch, "release_integrity_fixture_matrix")
    error = RuntimeError("unknown")
    error.errno = 2141

    def fail():
        raise error

    with pytest.raises(RuntimeError):
        matrix.require_permission_denied(fail, "hidden procedure", procedure_control=fail)


def review_data():
    head = "a" * 40
    pr = {
        "number": 706,
        "head": {"sha": head},
        "user": {"login": "author"},
        "state": "open",
        "draft": True,
        "base": {"ref": "main"},
    }
    reviews = [
        {
            "user": {"login": name, "type": "User"},
            "state": "APPROVED",
            "commit_id": head,
            "author_association": "MEMBER",
            "id": index,
            "submitted_at": "2026-10-18T00:00:00Z",
        }
        for index, name in enumerate(("engineer", "security"))
    ]
    policy = {"engineering": ["engineer"], "security": ["security"]}
    checks = [{"head_sha": head, "name": "checks", "conclusion": "success"}]
    return head, pr, reviews, policy, checks


def test_exact_head_green_source_passes_without_claiming_peer_review(monkeypatch):
    gate = module(monkeypatch, "review_release_integrity_fixture_gate")
    head, pr, _, _, checks = review_data()
    assert gate.validate_source(head, pr, checks) is None


@pytest.mark.parametrize("bad", [None, "checksum", "incomplete"])
def test_corrected_harness_reuses_complete_installation_without_ddl_or_ledger_rewrite(
    monkeypatch, tmp_path, bad
):
    import copy

    fixture, connection, ledger, executed, mutations = fake_install(monkeypatch, tmp_path)
    fixture.install(connection)
    original = copy.deepcopy(fixture.binding)
    original_ledger = copy.deepcopy(ledger)
    current = copy.deepcopy(original)
    current.update(commit="c" * 40, image_digest="sha256:" + "d" * 64)
    runner = module(monkeypatch, "run_release_integrity_fixture")
    monkeypatch.setattr(runner, "SnowflakeSettings", lambda: None)
    resumed = runner.Fixture(current, tmp_path / "recovery.json", installation_binding=original)
    resumed.query = fixture.query
    before = len(mutations)
    if bad == "checksum":
        current["artifacts"][0]["source_sha256"] = "f" * 64
    elif bad == "incomplete":
        ledger.pop()
    if bad:
        with pytest.raises(PermissionError):
            resumed.install(connection)
    else:
        resumed.install(connection)
        assert ledger == original_ledger
        assert resumed.receipt["installation_mode"] == "REUSED_IMMUTABLE_PAIR"
        assert resumed.receipt["installation_binding"] == original
    assert len(executed) == 3
    assert not any(
        sql.startswith(("CREATE", "GRANT", "INSERT", "UPDATE", "DROP"))
        for _, sql, _ in mutations[before:]
    )


@pytest.mark.parametrize("bad", ["ci", "head", "closed"])
def test_source_gate_still_requires_green_exact_source(monkeypatch, bad):
    gate = module(monkeypatch, "review_release_integrity_fixture_gate")
    head, pr, _, _, checks = review_data()
    if bad == "ci":
        checks[0]["conclusion"] = "failure"
    elif bad == "head":
        pr["head"]["sha"] = "b" * 40
    else:
        pr["state"] = "closed"
    with pytest.raises(ValueError):
        gate.validate_source(head, pr, checks)


@pytest.mark.parametrize("state,merged", [("open", False), ("closed", True)])
def test_post_merge_or_ready_source_needs_separate_owner_authorization(monkeypatch, state, merged):
    gate = module(monkeypatch, "review_release_integrity_fixture_gate")
    head, pr, _, _, checks = review_data()
    pr.update(number=707, state=state, merged=merged, draft=False)
    assert gate.validate_source(head, pr, checks) is None


@pytest.mark.parametrize("bad", [None, "head", "fork", "base", "duplicate", "missing"])
def test_review_discovery_binds_unique_same_repository_source(monkeypatch, bad):
    gate = module(monkeypatch, "review_release_integrity_fixture_gate")
    repository = "Caraway-Labs/one-health-lyme-gap-atlas-data"
    pr = {
        "number": 707,
        "head": {"sha": "a" * 40, "repo": {"full_name": repository}},
        "base": {"ref": "main", "repo": {"full_name": repository}},
    }
    candidates = [pr]
    if bad == "head":
        pr["head"]["sha"] = "b" * 40
    elif bad == "fork":
        pr["head"]["repo"]["full_name"] = "other/fork"
    elif bad == "base":
        pr["base"]["ref"] = "other"
    elif bad == "duplicate":
        candidates.append(pr.copy())
    elif bad == "missing":
        candidates.clear()
    if bad:
        with pytest.raises(ValueError, match="UNIQUE_EXACT_SOURCE"):
            gate.select_review_pr("a" * 40, candidates, repository)
    else:
        assert gate.select_review_pr("a" * 40, candidates, repository) == 707


def configure_binding(monkeypatch, tmp_path, runner):
    artifact = [
        {
            "version": m.version,
            "filename": m.filename,
            "source_sha256": m.sha256,
            "rendered_sha256": runner.digest(runner.render_fixture(m)),
        }
        for m in runner.load_migrations()
        if m.version in runner.TARGETS
    ]
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"reviewed_commit": "a" * 40, "scope": runner.MARKER}))
    for name, value in {
        "GITHUB_ACTIONS": "true",
        "RI706_FIXTURE_MODE": "true",
        "GITHUB_REPOSITORY": "Caraway-Labs/one-health-lyme-gap-atlas-data",
        "GITHUB_SHA": "a" * 40,
        "REVIEWED_COMMIT": "a" * 40,
        "RI706_IMAGE_DIGEST": "sha256:" + "b" * 64,
        "RI706_REVIEW_RECEIPT": str(review),
        "RI706_EXPECTED_ARTIFACTS": json.dumps(artifact),
    }.items():
        monkeypatch.setenv(name, value)
    return artifact


@pytest.mark.parametrize("bad", [None, "image", "commit", "artifact", "scope"])
def test_immutable_bindings_are_checked_before_connect(monkeypatch, tmp_path, bad):
    runner = module(monkeypatch, "run_release_integrity_fixture")
    artifacts = configure_binding(monkeypatch, tmp_path, runner)
    if bad == "image":
        monkeypatch.setenv("RI706_IMAGE_DIGEST", "latest")
    elif bad == "commit":
        monkeypatch.setenv("REVIEWED_COMMIT", "c" * 40)
    elif bad == "artifact":
        artifacts[0]["rendered_sha256"] = "d" * 64
        monkeypatch.setenv("RI706_EXPECTED_ARTIFACTS", json.dumps(artifacts))
    elif bad == "scope":
        monkeypatch.setenv("RI706_FIXTURE_MODE", "false")
    if bad:
        with pytest.raises(ValueError):
            runner.binding_from_environment()
    else:
        assert {a["version"] for a in runner.binding_from_environment()["artifacts"]} == {
            "V157",
            "V158",
            "V159",
        }


def fake_install(monkeypatch, tmp_path):
    runner = module(monkeypatch, "run_release_integrity_fixture")
    configure_binding(monkeypatch, tmp_path, runner)
    monkeypatch.setattr(runner, "SnowflakeSettings", lambda: None)
    fixture = runner.Fixture(runner.binding_from_environment(), tmp_path / "receipt.json")
    ledger, executed, mutations = [], [], []
    marker = json.dumps(fixture.binding, sort_keys=True, separators=(",", ":"))

    def query(connection, label, sql, params=(), **kwargs):
        mutations.append((label, sql, params))
        if label == "schema_preflight":
            return [(s, marker, "OH_LYME_DEV_MIGRATION_DEPLOYER") for s in runner.SCHEMAS.values()]
        if label == "fixture_ledger_read":
            return ledger
        if label == "seed_presence":
            return [(1,)]
        if label == "seed_recovery":
            return [(runner.MARKER,)]
        if label.startswith("record_V"):
            ledger.append((params[0], *params[2:]))
        return []

    def stream(source):
        sql = source.read()
        assert "RI706_" in sql
        assert "V155" not in sql
        executed.append(sql)
        return [SimpleNamespace(sfqid="fixture-query")]

    fixture.query = query
    connection = MagicMock()
    connection.execute_stream.side_effect = stream
    return fixture, connection, ledger, executed, mutations


def test_interrupted_pair_resumes_then_replays_without_reexecuting(monkeypatch, tmp_path):
    fixture, connection, ledger, executed, mutations = fake_install(monkeypatch, tmp_path)
    with pytest.raises(InterruptedError):
        fixture.install(connection, stop_after_v157=True)
    assert [row[0] for row in ledger] == ["V157"]
    fixture.install(connection)
    assert [row[0] for row in ledger] == ["V157", "V158", "V159"]
    assert len(executed) == 3
    fixture.install(connection)
    assert len(executed) == 3
    assert all("V155" not in sql for _, sql, _ in mutations)


@pytest.mark.parametrize("field", [1, 2, 3, 4, 5])
def test_recovery_rejects_changed_original_rendered_commit_image_or_marker(
    monkeypatch, tmp_path, field
):
    fixture, connection, ledger, executed, _ = fake_install(monkeypatch, tmp_path)
    fixture.install(connection)
    changed = list(ledger[0])
    changed[field] = "changed"
    ledger[0] = tuple(changed)
    with pytest.raises(PermissionError, match="LEDGER_MISMATCH"):
        fixture.install(connection)
    assert len(executed) == 3


def test_wrong_schema_owner_or_marker_is_preserved(monkeypatch, tmp_path):
    fixture, connection, _, executed, _ = fake_install(monkeypatch, tmp_path)
    fixture.query = lambda *a, **k: [("RI706_GOVERNANCE", "unrelated", "OTHER_OWNER")]
    with pytest.raises(PermissionError, match="SCHEMA_BINDING"):
        fixture.install(connection)
    assert not executed


@pytest.mark.parametrize(
    "sql,live",
    [
        ("UPDATE PRESENTATION.SEMANTIC_RELEASE_POINTER SET current_release_id='x'", True),
        ("DELETE FROM GOVERNANCE.SCHEMA_MIGRATIONS", True),
        ("SELECT 1; DROP TABLE x", True),
        ("SELECT * FROM one_health_lyme_gap_atlas_prod.presentation.x", False),
    ],
)
def test_live_mutations_and_prod_references_never_reach_connector(monkeypatch, tmp_path, sql, live):
    runner = module(monkeypatch, "run_release_integrity_fixture")
    fixture = runner.Fixture.__new__(runner.Fixture)
    fixture.started = time.monotonic()
    connection = MagicMock()
    with pytest.raises(ValueError):
        fixture.query(connection, "forbidden", sql, live=live)
    connection.cursor.assert_not_called()


def test_missing_role_credentials_cannot_fall_back_to_migrator(monkeypatch, tmp_path):
    runner = module(monkeypatch, "run_release_integrity_fixture")
    monkeypatch.setattr(runner, "SnowflakeSettings", lambda: object())
    monkeypatch.delenv("RI706_PUBLISHER_USER", raising=False)
    fixture = runner.Fixture({}, tmp_path / "receipt.json")
    connection = MagicMock()
    monkeypatch.setattr(runner, "connect", connection)
    with pytest.raises(PermissionError, match="PUBLISHER_CREDENTIALS"):
        fixture.open("publisher")
    connection.assert_not_called()


def test_role_profile_uses_its_own_secret_key_and_actual_context(monkeypatch, tmp_path):
    from lyme_gap_atlas_shared.settings import SnowflakeSettings

    runner = module(monkeypatch, "run_release_integrity_fixture")
    settings = SnowflakeSettings(
        _env_file=None,
        snowflake_account="fixture",
        snowflake_user="OH_LYME_DEV_MIGRATION_DEPLOY_SVC",
        snowflake_role="OH_LYME_DEV_MIGRATION_DEPLOYER",
        snowflake_database=runner.DATABASE,
        snowflake_warehouse="OH_LYME_DEV_INGEST_XS_WH",
        snowflake_auth_method="key_pair",
        snowflake_private_key_b64="offline-migration-key",
    )
    monkeypatch.setattr(runner, "SnowflakeSettings", lambda: settings)
    for name, value in {
        "USER": "fixture-publisher",
        "PRIVATE_KEY_B64": "offline-publisher-key",
        "PRIVATE_KEY_PASSPHRASE": "offline-passphrase",
    }.items():
        monkeypatch.setenv("RI706_PUBLISHER_" + name, value)
    connector = MagicMock()
    monkeypatch.setattr(runner, "connect", connector)
    fixture = runner.Fixture({}, tmp_path / "receipt.json")

    def query(connection, label, sql, params=(), **kwargs):
        if label == "context":
            return [
                (
                    "fixture-publisher",
                    "OH_LYME_DEV_ML_PUBLISHER",
                    runner.DATABASE,
                    "OH_LYME_DEV_INGEST_XS_WH",
                )
            ]
        return [(False,) * 5] if label == "forbidden_role_check" else []

    fixture.query = query
    fixture.open("publisher")
    actual = connector.call_args.args[0]
    assert actual.snowflake_private_key_b64.get_secret_value() == "offline-publisher-key"
    assert actual.snowflake_private_key_passphrase.get_secret_value() == "offline-passphrase"
    assert settings.snowflake_private_key_b64.get_secret_value() == "offline-migration-key"


def test_workflow_keeps_generic_migrations_and_app_deployment_out_of_fixture_job():
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-dev.yml").read_text())
    assert "!= true" in workflow["jobs"]["deploy"]["if"]
    job = workflow["jobs"]["release-integrity-fixture"]
    assert job["environment"] == "dev"
    assert job["concurrency"]["cancel-in-progress"] is False
    steps = job["steps"]
    gate_index = next(
        i
        for i, step in enumerate(steps)
        if step.get("run") == "uv run python scripts/review_release_integrity_fixture_gate.py"
    )
    assert gate_index < next(i for i, step in enumerate(steps) if step.get("id") == "fixture_image")
    text = json.dumps(job)
    assert "apply-reviewed-dev-migrations" not in text
    assert "doctl apps" not in text
    assert "--stop-after-v157" in text
    assert "$IMAGE@$RI706_IMAGE_DIGEST" in text
    assert "actions/upload-artifact@v4" in text
    assert (
        "!docs/contracts/semantic-release/release-completeness-2026-10-18.json"
        in (ROOT / ".dockerignore").read_text().splitlines()
    )


def test_latest_pinned_api_readers_are_all_in_the_release_inventory():
    from lyme_gap_atlas_data.release_completeness import VIEWS

    audit = json.loads((ROOT / "docs/operations/ri706-api-consumer-audit.json").read_text())
    assert set(audit["views"]) <= set(VIEWS)
    assert {row["procedure"] for row in audit["independent_operational_controls"]} == set(
        audit["procedures"]
    )


def test_exact_action_diagnostic_request_has_no_base_grant_or_automatic_authorization(monkeypatch):
    builder = module(monkeypatch, "prepare_retained_lineage_authorization")
    request = builder.request()
    retained = json.loads(
        (ROOT / "docs/operations/ri706-retained-lineage-exact-action-request.json").read_text()
    )
    assert retained == request
    assert request["security_review"] is request["exact_action_authorization"] is None
    assert request["base_table_reader_grants"] == request["role_membership_changes"] == []
    assert len(request["new_reader_grants"]) == 4
    assert all(
        g["role"] == "OH_LYME_PROD_READ" and g["privilege"] == "SELECT"
        for g in request["new_reader_grants"]
    )
    sql = (ROOT / request["sql_artifacts"][0]["path"]).read_text()
    assert sql.count("CURRENT_TIMESTAMP()<TO_TIMESTAMP_TZ") == 4
    assert "GRANT SELECT ON TABLE" not in sql


def test_committed_fixture_artifacts_match_original_and_fixed_rendering(monkeypatch):
    import hashlib

    from lyme_gap_atlas_data.migrations import load_migrations

    renderer = module(monkeypatch, "prepare_release_integrity_dev_plan")
    retained = json.loads(
        (ROOT / "docs/operations/ri706-fixture-execution-artifacts.json").read_text()
    )
    actual = [
        {
            "version": migration.version,
            "filename": migration.filename,
            "source_sha256": migration.sha256,
            "rendered_sha256": hashlib.sha256(
                renderer.render_fixture(migration).encode()
            ).hexdigest(),
        }
        for migration in load_migrations()
        if migration.version in {"V157", "V158"}
    ]
    assert retained == actual


@pytest.mark.parametrize("bad", [None, "V157", "V159"])
def test_forward_activation_fix_preserves_pair_and_records_own_provenance(
    monkeypatch, tmp_path, bad
):
    import copy

    fixture, connection, ledger, executed, mutations = fake_install(monkeypatch, tmp_path)
    fixture.install(connection)
    ledger.pop()  # Model the actual retained V157/V158 installation.
    original = copy.deepcopy(fixture.binding)
    original["artifacts"] = original["artifacts"][:2]
    unchanged_pair = copy.deepcopy(ledger)
    current = copy.deepcopy(fixture.binding)
    current.update(commit="c" * 40, image_digest="sha256:" + "d" * 64)
    runner = module(monkeypatch, "run_release_integrity_fixture")
    resumed = runner.Fixture(current, tmp_path / "forward.json", installation_binding=original)
    previous_query = fixture.query

    def query(connection, label, sql, params=(), **kwargs):
        if label == "schema_preflight":
            marker = json.dumps(original, sort_keys=True, separators=(",", ":"))
            return [
                (schema, marker, "OH_LYME_DEV_MIGRATION_DEPLOYER")
                for schema in runner.SCHEMAS.values()
            ]
        return previous_query(connection, label, sql, params, **kwargs)

    resumed.query = query
    before = len(executed)
    resumed.install(connection)
    assert ledger[:2] == unchanged_pair
    assert len(executed) == before + 1
    assert "Snowflake SQL BOOLEAN" in executed[-1]
    assert ledger[-1][0] == "V159"
    assert ledger[-1][3:5] == (current["commit"], current["image_digest"])
    if bad:
        index = 0 if bad == "V157" else 2
        row = list(ledger[index])
        row[4] = "sha256:" + "f" * 64
        ledger[index] = tuple(row)
        with pytest.raises(PermissionError, match="LEDGER_MISMATCH"):
            resumed.install(connection)
    else:
        resumed.install(connection)
        assert len(executed) == before + 1


@pytest.mark.parametrize("changed", [False, True])
def test_retained_pair_proof_accepts_only_identical_prefix_before_forward_fix(monkeypatch, changed):
    proof = module(monkeypatch, "retained_fixture_installation")
    artifacts = [{"version": v, "sha": v} for v in ("V157", "V158", "V159")]
    binding = {
        "commit": "a" * 40,
        "image_digest": "sha256:" + "b" * 64,
        "marker": proof.MARKER,
        "artifacts": artifacts[:2],
    }
    receipt = {"binding": binding, "status": "FAIL", "installation": "PASS", "live_unchanged": True}
    run = {"status": "completed", "conclusion": "failure", "head_sha": "a" * 40}
    if changed:
        artifacts = [{"version": "V157", "sha": "changed"}, *artifacts[1:]]
        with pytest.raises(ValueError, match="IDENTICAL_INSTALLED_PAIR"):
            proof.validate_installation(run, receipt, artifacts)
    else:
        assert proof.validate_installation(run, receipt, artifacts) == binding
