import copy
import json
import os
import runpy
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from lyme_gap_atlas_data import climate_metadata_preflight as preflight
from lyme_gap_atlas_data.climate_dev_validation import DEV, ROLE, USER, WAREHOUSE
from lyme_gap_atlas_data.migrations import (
    LEGACY_DEV_MIGRATION_CHECKSUMS,
    REQUIRED_REGISTRATION_COLUMNS,
    load_migrations,
    migration_plan,
)

ROOT = Path(__file__).parents[1]
HELPERS = runpy.run_path(str(ROOT / "scripts/verify_climate_dev_views.py"))


def responses():
    grant = {"privilege": "OWNERSHIP", "granted_to": "ROLE", "grantee_name": ROLE}
    ledger = [
        {key: row[key] for key in ("version", "filename", "sha256")}
        for row in migration_plan(DEV)
        if row["version"] != "V147"
    ]
    for row in ledger:
        if row["version"] in LEGACY_DEV_MIGRATION_CHECKSUMS:
            row["sha256"] = LEGACY_DEV_MIGRATION_CHECKSUMS[row["version"]]
    source = {row.version: row for row in load_migrations()}
    ddl = HELPERS["proposals"]((ROOT / "sql/january_climate_consumer_views.sql").read_text())
    return [
        [
            dict(
                zip(
                    ("user", "role", "database", "warehouse"),
                    (USER, ROLE, DEV, WAREHOUSE),
                    strict=True,
                )
            )
        ],
        [
            {
                "name": WAREHOUSE,
                "size": "X-Small",
                "type": "STANDARD",
                "generation": "GEN_2",
                "max_cluster_count": 1,
                "min_cluster_count": 1,
                "enable_query_acceleration": False,
                "auto_suspend": 60,
            }
        ],
        [grant],
        [grant],
        [grant],
        [grant],
        [{"ddl": ddl[0]}],
        [{"ddl": ddl[1]}],
        ledger,
        [
            {
                "migration_version": version,
                "legacy_sha256": old,
                "source_sha256": source[version].sha256,
                "reconciliation_scope": "DEV",
            }
            for version, old in LEGACY_DEV_MIGRATION_CHECKSUMS.items()
        ],
        [{"column": name} for name in sorted(REQUIRED_REGISTRATION_COLUMNS)],
        [grant],
        [grant],
        [grant],
        [grant],
        [grant],
        [{"name": name, "type": kind} for name, kind in preflight.column_contract(0)],
        [{"name": name, "type": kind} for name, kind in preflight.column_contract(1)],
    ]


class Cursor:
    def __init__(self, data=None, fail_at=None):
        self.data = responses() if data is None else data
        self.calls = []
        self.fail_at = fail_at
        self.description = []
        self.sfqid = None

    def execute(self, sql):
        self.calls.append(sql)
        self.sfqid = "query-" + str(len(self.calls))
        if len(self.calls) == self.fail_at:
            raise RuntimeError("PRIVATE_SENTINEL must not leak")
        self.current = self.data[len(self.calls) - 1]
        self.description = [(key,) for key in self.current[0]] if self.current else []

    def fetchall(self):
        return [tuple(row.values()) for row in self.current]


def test_exact_order_read_only_scope_and_sanitized_acceptance():
    cursor = Cursor()
    report = preflight.inspect(cursor, preflight.receipt("reviewed-head"), HELPERS)
    assert report["status"] == "PASS"
    assert report["metadata_prerequisites_pass"] is True
    assert report["sole_v147_ready"] is False  # Pricing/owner authorization is separate.
    assert report["statements_executed"] == 18
    assert cursor.calls == preflight.statements()
    assert report["pending_migrations"] == [preflight.V147]
    assert report["v149_excluded"] is True
    assert all(check["status"] == "PASS" for check in report["checks"])
    assert report["pricing_assumptions"]["actual_billed_cost_usd"] is None
    serialized = json.dumps(report)
    assert "CREATE OR REPLACE" not in serialized and "WITH current_climate" not in serialized
    assert report["reserved_forecast_usd"] <= 7


@pytest.mark.parametrize("failure", range(1, 19))
def test_access_error_stops_in_order_without_retry_or_exception_leak(failure):
    cursor = Cursor(fail_at=failure)
    report = preflight.inspect(cursor, preflight.receipt("head"), HELPERS)
    assert len(cursor.calls) == failure
    assert cursor.calls == preflight.statements()[:failure]
    assert report["checks"][failure - 1]["category"] == "READ_OR_ACCESS_UNAVAILABLE"
    assert all(c["status"] == "NOT_EXECUTED" for c in report["checks"][failure:])
    assert "PRIVATE_SENTINEL" not in json.dumps(report)
    assert report["sole_v147_ready"] is False


