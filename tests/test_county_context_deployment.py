"""Scope and resource gates for the protected forward migration."""

import json
import runpy
import sqlite3
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest

from lyme_gap_atlas_data import migrations

ROOT = Path(__file__).parents[1]


def entry(version):
    migration = next(m for m in migrations.load_migrations() if m.version == version)
    return {"version": version, "filename": migration.filename, "sha256": migration.sha256}


@pytest.mark.parametrize(
    "database,versions",
    [
        (migrations.DEV_DATABASE, ["V150", "V155"]),
        (migrations.PROD_DATABASE, ["V155"]),
        (migrations.PROD_DATABASE, ["V150", "V154", "V155"]),
    ],
)
def test_wrong_execution_scope_cannot_connect(monkeypatch, database, versions):
    connection = Mock()
    monkeypatch.setattr(migrations, "connect", connection)
    with pytest.raises(PermissionError, match="County context"):
        migrations.apply_migrations(
            Mock(),
            database,
            county_context_only=True,
            expected_pending=[entry(v) for v in versions],
        )
    connection.assert_not_called()


def test_only_v155_executes_and_v150_remains_pending(monkeypatch):
    plan = [
        m
        for m in migrations.load_migrations()
        if m.version not in migrations.DEV_ONLY_MIGRATION_VERSIONS
    ]
    cursor = Mock()
    cursor.fetchall.return_value = [
        (m.version, m.sha256) for m in plan if m.version not in {"V150", "V155"}
    ]
    connection = Mock()
    connection.cursor.return_value = nullcontext(cursor)
    monkeypatch.setattr(migrations, "connect", lambda *a, **k: nullcontext(connection))
    monkeypatch.setattr(migrations, "_reconciled_legacy_migrations", lambda *a: {})
    applied = migrations.apply_migrations(
        Mock(),
        migrations.PROD_DATABASE,
        "reviewed-commit",
        county_context_only=True,
        expected_pending=[entry("V150"), entry("V155")],
    )
    assert applied == ["V155"]
    assert connection.execute_string.call_count == 1
    sql = connection.execute_string.call_args.args[0]
    assert "CURRENT_COUNTY_OBSERVATIONS_V COPY GRANTS" in sql
    assert "CLEANUP" not in sql
    recorded = [
        call for call in cursor.execute.call_args_list if call.args[0].lstrip().startswith("INSERT")
    ]
    assert len(recorded) == 1 and recorded[0].args[1][0] == "V155"


def test_view_replacement_uses_existing_owner_without_new_grants():
    migration = next(m for m in migrations.load_migrations() if m.version == "V155")
    assert (
        migrations.migration_execution_role(migration, migrations.PROD_DATABASE)
        == "OH_LYME_PROD_OWNER"
    )
    assert "GRANT " not in migration.source


@pytest.mark.parametrize("rows", [[], [("wrong", "bundle")]])
def test_deployment_stops_on_release_change(rows):
    script = runpy.run_path(str(ROOT / "scripts/apply_county_context_migration.py"))
    cursor = Mock()
    cursor.fetchall.return_value = rows
    with pytest.raises(ValueError, match="CONTEXT_RELEASE_BINDING"):
        script["snapshot"](cursor, deployed=False)
    assert cursor.execute.call_count == 1


def test_deployment_entry_requires_protected_production_environment(monkeypatch):
    script = runpy.run_path(str(ROOT / "scripts/apply_county_context_migration.py"))
    monkeypatch.delenv("COUNTY_CONTEXT_ONLY", raising=False)
    with pytest.raises(SystemExit, match="CONTEXT_PROTECTED_PROD_REQUIRED"):
        script["main"]()


