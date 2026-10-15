import json
import runpy
from pathlib import Path

import pytest
import yaml
from test_climate_metadata_preflight import Cursor, responses

from lyme_gap_atlas_data import climate_inspection as inspection

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("environment,count", [("dev", 5), ("production", 10)])
def test_fixed_sql_scope(environment, count):
    sql = inspection.statements(environment)
    assert len(sql) == count
    assert all(
        " LIMIT " in item or item.startswith("SHOW ") or index == 0
        for index, item in enumerate(sql)
    )
    assert all("INSERT INTO" not in item and "CREATE " not in item for item in sql)


def run(environment="dev", fail_at=None):
    suffix = "PROD" if environment == "production" else "DEV"
    expected = (
        f"OH_LYME_{suffix}_MIGRATION_DEPLOY_SVC",
        f"OH_LYME_{suffix}_MIGRATION_DEPLOYER",
        f"ONE_HEALTH_LYME_GAP_ATLAS_{suffix}",
        "OH_LYME_PROD_APPROVAL_XS_WH" if suffix == "PROD" else "OH_LYME_DEV_INGEST_XS_WH",
    )
    data = responses()[:2]
    data[0][0] = dict(zip(data[0][0], (*expected, "AWS_US_WEST_2", "TXB06009"), strict=True))
    data[1][0]["name"] = expected[3]
    data += [[{"evidence": "bounded"}]] * (inspection.BUNDLES[environment][2] - 2)
    cursor = Cursor(data, fail_at=fail_at)
    report = inspection.inspect(
        cursor, environment, expected, {"status": "BLOCKED", "statements_executed": 0}, 0
    )
    return report, cursor


@pytest.mark.parametrize("environment,count", [("dev", 5), ("production", 10)])
def test_one_session_fixed_reads_no_extra_sql(monkeypatch, environment, count):
    monkeypatch.setattr(inspection.time, "monotonic", lambda: 1)
    report, cursor = run(environment)
    assert report["status"] == "PASS" and len(cursor.calls) == count
    assert cursor.calls == inspection.statements(environment)
    assert report["writes"] is False and "TXB06009" not in json.dumps(report)


@pytest.mark.parametrize("position", range(1, 11))
def test_failure_stops_without_retry(monkeypatch, position):
    monkeypatch.setattr(inspection.time, "monotonic", lambda: 1)
    report, cursor = run("production", fail_at=position)
    assert report["status"] == "BLOCKED" and len(cursor.calls) == position
    assert "PRIVATE_SENTINEL" not in json.dumps(report)


def test_inspection_job_excludes_release_job_and_credentials_stay_protected():
    workflow = yaml.safe_load((ROOT / ".github/workflows/publish-semantic-release.yml").read_text())
    jobs = workflow["jobs"]
    assert "!= 'inspect_january_climate'" in jobs["semantic-release"]["if"]
    job = jobs["climate-inspection"]
    assert "== 'inspect_january_climate'" in job["if"]
    assert job["environment"] == "${{ inputs.environment_name }}"
    step = job["steps"][-1]
    shell = step["run"]
    assert "180s" in shell and "--kill-after=15s" in shell and "MAX_CON_RETRY_ATTEMPTS=0" in shell
    assert 'test "$GITHUB_SHA" = "$REVIEWED_COMMIT"' in shell
    assert all(
        command not in shell
        for command in ("apply-migrations", "publish-release", "source run", "snow sql", "doctl")
    )


def test_prelogin_scope_tampering_or_identity_never_connects(monkeypatch, capsys):
    script = runpy.run_path(str(ROOT / "scripts/inspect_january_climate.py"))
    monkeypatch.setenv("INSPECTION_ENVIRONMENT", "production")
    monkeypatch.setenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN")
    monkeypatch.setattr(runpy, "run_path", lambda path: pytest.fail("must not load connection"))
    with pytest.raises(SystemExit):
        script["main"]()
    assert json.loads(capsys.readouterr().out)["statements_executed"] == 0


def test_sql_pin_cannot_be_replaced_by_arbitrary_input(tmp_path, monkeypatch):
    folder = tmp_path / "sql"
    folder.mkdir()
    filename = inspection.BUNDLES["production"][0]
    (folder / filename).write_text("DROP TABLE X")
    monkeypatch.setattr(inspection, "ROOT", tmp_path)
    with pytest.raises(inspection.Stop, match="SQL_SCOPE_CHANGED"):
        inspection.statements("production")


def test_unknown_prod_entitlement_does_not_assume_missing_settings(monkeypatch):
    monkeypatch.setattr(inspection.time, "monotonic", lambda: 1)
    original = Cursor.execute

    def execute(cursor, sql):
        if not cursor.calls:
            cursor.data[0][0]["account"] = "DIFFERENT_ACCOUNT"
            for key in ("min_cluster_count", "max_cluster_count", "enable_query_acceleration"):
                cursor.data[1][0].pop(key)
        original(cursor, sql)

    monkeypatch.setattr(Cursor, "execute", execute)
    report, cursor = run("production")
    assert report["status"] == "BLOCKED" and len(cursor.calls) == 2
    assert "rows" not in report["checks"][1]