@pytest.mark.parametrize(
    "kind",
    [
        "warehouse_unknown",
        "permission",
        "v149",
        "checksum",
        "legacy",
        "column_name",
        "column_type",
        "column_order",
    ],
)
def test_failed_acceptance_does_not_continue(kind):
    data = copy.deepcopy(responses())
    expected = {
        "warehouse_unknown": 2,
        "permission": 5,
        "v149": 9,
        "checksum": 9,
        "legacy": 10,
        "column_name": 17,
        "column_type": 17,
        "column_order": 17,
    }[kind]
    if kind == "warehouse_unknown":
        del data[1][0]["max_cluster_count"]
    elif kind == "permission":
        data[4] = [{**data[4][0], "grantee_name": "UNVERIFIED_OWNER"}]
    elif kind == "v149":
        data[8] = [row for row in data[8] if row["version"] != "V149"]
    elif kind == "checksum":
        data[8][0]["sha256"] = "PRIVATE_SENTINEL"
    elif kind == "legacy":
        data[9][0]["source_sha256"] = "bad"
    elif kind == "column_name":
        data[16][0]["name"] = "RENAMED"
    elif kind == "column_type":
        data[16][0]["type"] = "VARIANT"
    else:
        data[16][0], data[16][1] = data[16][1], data[16][0]
    cursor = Cursor(data)
    report = preflight.inspect(cursor, preflight.receipt("head"), HELPERS)
    assert len(cursor.calls) == expected
    assert report["status"] == "BLOCKED"
    assert report["checks"][expected - 1]["status"] == "BLOCKED"
    assert "PRIVATE_SENTINEL" not in json.dumps(report)
    if kind == "v149":
        assert report["v149_excluded"] is False


def test_sql_tampering_blocks_before_any_sql(tmp_path, monkeypatch):
    path = tmp_path / "scope.sql"
    path.write_text(preflight.SQL_PATH.read_text() + "DROP TABLE private;")
    monkeypatch.setattr(preflight, "SQL_PATH", path)
    cursor = Cursor()
    with pytest.raises(preflight.Stop, match="SQL_SCOPE_CHANGED"):
        preflight.inspect(cursor, preflight.receipt("head"), HELPERS)
    assert not cursor.calls


def test_entrypoint_does_not_add_commit_rollback_or_close_retry(monkeypatch, capsys):
    script = runpy.run_path(str(ROOT / "scripts/preflight_climate_v147_dev.py"))
    main = script["main"]
    cursor = Cursor()

    class Connection:
        def __enter__(self):
            raise AssertionError("Connection context manager adds transaction SQL")

        def cursor(self):
            class Context:
                def __enter__(self):
                    return cursor

                def __exit__(self, *args):
                    pass

            return Context()

        def close(self, *, retry):
            assert retry is False

    monkeypatch.setattr(
        runpy, "run_path", lambda path: {**HELPERS, "bounded_connection": Connection}
    )
    main()
    assert len(cursor.calls) == 18
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"


@pytest.mark.parametrize(
    "override",
    [
        {},
        {"DIAGNOSE_CLIMATE_VIEWS": "true"},
        {"DIAGNOSE_CLIMATE_DEV": "true"},
        {"DIAGNOSE_JANUARY_PAIR": "true"},
        {"DIAGNOSE_INTELLIGENCE_DEV": "true"},
        {"REGISTER_EID_EXPEDITED_DEV": "true"},
        {"EXPECTED_PENDING_JSON": '[{"version":"V147"}]'},
        {"GITHUB_REF": "refs/heads/feature"},
        {"REVIEWED_COMMIT": "b" * 40},
        {"SNOWFLAKE_ROLE": "ACCOUNTADMIN"},
        {"DIAGNOSE_QUERY_ID": "unapproved"},
    ],
)
def test_actual_protected_shell_only_calls_metadata_runner(tmp_path, override):
    bash = shutil.which("bash") if os.name != "nt" else None
    if not bash:
        pytest.skip("Exact-head Linux CI validates the actual workflow shell")
    document = yaml.safe_load((ROOT / ".github/workflows/deploy-dev.yml").read_text())
    step = next(
        step
        for step in document["jobs"]["deploy"]["steps"]
        if step.get("name") == "Configure and verify the DEV Snowflake service connection"
    )
    calls = tmp_path / "calls"
    env = {
        **os.environ,
        **{key: "false" for key in step["env"]},
        "METADATA_PREFLIGHT_ONLY": "true",
        "EXPECTED_PENDING_JSON": "[]",
        "DIAGNOSE_QUERY_ID": "",
        "JANUARY_DIAGNOSTIC_BUDGET_EVIDENCE": "",
        "REVIEWED_COMMIT": "a" * 40,
        "GITHUB_SHA": "a" * 40,
        "GITHUB_REF": "refs/heads/main",
        "RUNNER_TEMP": str(tmp_path),
        "CALLS": str(calls),
        "SNOWFLAKE_USER": USER,
        "SNOWFLAKE_ROLE": ROLE,
        "SNOWFLAKE_DATABASE": DEV,
        "SNOWFLAKE_WAREHOUSE": WAREHOUSE,
        "SNOWFLAKE_PRIVATE_KEY_B64": "",
        **override,
    }
    fakes = """
    uv() { printf '%s\\n' "$*:$MAX_CON_RETRY_ATTEMPTS" >> "$CALLS"; }
    gh() { echo 1; }
    git() { echo "$GITHUB_SHA"; }
    snow() { echo forbidden-sql >> "$CALLS"; return 99; }
    timeout() { shift 3; "$@"; }
    """
    result = subprocess.run(
        [bash, "-c", fakes + step["run"]],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if override:
        assert result.returncode != 0
        assert not calls.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert calls.read_text().splitlines() == [
            "run python scripts/preflight_climate_v147_dev.py:0"
        ]