@pytest.fixture
def mixed_snapshot():
    """Execute snapshot SELECTs against context plus actual retained-row shapes."""
    script = runpy.run_path(str(ROOT / "scripts/apply_county_context_migration.py"))
    db = sqlite3.connect(":memory:")
    db.execute("ATTACH DATABASE ':memory:' AS PRESENTATION")
    names = list(
        dict.fromkeys(
            [
                *script["LEGACY_COLUMNS"].split(","),
                "vintage_year",
                "metadata_revision_id",
                "context_limitations",
                "context_contract_version",
            ]
        )
    )
    db.execute(f"CREATE TABLE {script['VIEW']} ({','.join(names)})")
    db.execute("CREATE TABLE PRESENTATION.CURRENT_RELEASE_V (release_id,bundle_sha256)")
    db.execute(
        "INSERT INTO PRESENTATION.CURRENT_RELEASE_V VALUES (?,?)",
        (script["RELEASE"], script["BUNDLE"]),
    )
    db.execute(
        "CREATE TABLE PRESENTATION.CURRENT_COUNTY_ATLAS_V "
        "(fips,population,svi_percentile,uninsured_percent,uninsured_percentile,rucc_2023)"
    )
    for fips in ("01001", "08001"):
        db.execute(
            "INSERT INTO PRESENTATION.CURRENT_COUNTY_ATLAS_V VALUES (?,100,0.5,7.4,0.6,2)", (fips,)
        )
        values = dict(zip(script["CONTEXT_MEASURES"], (100, 0.5, 7.4, 0.6, 2), strict=True))
        for measure, value in values.items():
            rucc = measure == "rucc_2023"
            record = dict.fromkeys(names)
            record.update(
                observation_id=f"{measure}:{fips}",
                measure_id=measure,
                county_fips=fips,
                value=json.dumps(value),
                value_state="OBSERVED",
                period_start=None if rucc else "2018-01-01",
                period_end=None if rucc else "2022-12-31",
                temporal_grain="VINTAGE_YEAR" if rucc else "PERIOD",
                vintage_year=2023 if rucc else 2022,
                metadata_revision_id=f"metadata:{measure}",
                context_limitations='[{"text":"Context only"}]',
                context_contract_version=script["CONTEXT_CONTRACT"],
            )
            db.execute(
                f"INSERT INTO {script['VIEW']} VALUES ({','.join(['?'] * len(names))})",
                tuple(record.values()),
            )
    for fips in ("01001", "08001", "09110", "51013"):
        measures = ["human_status", "case_count_floor_2023", "incidence_floor_2023"]
        if fips in ("09110", "51013"):
            measures += [f"nlcd_measure_{index}" for index in range(7)]
        for measure in measures:
            record = dict.fromkeys(names)
            record.update(
                observation_id=f"{measure}:{fips}",
                measure_id=measure,
                county_fips=fips,
                value="1",
                value_state="OBSERVED",
                temporal_grain="YEAR",
                period_start="2023-01-01",
                period_end="2023-12-31",
            )
            db.execute(
                f"INSERT INTO {script['VIEW']} VALUES ({','.join(['?'] * len(names))})",
                tuple(record.values()),
            )

    class Cursor:
        def execute(self, sql, params=()):
            if sql.startswith("SHOW GRANTS"):
                self.description = [
                    (name,) for name in ("privilege", "granted_to", "grantee_name", "grant_option")
                ]
                self.result = [
                    ("OWNERSHIP", "ROLE", "OH_LYME_PROD_OWNER", "true"),
                    ("SELECT", "ROLE", "OH_LYME_PROD_READ", "false"),
                ]
            else:
                cursor = db.execute(sql.replace("%s", "?"), params)
                self.description = cursor.description
                self.result = cursor.fetchall()

        def fetchall(self):
            return self.result

    # Candidate is context-only; deployed source is the intentionally mixed view.
    script["snapshot"].__globals__["candidate"] = lambda: (
        f"SELECT * FROM {script['VIEW']} WHERE context_contract_version IS NOT NULL"
    )
    yield script, db, Cursor()
    db.close()


def test_mixed_deployed_view_matches_candidate_and_preserves_legacy(mixed_snapshot):
    script, db, cursor = mixed_snapshot
    unfiltered = db.execute(
        f"SELECT measure_id FROM {script['VIEW']} "
        "WHERE county_fips IN ('01001','08001') ORDER BY measure_id,county_fips LIMIT 11"
    ).fetchall()
    assert len(unfiltered) == 11
    assert any(row[0] == "human_status" for row in unfiltered)
    before = script["snapshot"](cursor, deployed=False)
    after = script["snapshot"](cursor, deployed=True)
    assert before == after
    assert len(after["observations"]) == 10 and len(after["legacy"]) == 23
    db.execute(
        f"UPDATE {script['VIEW']} SET value='changed legacy' "
        "WHERE measure_id='human_status' AND county_fips='01001'"
    )
    changed = script["snapshot"](cursor, deployed=True)
    assert changed["observations"] == after["observations"]
    assert changed["legacy"] != after["legacy"]


@pytest.mark.parametrize("deployed", [False, True])
@pytest.mark.parametrize("fault", ["missing", "duplicate", "replaced", "wrong_contract"])
def test_context_missing_duplicate_and_replaced_rows_fail_closed(mixed_snapshot, deployed, fault):
    script, db, cursor = mixed_snapshot
    target = "measure_id='population_2022' AND county_fips='08001'"
    if fault == "missing":
        db.execute(f"DELETE FROM {script['VIEW']} WHERE {target}")
    elif fault == "duplicate":
        db.execute(f"INSERT INTO {script['VIEW']} SELECT * FROM {script['VIEW']} WHERE {target}")
    elif fault == "wrong_contract":
        db.execute(
            f"UPDATE {script['VIEW']} SET context_contract_version='unreviewed' WHERE {target}"
        )
    else:
        # Total remains ten context-marked rows; an unrelated measure cannot fill the gap.
        db.execute(f"UPDATE {script['VIEW']} SET measure_id='unreviewed_measure' WHERE {target}")
    with pytest.raises(ValueError, match="CONTEXT_TEN_OBSERVATIONS"):
        script["snapshot"](cursor, deployed=deployed)


def test_missing_legacy_row_still_fails_separate_parity_gate(mixed_snapshot):
    script, db, cursor = mixed_snapshot
    db.execute(
        f"DELETE FROM {script['VIEW']} WHERE measure_id='human_status' AND county_fips='01001'"
    )
    with pytest.raises(ValueError, match="CONTEXT_LEGACY_BASELINE"):
        script["snapshot"](cursor, deployed=True)
