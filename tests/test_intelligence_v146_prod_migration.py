"""Pin the PROD feed projection to the DEV-verified V142 shape."""

from lyme_gap_atlas_data.migrations import (
    DEV_DATABASE,
    PROD_DATABASE,
    load_migrations,
    migration_plan,
    render_migration,
)


def test_v146_is_prod_only_and_preserves_v142_shape() -> None:
    migrations = {item.version: item for item in load_migrations()}
    assert "V146" not in {row["version"] for row in migration_plan(DEV_DATABASE)}
    assert "V146" in {row["version"] for row in migration_plan(PROD_DATABASE)}
    prod = render_migration(migrations["V146"], PROD_DATABASE)
    dev = render_migration(migrations["V142"], DEV_DATABASE)
    for name in (
        "INTELLIGENCE_RAW_RETENTION_DOCUMENTS",
        "INTELLIGENCE_RAW_RETENTION_AUDIT",
        "INTELLIGENCE_FEED_V2",
    ):
        assert name in prod
    assert "CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V COPY GRANTS" in prod
    assert "OH_LYME_PROD_RUNTIME" in prod
    assert "OH_LYME_PROD_READ" in prod
    assert "OH_LYME_DEV_" not in prod
    assert "DELETE " not in prod
    assert "INTELLIGENCE_RAW_CLEANUP_APPROVALS" not in prod
    # The SQL body is the already reviewed DEV migration with only environment
    # and comment differences; no publisher-field or policy changes are hidden.
    assert (
        prod.split("USE DATABASE ", 1)[1]
        .replace(PROD_DATABASE, DEV_DATABASE)
        .replace("OH_LYME_PROD_", "OH_LYME_DEV_")
        == dev.split("USE DATABASE ", 1)[1]
    )
