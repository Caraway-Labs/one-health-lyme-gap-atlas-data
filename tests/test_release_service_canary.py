"""The real-identity canary honors retained exceptions, never an invented class."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from lyme_gap_atlas_shared.settings import SnowflakeSettings

from lyme_gap_atlas_data import sql_sessions

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "service_canary", ROOT / "scripts/verify_release_service_identity.py"
)
assert SPEC and SPEC.loader
canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canary)


@pytest.mark.parametrize("operation", ["publish", "rollback"])
def test_january_inherited_environment_accepts_actual_canary_warehouse(monkeypatch, operation):
    workflow = yaml.safe_load((ROOT / ".github/workflows/publish-semantic-release.yml").read_text())
    step = next(
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == "Verify complete release through the real API service identity"
    )
    monkeypatch.setenv("ATLAS_JANUARY_PROD_SESSION", "true")
    for name, value in step["env"].items():
        if "${{" not in str(value):
            monkeypatch.setenv(name, str(value))
    settings = SnowflakeSettings(
        _env_file=None,
        snowflake_account="fixture",
        snowflake_user="OH_LYME_API_SVC",
        snowflake_role="OH_LYME_PROD_READ",
        snowflake_database="ONE_HEALTH_LYME_GAP_ATLAS_PROD",
        snowflake_warehouse=step["env"]["SNOWFLAKE_WAREHOUSE"],
        snowflake_auth_method="pat",
        snowflake_pat="offline-fixture",
    )
    connection = MagicMock()
    captured = {}

    def mocked_establishment(settings, **kwargs):
        captured.update(sql_sessions.connection_parameters(settings, **kwargs))
        return connection

    monkeypatch.setattr(sql_sessions, "shared_connect", mocked_establishment)
    sql_sessions.connect(settings)
    assert captured["warehouse"] == "COMPUTE_WH"
    statement = connection.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
    assert "STATEMENT_TIMEOUT_IN_SECONDS=60" in statement
    assert "STATEMENT_QUEUED_TIMEOUT_IN_SECONDS=10" in statement


@pytest.mark.parametrize("model_rows", [0, 100])
def test_canary_reads_exact_current_admission_and_retained_exceptions(monkeypatch, model_rows):
    profile = json.loads(
        (ROOT / "docs/contracts/semantic-release/release-completeness-2026-10-18.json").read_text()
    )
    for item in profile["artifacts"]:
        if "batch_id" in item:
            item.update(
                disposition="excluded" if model_rows == 0 else "degraded",
                expected_rows=model_rows,
                class_counts={} if model_rows == 0 else {"admitted-class": model_rows},
                exception_decision="fixture-owner-decision",
            )

    class Denied(Exception):
        sqlstate = "42S02"

    class Cursor:
        description = [("granted_on",), ("name",)]
        sql = ""
        queries = []

        def execute(self, sql, params=None):
            self.sql = sql
            self.queries.append((sql, params))
            if sql.startswith("SELECT * FROM FEATURE_STORE."):
                raise Denied()

        def fetchone(self):
            if "IS_ROLE_IN_SESSION" in self.sql:
                return (False, False, False)
            if "CURRENT_USER()" in self.sql:
                return (
                    "OH_LYME_API_SVC",
                    "OH_LYME_PROD_READ",
                    "ONE_HEALTH_LYME_GAP_ATLAS_PROD",
                    "COMPUTE_WH",
                )
            if "COUNT(DISTINCT fips)" in self.sql:
                return (3144, 3144)
            if "COUNT_IF(availability" in self.sql:
                return (6288, 6288 - 2 * model_rows)
            if "SELECT COUNT(*) FROM (SELECT model_id" in self.sql:
                return (0,)
            return (1,)

        def fetchmany(self, size):
            if "SELECT completeness" in self.sql:
                return [(profile,)]
            return [(profile["snapshot_release_id"], profile["snapshot_bundle_sha256"])]

        def fetchall(self):
            return []

    cursor = Cursor()
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    context = MagicMock()
    context.__enter__.return_value = connection
    monkeypatch.setattr(canary, "SnowflakeSettings", lambda: None)
    monkeypatch.setattr(canary, "connect", lambda _: context)
    projection = MagicMock()
    monkeypatch.setattr(canary, "verify_current", projection)
    result = canary.run()
    assert result["tier1_eligible_rows"] == model_rows
    assert result["situations_eligible_rows"] == 2 * model_rows
    assert projection.call_args.args[2]["artifacts"]["tier1"]["expected_rows"] == model_rows
    assert not any("36001" in q for q, _ in cursor.queries)
    assert sum("RELEASE_COMPLETENESS_EXCEPTIONS_V" in q for q, _ in cursor.queries) == 3
