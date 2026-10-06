import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "feed_preflight", Path(__file__).parents[1] / "scripts/verify_intelligence_dev_preflight.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_budget_requires_public_safe_confirmation_only():
    for value in ("false", "", '{"spent_usd":0}'):
        with pytest.raises(ValueError, match="CONFIRMATION_REQUIRED"):
            module.budget(value)
    assert module.budget("true") is None


class Cursor:
    def __init__(self, identity):
        self.identity = identity
        self.sql = []
        self.description = [("name",), ("owner",)]

    def execute(self, sql, **kwargs):
        self.sql.append(sql)

    def fetchone(self):
        return self.identity

    def fetchall(self):
        return []


def test_wrong_identity_stops_before_object_inspection():
    cursor = Cursor((module.USER, "ACCOUNTADMIN", module.DEV, module.WAREHOUSE))
    with pytest.raises(ValueError, match="IDENTITY"):
        module.inspect(cursor, {})
    assert len(cursor.sql) == 2


def test_hidden_objects_remain_unknown_no_registry_records():
    cursor = Cursor((module.USER, module.ROLE, module.DEV, module.WAREHOUSE))
    report = {}
    module.inspect(cursor, report)
    assert len(report["objects"]) == 5
    assert all(item["state"] == "NOT_VISIBLE_NOT_PROOF_OF_ABSENCE" for item in report["objects"])
    assert len(cursor.sql) == 7
    assert not any("registry_sha256" in sql or "registry_document" in sql for sql in cursor.sql)


def test_partial_completed_safe_observations_survive_later_failure():
    class Failing(Cursor):
        def execute(self, sql, **kwargs):
            super().execute(sql, **kwargs)
            if "INTELLIGENCE_RAW_RETENTION_AUDIT" in sql:
                raise RuntimeError("private failure text")

    cursor = Failing((module.USER, module.ROLE, module.DEV, module.WAREHOUSE))
    report = {}
    with pytest.raises(RuntimeError):
        module.inspect(cursor, report)
    assert len(report["objects"]) == 1
    assert report["objects"][0]["inspection_complete"] is True
    assert "private failure" not in str(report)


def test_workflow_public_safe_input_and_exit_before_migration():
    workflow = (Path(__file__).parents[1] / ".github/workflows/deploy-dev.yml").read_text()
    branch = workflow.index('if [ "$DIAGNOSE_INTELLIGENCE_DEV" = "true" ]')
    execute = workflow.index("uv run python scripts/verify_intelligence_dev_preflight.py", branch)
    assert workflow.index("exit 0", execute) < workflow.index("SELECT CURRENT_ACCOUNT()")
    for private_surface in (
        "BUDGET_JSON",
        "PUBLIC_KEY",
        "upload-artifact",
        "spent_usd",
        "evidence_ref",
    ):
        assert private_surface not in workflow


def test_definition_comparison_detects_version_and_private_projection_changes():
    source = (
        Path(__file__).parents[1] / "docs/contracts/intelligence/v2/presentation-projection.sql"
    ).read_text()
    start = source.index("CREATE VIEW IF NOT EXISTS PRESENTATION.INTELLIGENCE_FEED_V2")
    ddl = source[start:].split(";", 1)[0]
    assert module.view_matches("INTELLIGENCE_FEED_V2", ddl)
    assert not module.view_matches("INTELLIGENCE_FEED_V2", ddl.replace("'2.0.0'", "'1.0.0'"))
    assert not module.view_matches(
        "INTELLIGENCE_FEED_V2",
        ddl.replace(
            "OBJECT_CONSTRUCT() AS derived_metadata", "c.item_document AS derived_metadata"
        ),
    )


def test_watchdog_exit_is_unconditional_when_evidence_output_fails(monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("output failed")

    class Exited(BaseException):
        pass

    exits = []

    def leave(code):
        exits.append(code)
        raise Exited

    monkeypatch.setattr("builtins.print", broken)
    monkeypatch.setattr(module.os, "_exit", leave)
    with pytest.raises(Exited):
        module.terminate({"objects": []})
    assert exits == [124]


def test_catalog_and_owner_status_survive_describe_denial():
    class Denied(Cursor):
        def fetchall(self):
            return [("INTELLIGENCE_RAW_RETENTION_DOCUMENTS", module.ROLE)]

        def execute(self, sql, **kwargs):
            super().execute(sql, **kwargs)
            if sql.startswith("DESCRIBE"):
                raise PermissionError("private details")

    report = {}
    cursor = Denied((module.USER, module.ROLE, module.DEV, module.WAREHOUSE))
    with pytest.raises(PermissionError):
        module.inspect(cursor, report)
    assert report["identity_matches_expected"] is True
    observed = report["objects"][0]
    assert observed["state"] == "VISIBLE"
    assert observed["owner_matches_expected"] is True
    assert observed["inspection_complete"] is False
    assert module.ROLE not in str(report)


def test_table_reuse_requires_exact_columns_types_nullability_and_defaults():
    name = "INTELLIGENCE_RAW_RETENTION_DOCUMENTS"
    columns = [
        {
            "name": column,
            "type": kind,
            "kind": "COLUMN",
            "null?": "Y" if nullable else "N",
            "default": default or None,
        }
        for column, kind, nullable, default in module.TABLE_SHAPES[name]
    ]
    assert module.table_matches(name, columns)
    assert not module.table_matches(
        name,
        columns + [{"name": "PRIVATE_BODY", "type": "VARIANT", "kind": "COLUMN", "null?": "Y"}],
    )
    for key, wrong in (("type", "VARCHAR(1024)"), ("null?", "Y"), ("default", "'invented'")):
        changed = [dict(row) for row in columns]
        changed[0][key] = wrong
        assert not module.table_matches(name, changed)


def test_three_approved_scopes_reject_extra_runtime_access_and_grant_option():
    for name in (
        "INTELLIGENCE_RAW_RETENTION_DOCUMENTS",
        "INTELLIGENCE_RAW_RETENTION_AUDIT",
        "INTELLIGENCE_FEED_V2",
    ):
        role, privileges = module.ROLE_PRIVILEGES[name]
        grants = [
            {
                "grantee_name": role,
                "granted_to": "ROLE",
                "privilege": privilege,
                "grant_option": "false",
            }
            for privilege in privileges
        ]
        assert module.privileges_match(name, grants)["target_role_privileges_exact"] is True
        assert module.privileges_match(name, [])["required_privileges_present"] is False
        changed = grants + [
            {
                "grantee_name": role,
                "granted_to": "ROLE",
                "privilege": "DELETE",
                "grant_option": "false",
            }
        ]
        assert module.privileges_match(name, changed)["unexpected_target_role_privileges"] is True
        changed = [dict(row, grant_option="true") for row in grants]
        assert module.privileges_match(name, changed)["target_role_grant_option_present"] is True
