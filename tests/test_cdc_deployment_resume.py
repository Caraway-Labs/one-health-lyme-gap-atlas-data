"""Exercise the protected entrypoint and real migration driver with an offline ledger."""

import importlib.util
import json
from contextlib import nullcontext
from pathlib import Path

import pytest

from lyme_gap_atlas_data import migrations
from lyme_gap_atlas_data.cdc_consumer_admission import TARGET_BUNDLE_SHA256, TARGET_RELEASE_ID

SPEC = importlib.util.spec_from_file_location(
    "apply_cdc_admission_migration", Path("scripts/apply_cdc_admission_migration.py")
)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
COMMIT = "a" * 40
OWNER = "OH_LYME_PROD_MIGRATION_DEPLOYER"


class Ledger:
    def __init__(self):
        self.plan = [
            m for m in migrations.load_migrations() if m.version in {"V149", "V150", "V155", "V156"}
        ]
        self.applied = {
            m.version: (m.filename, m.sha256, COMMIT)
            for m in self.plan
            if m.version in {"V149", "V155"}
        }
        self.statements = []
        self.ddl = []
        self.pointer = [(TARGET_RELEASE_ID, TARGET_BUNDLE_SHA256)]
        self.grant_drift = False
        self.missing_reader = False
        self.duplicate = False

    def cursor(self):
        return nullcontext(Cursor(self))

    def execute_string(self, sql):
        self.ddl.append(sql)

    def commit(self):
        pass


class Cursor:
    def __init__(self, db):
        self.db = db
        self.description = []
        self.rows = []

    def execute(self, sql, params=None):
        self.db.statements.append(sql)
        if sql.startswith("SELECT CURRENT_USER"):
            self.rows = [("SYNTHETIC_STEWARD", OWNER, migrations.PROD_DATABASE, "SYNTHETIC_WH")]
        elif "FROM PRESENTATION.CURRENT_RELEASE_V" in sql:
            self.rows = self.db.pointer
        elif sql.startswith("SHOW GRANTS"):
            self.description = [
                (key,) for key in ("privilege", "granted_to", "grantee_name", "grant_option")
            ]
            self.rows = [("OWNERSHIP", "ROLE", OWNER, "true")]
            if "VIEW" in sql:
                self.rows.append(("SELECT", "ROLE", "OH_LYME_PROD_READ", "false"))
                if self.db.missing_reader or (self.db.grant_drift and self.db.ddl):
                    self.rows.pop()
            else:
                assert "V156" in self.db.applied
        elif sql.startswith("SELECT version, sha256"):
            self.rows = [(version, record[1]) for version, record in self.db.applied.items()]
            if self.db.duplicate:
                self.rows.append(self.rows[0])
        elif sql.startswith("SELECT filename,sha256,deployment_commit"):
            self.rows = [self.db.applied["V156"]]
        elif sql.startswith("INSERT INTO GOVERNANCE.SCHEMA_MIGRATIONS"):
            version, filename, sha, commit = params
            assert version == "V156" and version not in self.db.applied
            self.db.applied[version] = (filename, sha, commit)
            self.rows = []
        else:
            assert sql == f"USE DATABASE {migrations.PROD_DATABASE}", sql
            self.rows = []
        return self

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


@pytest.fixture
def deployment(monkeypatch):
    db = Ledger()
    monkeypatch.setattr(migrations, "load_migrations", lambda: db.plan)
    monkeypatch.setattr(migrations, "_reconciled_legacy_migrations", lambda *_: {})
    monkeypatch.setattr(migrations, "_migration_settings", lambda settings, *_: settings)
    for module in (migrations, runner):
        monkeypatch.setattr(module, "connect", lambda *_, **__: nullcontext(db))
    monkeypatch.setattr(runner, "SnowflakeSettings", object)
    for key, value in {
        "TOPX_ENV": "prod",
        "ENABLE_PRODUCTION_EXECUTION": "true",
        "CDC_ADMISSION_ONLY": "true",
        "GITHUB_REF": "refs/heads/main",
        "REVIEWED_COMMIT": COMMIT,
        "GITHUB_SHA": COMMIT,
        "EXPECTED_PENDING_JSON": json.dumps(
            [migrations._migration_metadata(m) for m in db.plan if m.version in {"V150", "V156"}]
        ),
    }.items():
        monkeypatch.setenv(key, value)
    return db


def test_initial_application_validates_and_applies_only_v156(deployment, capsys):
    runner.main()
    result = json.loads(capsys.readouterr().out)
    assert result["applied"] == ["V156"] and not result["validated_resume"]
    assert len(deployment.ddl) == 1 and "V150" not in deployment.applied
    assert deployment.pointer == [(TARGET_RELEASE_ID, TARGET_BUNDLE_SHA256)]
    assert not any("MANUAL_REVIEW_DECISIONS" in sql for sql in deployment.statements)


