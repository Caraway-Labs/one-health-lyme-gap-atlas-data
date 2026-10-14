import copy
import hashlib
import json
import os
import runpy
import shutil
import subprocess
from datetime import UTC, datetime
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


def budget(standard=False, price=6):
    result = {
        "unit_price_usd": price,
        "verified_by": "FIXTURE_OWNER",
        "verified_at": datetime.now(UTC).isoformat(),
        "region": "AWS_US_WEST_2",
        "evidence_reference": "https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf",
    }
    if standard:
        result["standard_capability_evidence"] = {
            "edition": "STANDARD",
            "cloud": "AWS",
            "account_locator_sha256": hashlib.sha256(b"FIXTURE_ACCOUNT").hexdigest(),
            "verified_at": datetime.now(UTC).isoformat(),
            "verified_by": "FIXTURE_OWNER",
            "evidence_reference": "OWNER_SNOWSIGHT_ACCOUNT_DETAILS",
        }
    return result


def run(cursor, evidence=None):
    report = preflight.receipt("reviewed-head")
    checked = preflight.prepare_evidence(json.dumps(evidence or budget()), report)
    return preflight.inspect(cursor, report, {**HELPERS, "budget_evidence": checked})


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
                    ("user", "role", "database", "warehouse", "region", "account"),
                    (USER, ROLE, DEV, WAREHOUSE, "AWS_US_WEST_2", "FIXTURE_ACCOUNT"),
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
    report = run(cursor)
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
    report = run(cursor)
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
    report = run(cursor)
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
        run(cursor)
    assert not cursor.calls


def test_retained_omission_shape_passes_only_with_bound_owner_entitlement():
    data = responses()
    for key in ("min_cluster_count", "max_cluster_count", "enable_query_acceleration"):
        del data[1][0][key]
    blocked = run(Cursor(copy.deepcopy(data)))
    assert blocked["status"] == "BLOCKED"
    accepted = run(Cursor(data), budget(standard=True))
    assert accepted["status"] == "PASS"
    assert accepted["standard_capability_binding"] == "MATCHED_LIVE_ACCOUNT"
    assert accepted["edition_cost_capabilities"]["compute_cluster_cost_bound"] == 1
    for key in ("min_cluster_count", "max_cluster_count", "enable_query_acceleration"):
        assert accepted["warehouse_configuration"][key] == {"present": False, "value": None}
    assert accepted["pricing_assumptions"]["actual_billed_unit_price_usd"] is None


@pytest.mark.parametrize(
    "field,value",
    [("max_cluster_count", 2), ("min_cluster_count", 2), ("enable_query_acceleration", True)],
)
def test_owner_entitlement_cannot_override_observed_contradictions(field, value):
    data = responses()
    data[1][0][field] = value
    cursor = Cursor(data)
    report = run(cursor, budget(standard=True))
    assert report["status"] == "BLOCKED" and len(cursor.calls) == 2


@pytest.mark.parametrize("field,value", [("account", "WRONG_ACCOUNT"), ("region", "AWS_US_EAST_1")])
def test_owner_evidence_must_bind_before_warehouse_statement(field, value):
    data = responses()
    data[0][0][field] = value
    cursor = Cursor(data)
    report = run(cursor, budget(standard=True))
    assert report["status"] == "BLOCKED" and len(cursor.calls) == 1
    assert value not in json.dumps(report)


def test_absent_minimum_stays_unknown_without_owner_evidence():
    data = responses()
    del data[1][0]["min_cluster_count"]
    report = run(Cursor(data))
    assert report["status"] == "BLOCKED"
    assert report["warehouse_cost_failed_fields"] == ["min_cluster_count"]


def test_owner_cloud_must_match_live_region_before_warehouse():
    evidence = budget(standard=True)
    evidence["region"] = "AZURE_WESTUS2"
    data = responses()
    data[0][0]["region"] = "AZURE_WESTUS2"
    cursor = Cursor(data)
    report = run(cursor, evidence)
    assert report["status"] == "BLOCKED" and len(cursor.calls) == 1


