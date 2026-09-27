"""DEV-only role bootstrap and procedure grant boundary for ADR 0041."""

from pathlib import Path

import pytest

from lyme_gap_atlas_data.migrations import load_migrations, migration_plan, render_migration

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts/bootstrap_dataset_discovery_roles_dev.sql"
GRANTS = ROOT / "migrations/V114__dev_dataset_discovery_role_grants.sql"


def sql_statements(path: Path) -> list[str]:
    source = "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("--")
    )
    return [statement.strip().upper() for statement in source.split(";") if statement.strip()]


def test_account_bootstrap_is_explicitly_dev_only() -> None:
    sql = BOOTSTRAP.read_text(encoding="utf-8").upper()
    assert sql.count("CREATE ROLE IF NOT EXISTS") == 3
    assert sql.count("GRANT READ SESSION ON ACCOUNT") == 1
    assert "TO ROLE OH_LYME_DEV_DATASET_DISCOVERY_WRITE_OWNER" in sql
    assert "GRANT ROLE OH_LYME_DEV_DATASET_DISCOVERY_WRITE_OWNER" in sql
    assert "TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER" in sql
    assert sql.count("GRANT USAGE ON DATABASE ONE_HEALTH_LYME_GAP_ATLAS_DEV") == 3
    assert sql.count("GRANT USAGE ON SCHEMA ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE") == 2
    assert "GRANT SELECT ON TABLE ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.CATALOG_DATASETS" in sql
    assert sql.count("GRANT USAGE ON WAREHOUSE OH_LYME_DEV_INGEST_XS_WH") == 2
    for forbidden in ("OH_LYME_PROD", "CREATE USER", "ALTER USER", "GRANT MANAGE GRANTS"):
        assert forbidden not in sql


def test_v114_is_protected_dev_only_and_keeps_runtime_reviewer_narrow() -> None:
    migration = next(item for item in load_migrations() if item.version == "V114")
    assert migration.filename == GRANTS.name
    assert "V114" in {item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_DEV")}
    assert "V114" not in {
        item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    }
    with pytest.raises(ValueError, match="DEV-only"):
        render_migration(migration, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    rendered = render_migration(migration, "ONE_HEALTH_LYME_GAP_ATLAS_DEV")
    sql = "\n".join(
        line for line in rendered.splitlines() if not line.lstrip().startswith("--")
    ).upper()
    assert "USE DATABASE ONE_HEALTH_LYME_GAP_ATLAS_DEV" in sql
    assert "OH_LYME_PROD" not in sql
    assert "GRANT READ SESSION" not in sql
    assert "CREATE ROLE" not in sql
    assert "GRANT MANAGE GRANTS" not in sql
    assert "GRANT USAGE ON DATABASE" not in sql
    assert "GRANT USAGE ON SCHEMA GOVERNANCE" not in sql
    assert "GRANT SELECT ON TABLE GOVERNANCE.CATALOG_DATASETS" not in sql
    assert "GRANT USAGE ON WAREHOUSE" not in sql
    assert "GRANT OWNERSHIP ON PROCEDURE" in sql
    assert sql.count("COPY CURRENT GRANTS") == 6
    for procedure in (
        "SP_CREATE_RUN",
        "SP_RECORD_CANDIDATE_OUTCOME",
        "SP_COMMIT_RECOMMENDATION",
        "SP_FINALIZE_RUN",
        "SP_APPEND_REVIEW_EVENT",
        "SP_HANDOFF_DATASET_DISCOVERY_RECOMMENDATION",
    ):
        assert any(
            statement.startswith("GRANT OWNERSHIP ON PROCEDURE ") and procedure in statement
            for statement in sql_statements(GRANTS)
        )


def test_runtime_and_reviewer_have_no_base_table_or_cross_authority_grants() -> None:
    for statement in sql_statements(GRANTS):
        if "TO ROLE OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME" in statement:
            assert "ON TABLE" not in statement
            assert "SP_APPEND_REVIEW_EVENT" not in statement
            assert "SP_HANDOFF_DATASET_DISCOVERY_RECOMMENDATION" not in statement
            assert "GOVERNANCE." not in statement
        if "TO ROLE OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER" in statement:
            assert "ON TABLE" not in statement
            assert "SP_CREATE_RUN" not in statement
            assert "SP_RECORD_CANDIDATE_OUTCOME" not in statement
            assert "SP_COMMIT_RECOMMENDATION" not in statement
            assert "SP_FINALIZE_RUN" not in statement
        assert "GRANT DELETE" not in statement
        assert "GRANT ALL" not in statement


def test_initial_human_reviewer_onboarding_is_ledgered_and_dev_only() -> None:
    migration = next(item for item in load_migrations() if item.version == "V115")
    assert "V115" in {item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_DEV")}
    assert "V115" not in {
        item["version"] for item in migration_plan("ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    }
    with pytest.raises(ValueError, match="DEV-only"):
        render_migration(migration, "ONE_HEALTH_LYME_GAP_ATLAS_PROD")
    statements = sql_statements(ROOT / "migrations" / migration.filename)
    assert len(statements) == 2
    assert statements[0] == "USE DATABASE {{ DATABASE }}"
    assert statements[1].startswith("INSERT INTO DATASET_DISCOVERY.REVIEWER_ALLOWLIST")
    assert statements[1].count("'MATTHEWCARAWAY'") == 2
    assert "WHERE NOT EXISTS" in statements[1]
    assert "CURRENT_USER()" in statements[1]
    assert "GRANT ROLE" not in statements[1]