@pytest.mark.parametrize("original_inputs", [True, False])
def test_already_applied_retry_revalidates_without_replaying(
    deployment, monkeypatch, capsys, original_inputs
):
    runner.main()
    capsys.readouterr()
    deployment.ddl.clear()
    deployment.statements.clear()
    if not original_inputs:
        monkeypatch.setenv(
            "EXPECTED_PENDING_JSON",
            json.dumps(
                [migrations._migration_metadata(m) for m in deployment.plan if m.version == "V150"]
            ),
        )
    runner.main()
    result = json.loads(capsys.readouterr().out)
    assert result["applied"] == [] and result["validated_resume"]
    assert not deployment.ddl and "V150" not in deployment.applied
    assert sum(sql.startswith("SELECT CURRENT_USER") for sql in deployment.statements) == 2
    assert sum("CURRENT_RELEASE_V" in sql for sql in deployment.statements) == 2
    assert any("SHOW GRANTS ON PROCEDURE" in sql for sql in deployment.statements)
    assert any("deployment_commit" in sql for sql in deployment.statements)


@pytest.mark.parametrize(
    "failure",
    [
        "checksum",
        "commit",
        "filename",
        "duplicate",
        "unexpected_pending",
        "unknown_applied",
        "v150_applied",
        "prior_checksum",
    ],
)
def test_invalid_resume_state_blocks_before_image_promotion(deployment, failure):
    runner.main()
    deployment.ddl.clear()
    filename, sha, commit = deployment.applied["V156"]
    if failure == "checksum":
        deployment.applied["V156"] = (filename, "0" * 64, commit)
    elif failure == "commit":
        deployment.applied["V156"] = (filename, sha, "b" * 40)
    elif failure == "filename":
        deployment.applied["V156"] = ("V156__wrong.sql", sha, commit)
    elif failure == "duplicate":
        deployment.duplicate = True
    elif failure == "unexpected_pending":
        deployment.plan.append(
            migrations.Migration("V157", "V157__synthetic.sql", "SELECT 1;", "0" * 64)
        )
    elif failure == "unknown_applied":
        deployment.applied["V999"] = ("V999__unexpected.sql", "0" * 64, COMMIT)
    elif failure == "v150_applied":
        m = next(m for m in deployment.plan if m.version == "V150")
        deployment.applied["V150"] = (m.filename, m.sha256, COMMIT)
    else:
        deployment.applied["V149"] = ("V149__wrong.sql", "0" * 64, COMMIT)
    with pytest.raises((ValueError, PermissionError)):
        runner.main()
        pytest.fail("image promotion must be unreachable")
    assert not deployment.ddl


def test_reviewed_commit_mismatch_rejects_before_any_session(deployment, monkeypatch):
    monkeypatch.setenv("REVIEWED_COMMIT", "b" * 40)
    with pytest.raises(SystemExit, match="PROTECTED_REVIEWED_MAIN"):
        runner.main()
    assert not deployment.statements and not deployment.ddl


def test_failed_post_migration_image_promotion_is_resumable(deployment, capsys):
    calls = []

    def workflow(*, image_failure):
        runner.main()  # Existing protected workflow orders this before provider update.
        calls.append("promote exact DEV-tested digest")
        if image_failure:
            raise RuntimeError("synthetic provider failure")

    with pytest.raises(RuntimeError, match="provider failure"):
        workflow(image_failure=True)
    first = json.loads(capsys.readouterr().out)
    assert first["applied"] == ["V156"]
    workflow(image_failure=False)
    second = json.loads(capsys.readouterr().out)
    assert second["validated_resume"] and second["applied"] == []
    assert len(deployment.ddl) == 1 and len(calls) == 2
    assert "V150" not in deployment.applied
    assert deployment.pointer == [(TARGET_RELEASE_ID, TARGET_BUNDLE_SHA256)]


def test_post_migration_grant_drift_prevents_promotion(deployment):
    deployment.grant_drift = True
    with pytest.raises(ValueError, match="EXISTING_READER_REQUIRED"):
        runner.main()


def test_retry_cannot_accept_missing_reader_as_a_new_grant_baseline(deployment):
    runner.main()
    deployment.ddl.clear()
    deployment.missing_reader = True
    with pytest.raises(ValueError, match="EXISTING_READER_REQUIRED"):
        runner.main()
    assert not deployment.ddl


def test_changed_release_pointer_blocks_resume(deployment):
    runner.main()
    deployment.ddl.clear()
    deployment.pointer = [("unapproved-release", "0" * 64)]
    with pytest.raises(ValueError, match="RELEASE_BINDING"):
        runner.main()
    assert not deployment.ddl


@pytest.mark.parametrize("failure", ["checksum", "filename", "missing_v150", "unexpected_pending"])
def test_changed_review_inputs_cannot_hide_behind_applied_v156(deployment, monkeypatch, failure):
    runner.main()
    deployment.ddl.clear()
    reviewed = [
        migrations._migration_metadata(m) for m in deployment.plan if m.version in {"V150", "V156"}
    ]
    if failure == "missing_v150":
        reviewed = []
    elif failure == "unexpected_pending":
        reviewed.append({"version": "V157", "filename": "V157__unexpected.sql", "sha256": "0" * 64})
    else:
        target = next(item for item in reviewed if item["version"] == "V156")
        target["sha256" if failure == "checksum" else "filename"] = (
            "0" * 64 if failure == "checksum" else "V156__unexpected.sql"
        )
    monkeypatch.setenv("EXPECTED_PENDING_JSON", json.dumps(reviewed))
    with pytest.raises((ValueError, PermissionError)):
        runner.main()
    assert not deployment.ddl
