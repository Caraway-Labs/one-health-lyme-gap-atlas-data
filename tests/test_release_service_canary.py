"""The real-identity canary honors retained exceptions, never an invented class."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "service_canary", ROOT / "scripts/verify_release_service_identity.py"
)
assert SPEC and SPEC.loader
canary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(canary)


def test_canary_reads_exact_current_admission_and_retained_exceptions(monkeypatch):
    profile = json.loads(
        (ROOT / "docs/contracts/semantic-release/release-completeness-2026-10-18.json").read_text()
    )
    for item in profile["artifacts"]:
        if "batch_id" in item:
            item.update(
                disposition="excluded",
                expected_rows=0,
                class_counts={},
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
                return (6288, 6288)
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
    assert result["tier1_eligible_rows"] == result["situations_eligible_rows"] == 0
    assert projection.call_args.args[2]["artifacts"]["tier1"]["expected_rows"] == 0
    assert sum("RELEASE_COMPLETENESS_EXCEPTIONS_V" in q for q, _ in cursor.queries) == 3
