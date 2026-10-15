import pytest

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    PROD_DATABASE,
    load_migrations,
    migration_plan,
    render_migration,
)


def test_v149_is_immutable_prod_authority_not_dev_dependency():
    migration = next(item for item in load_migrations() if item.version == "V149")
    assert migration.sha256 == "3f96b4889086dbc2df43bf9a7f0a02bc58f000e2c2bf7d68b09d2a1601c8299b"
    assert "SP_RECORD_RESTRICTED_FINAL_COPY_PROD" in migration.source
    assert "CURRENT_DATABASE() <> 'ONE_HEALTH_LYME_GAP_ATLAS_PROD'" in migration.source
    assert "COPY GRANTS" in migration.source
    assert "V149" not in {item["version"] for item in migration_plan(DEV_DATABASE)}
    assert "V149" in {item["version"] for item in migration_plan(PROD_DATABASE)}
    with pytest.raises(ValueError, match="PROD-only"):
        render_migration(migration, DEV_DATABASE)
    assert "USE DATABASE ONE_HEALTH_LYME_GAP_ATLAS_PROD" in render_migration(
        migration, PROD_DATABASE
    )


def test_climate_and_adjacent_authority_environment_scopes_stay_separate():
    dev = {item["version"] for item in migration_plan(DEV_DATABASE)}
    prod = {item["version"] for item in migration_plan(PROD_DATABASE)}
    assert {"V136", "V147"} <= dev
    assert {"V148", "V149", "V150"}.isdisjoint(dev)
    assert {"V148", "V149", "V150"} <= prod
    assert {"V136", "V147"}.isdisjoint(prod)
