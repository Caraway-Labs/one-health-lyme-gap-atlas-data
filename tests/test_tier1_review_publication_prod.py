"""Pinned PROD admission and artifact checks without Snowflake mutation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    PROD_DATABASE,
    load_migrations,
    migration_execution_role,
    migration_plan,
    render_migration,
)

ROOT = Path(__file__).parents[1]
SQL = (ROOT / "migrations/V141__prod_tier1_county_review_publication.sql").read_text(
    encoding="utf-8"
)
SCRIPT = ROOT / "scripts/publish_tier1_review_prod.py"
SPEC = importlib.util.spec_from_file_location("publish_tier1_review_prod", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


def test_prod_migration_is_isolated_from_dev_v140() -> None:
    migration = next(item for item in load_migrations() if item.version == "V141")
    assert migration_execution_role(migration, PROD_DATABASE) == (
        "OH_LYME_PROD_TIER1_PUBLICATION_OWNER"
    )
    assert "V141" in {item["version"] for item in migration_plan(PROD_DATABASE)}
    assert "V141" not in {item["version"] for item in migration_plan(DEV_DATABASE)}
    with pytest.raises(ValueError, match="PROD-only"):
        render_migration(migration, DEV_DATABASE)
    assert "tier1-county-features-v1" not in SQL
    assert "governed-2026-09-17-unknown-coverage" not in SQL
    assert "OH_LYME_DEV" not in SQL


def test_prod_pins_exact_candidate_and_reuses_v140_safeguards() -> None:
    for value in (
        "tier1-review-priority-5536b5caad95cf47",
        "45e711465c2176b5a5b88f7eb23993a4e824a005f03b45e6abdf6171c81aca12",
        "024bbbf74a7da8e54566bd60e8e762d85a51e24f",
        "governed-2026-09-18-unknown-coverage",
        "038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026",
        "tier1-county-features-v2",
        "tier1-statistical-reference-v1",
        "tier1-selection-evaluation-v1",
        "tier1-review-percentile-v1",
    ):
        assert value in SQL
    for safeguard in (
        "CHANGED_DIGEST_REPLAY",
        "CHANGED_ROW_REPLAY",
        "INCOMPLETE_BATCH",
        "FIPS_SET_MISMATCH",
        "DIGEST_MISMATCH",
        "UPDATE FEATURE_STORE.TIER1_REVIEW_WRITE_LOCK",
        "LISTAGG(row_json, ',') WITHIN GROUP (ORDER BY county_fips)",
        "q('ROLLBACK')",
    ):
        assert safeguard in SQL
    assert SQL.count("EXCEPT SELECT") == 2
    assert (
        "GRANT SELECT ON VIEW PRESENTATION.CURRENT_TIER1_COUNTY_REVIEW_V TO ROLE OH_LYME_PROD_READ"
        in SQL
    )
    assert "GRANT SELECT ON TABLE FEATURE_STORE" not in SQL


def test_prod_read_view_matches_accepted_dev_api_contract() -> None:
    dev_sql = (ROOT / "migrations/V140__dev_tier1_county_review_publication.sql").read_text(
        encoding="utf-8"
    )
    marker = "CREATE OR REPLACE VIEW PRESENTATION.CURRENT_TIER1_COUNTY_REVIEW_V AS"
    assert (
        SQL.split(marker, 1)[1].split("GRANT SELECT", 1)[0]
        == dev_sql.split(marker, 1)[1].split("GRANT SELECT", 1)[0]
    )
    bootstrap = (ROOT / "scripts/bootstrap_tier1_review_roles_prod.sql").read_text(encoding="utf-8")
    assert (
        "GRANT SELECT, INSERT ON TABLE ONE_HEALTH_LYME_GAP_ATLAS_PROD.GOVERNANCE.SCHEMA_MIGRATIONS"
        in bootstrap
    )
    assert "TO ROLE OH_LYME_PROD_ML_PUBLISHER" in bootstrap
    assert "GRANT SELECT ON TABLE ONE_HEALTH_LYME_GAP_ATLAS_PROD.FEATURE_STORE" not in bootstrap


def test_offline_prod_handoff_is_byte_identical_and_complete() -> None:
    path = Path(
        r"C:\Users\caraw\Documents\Codex\2026-10-06\ml-104-final-prod-publication-artifacts"
    )
    if not path.exists():
        pytest.skip("Operator-preserved ML artifacts are outside this checkout")
    manifest, rows = publisher.verify_artifacts(path)
    assert len(rows) == 3144
    assert manifest["batch_id"] == publisher.BATCH_ID


def test_prod_publisher_rejects_human_role_assumption_before_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries: list[str] = []

    def query(_connection: str, sql: str) -> list[dict[str, str]]:
        queries.append(sql)
        return [
            {
                "USER_NAME": "MATTHEWCARAWAY",
                "ROLE_NAME": "OH_LYME_PROD_ML_PUBLISHER",
                "DATABASE_NAME": PROD_DATABASE,
                "WAREHOUSE_NAME": "OH_LYME_PROD_INGEST_XS_WH",
            }
        ]

    monkeypatch.setattr(publisher, "snow_query", query)
    with pytest.raises(ValueError, match="wrong service user"):
        publisher.publish("test", {}, [])
    assert len(queries) == 1
    assert queries[0].startswith("SELECT CURRENT_USER()")
