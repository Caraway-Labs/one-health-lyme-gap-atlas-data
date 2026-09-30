"""Keep fractional-dollar budget repair append-only and PROD-scoped."""

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    PROD_DATABASE,
    load_migrations,
    migration_execution_role,
    migration_plan,
    render_migration,
)


def test_prod_fractional_budget_contract() -> None:
    migrations = {migration.version: migration for migration in load_migrations()}
    prod_plan = {item["version"] for item in migration_plan(PROD_DATABASE)}
    dev_plan = {item["version"] for item in migration_plan(DEV_DATABASE)}
    assert {"V132", "V133"} <= prod_plan
    assert {"V132", "V133"}.isdisjoint(dev_plan)
    for version in ("V132", "V133"):
        sql = render_migration(migrations[version], PROD_DATABASE).upper()
        assert "NUMBER(12,6)" in sql
        assert migration_execution_role(migrations[version], PROD_DATABASE) == (
            "OH_LYME_PROD_KG_LLM_BUDGET_OWNER"
        )
    reserve = render_migration(migrations["V132"], PROD_DATABASE).upper()
    assert "COPY GRANTS" in reserve
    assert "DAILY_USED NUMBER(12,6)" in reserve
    assert "MONTHLY_USED NUMBER(12,6)" in reserve
    assert "GRANT INSERT" not in reserve