@pytest.mark.parametrize("document", ["", json.dumps(budget(price=8))])
def test_missing_or_over_budget_price_evidence_never_authenticates(monkeypatch, capsys, document):
    main = runpy.run_path(str(ROOT / "scripts/preflight_climate_v147_dev.py"))["main"]
    monkeypatch.setenv("JANUARY_DIAGNOSTIC_BUDGET_EVIDENCE", document)
    monkeypatch.setattr(runpy, "run_path", lambda path: pytest.fail("Authentication was reached"))
    with pytest.raises(SystemExit):
        main()
    report = json.loads(capsys.readouterr().out)
    assert report["statements_executed"] == 0
    assert report["pricing_assumptions"]["actual_billed_cost_usd"] is None


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
    monkeypatch.setenv("JANUARY_DIAGNOSTIC_BUDGET_EVIDENCE", json.dumps(budget()))
    main()
    assert len(cursor.calls) == 18
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"


@pytest.mark.parametrize(
    "override",
    [
        {},
        {"LEDGER_DIAGNOSTIC_ONLY": "true"},
        {"LEDGER_DIAGNOSTIC_ONLY": "true", "METADATA_PREFLIGHT_ONLY": "false"},
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
        "LEDGER_DIAGNOSTIC_ONLY": "false",
        "EXPECTED_PENDING_JSON": "[]",
        "DIAGNOSE_QUERY_ID": "",
        "JANUARY_DIAGNOSTIC_BUDGET_EVIDENCE": json.dumps(budget()),
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
    if override and override != {"LEDGER_DIAGNOSTIC_ONLY": "true"}:
        assert result.returncode != 0
        assert not calls.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert calls.read_text().splitlines() == [
            "run python scripts/preflight_climate_v147_dev.py:0"
        ]


def test_v022_reconciled_v019_preserves_both_rows_and_passes():
    data = responses()
    v019 = next(row for row in data[8] if row["version"] == "V019")
    data[8].append(copy.deepcopy(v019))
    report = run(Cursor(data))
    assert report["status"] == "PASS"
    assert sum(row["version"] == "V019" for row in report["migration_ledger"]) == 2
    assert report["checks"][8]["historical_duplicate_reconciliation"]["reconciled_by"] == "V022"


@pytest.mark.parametrize(
    "kind", ["third", "other", "checksum", "filename", "missing_v022", "twice_v022"]
)
def test_only_exact_v022_reconciled_duplicate_is_accepted(kind):
    data = responses()
    v019 = next(row for row in data[8] if row["version"] == "V019")
    data[8].append(copy.deepcopy(v019))
    if kind == "third":
        data[8].append(copy.deepcopy(v019))
    elif kind == "other":
        data[8].append(copy.deepcopy(next(row for row in data[8] if row["version"] == "V136")))
    elif kind == "checksum":
        data[8][-1]["sha256"] = "0" * 64
    elif kind == "filename":
        data[8][-1]["filename"] = "V019__unexpected.sql"
    elif kind == "missing_v022":
        data[8] = [row for row in data[8] if row["version"] != "V022"]
    else:
        data[8].append(copy.deepcopy(next(row for row in data[8] if row["version"] == "V022")))
    report = run(Cursor(data))
    assert report["status"] == "BLOCKED" and report["checks"][8]["status"] == "BLOCKED"
    assert report["pending_migrations"] is None


@pytest.mark.parametrize(
    "field,value", [("sha256", "0" * 64), ("filename", "V022__unexpected.sql")]
)
def test_v022_reconciliation_identity_cannot_change(field, value):
    data = responses()
    data[8].append(copy.deepcopy(next(row for row in data[8] if row["version"] == "V019")))
    next(row for row in data[8] if row["version"] == "V022")[field] = value
    report = run(Cursor(data))
    assert report["status"] == "BLOCKED" and report["pending_migrations"] is None


def test_v019_reconciliation_does_not_admit_pending_v149():
    data = responses()
    data[8].append(copy.deepcopy(next(row for row in data[8] if row["version"] == "V019")))
    data[8] = [row for row in data[8] if row["version"] != "V149"]
    report = run(Cursor(data))
    assert report["status"] == "BLOCKED"
    assert report["checks"][8]["category"] == "PENDING_SET_NOT_SOLE_V147"
    assert report["v149_excluded"] is False
    assert [row["version"] for row in report["pending_migrations"]] == ["V147", "V149"]
