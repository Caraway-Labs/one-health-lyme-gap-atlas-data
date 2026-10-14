"""Execute old/new membership joins in SQLite; Snowflake performance remains live proof."""

import hashlib
import json
import re
import runpy
import sqlite3
from pathlib import Path

import pytest

from lyme_gap_atlas_data.migrations import DEV_DATABASE, PROD_DATABASE, migration_plan

ROOT = Path(__file__).parents[1]
OLD = (ROOT / "sql/january_climate_consumer_views.sql").read_text()
NEW = (ROOT / "sql/january_climate_consumer_views_scalar_join.sql").read_text()
VERIFIER = runpy.run_path(str(ROOT / "scripts/verify_climate_dev_views.py"))


def join_query(sql: str) -> str:
    query = sql[sql.index("WITH current_climate") : sql.index("\nSELECT release_id,")]
    query = re.sub(
        r"LATERAL FLATTEN\(INPUT => c.extension:(capture_ids|metadata)\)",
        r"json_each(c.extension, '$.\1')",
        query,
    )
    query = re.sub(
        r"(\w+\.\w+)((?::\w+)+)",
        lambda m: f"json_extract({m[1]}, '$.{m[2][1:].replace(':', '.')}')",
        query.replace("::VARCHAR", ""),
    )
    query = query.replace("PRESENTATION.", "").replace("GOVERNANCE.", "")
    return query + " SELECT release_id, record, retrieved_at, metadata FROM records"


def test_immutable_projection_and_dev_only_migration() -> None:
    # Every public column/expression and the metadata view remain byte-identical.
    assert NEW[NEW.index("\nSELECT release_id,") :] == OLD[OLD.index("\nSELECT release_id,") :]
    assert "c.extension," not in NEW
    migration = (ROOT / "migrations/V147__dev_climate_scalar_membership_join.sql").read_text()
    assert "COPY GRANTS" in migration
    assert "GRANT SELECT" not in migration and "INSERT " not in migration
    assert "CURRENT_CLIMATE_MEASURE_METADATA_V" not in migration
    assert "V147" in {row["version"] for row in migration_plan(DEV_DATABASE)}
    assert "V147" not in {row["version"] for row in migration_plan(PROD_DATABASE)}
    assert hashlib.sha256(migration.encode()).hexdigest() == VERIFIER["SCALAR_CHECKSUM"]


@pytest.mark.parametrize("published", [True, False])
@pytest.mark.parametrize("supported_contract", [True, False])
def test_join_parity_preserves_frozen_membership_and_all_lineage_guards(
    published: bool, supported_contract: bool
) -> None:
    metadata = [
        {"measure": {"measure_id": f"nclimgrid_{measure.lower()}_county_day"}}
        for measure in ("PRCP", "TMIN", "TMAX", "TAVG")
    ]
    extension = {
        "contract_version": "atlas-january-climate-release-extension-v1"
        if supported_contract
        else "unsupported",
        "ingestion_run_id": "run",
        "sources": {"noaa": {"artifact_id": "artifact", "sha256": "sha"}},
        "metadata": metadata,
        "capture_ids": [
            "zero",
            "negative",
            "missing",
            "outside",
            "wrong-run",
            "wrong-artifact",
            "wrong-hash",
            "wrong-resource",
            "wrong-version",
            "unknown-measure",
        ],
    }
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE SEMANTIC_RELEASE_POINTER(pointer_key, current_release_id)")
        db.execute("CREATE TABLE SEMANTIC_RELEASES(release_id, status, source_manifest)")
        db.execute("INSERT INTO SEMANTIC_RELEASE_POINTER VALUES ('ATLAS', 'release')")
        db.execute(
            "INSERT INTO SEMANTIC_RELEASES VALUES (?, ?, ?)",
            (
                "release",
                "PUBLISHED" if published else "DRAFT",
                json.dumps({"climate_extension": extension}),
            ),
        )
        db.execute(
            "CREATE TABLE GOVERNED_SOURCE_RECORD_REVISIONS(capture_record_id, ingestion_run_id, "
            "resource_key, source_definition_version, artifact_id, artifact_sha256, "
            "payload, retrieved_at)"
        )
        for identifier, measure, value in (
            ("zero", "PRCP", 0),
            ("negative", "TMIN", -1.5),
            ("missing", "TMAX", None),
            ("outside", "TAVG", None),
            ("not-member", "PRCP", 99),
            ("wrong-run", "PRCP", 99),
            ("wrong-artifact", "PRCP", 99),
            ("wrong-hash", "PRCP", 99),
            ("wrong-resource", "PRCP", 99),
            ("wrong-version", "PRCP", 99),
            ("unknown-measure", "OTHER", 99),
        ):
            row = [
                identifier,
                "run",
                "noaa_nclimgrid_daily_202501",
                2,
                "artifact",
                "sha",
                json.dumps({"record": {"measure": measure, "value": value}}),
                "retrieved",
            ]
            overrides = {
                "wrong-run": (1, "other"),
                "wrong-resource": (2, "other"),
                "wrong-version": (3, 1),
                "wrong-artifact": (4, "other"),
                "wrong-hash": (5, "other"),
            }
            if identifier in overrides:
                index, replacement = overrides[identifier]
                row[index] = replacement
            db.execute("INSERT INTO GOVERNED_SOURCE_RECORD_REVISIONS VALUES (?,?,?,?,?,?,?,?)", row)
        previous = sorted(db.execute(join_query(OLD)).fetchall())
        revised = sorted(db.execute(join_query(NEW)).fetchall())
        assert revised == previous
        assert len(revised) == (4 if published and supported_contract else 0)


def test_scalar_ledger_mismatch_stops_before_view_read() -> None:
    class Cursor:
        current = ""

        def execute(self, sql: str) -> None:
            self.current = sql
            assert "GET_DDL" not in sql

        def fetchone(self):
            return (VERIFIER["USER"], VERIFIER["ROLE"], VERIFIER["DEV"], VERIFIER["WAREHOUSE"])

        def fetchall(self):
            if "V136" in self.current:
                return [("V136__dev_january_climate_consumer_views.sql", VERIFIER["CHECKSUM"])]
            return [("V147__dev_climate_scalar_membership_join.sql", "wrong")]

    with pytest.raises(ValueError, match="CLIMATE_SCALAR_VIEW_LEDGER"):
        VERIFIER["verify"](Cursor(), OLD)
