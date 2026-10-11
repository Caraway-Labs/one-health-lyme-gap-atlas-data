from lyme_gap_atlas_data import migrations


def test_v144_is_exact_dev_only_release_read_grant() -> None:
    migration = next(item for item in migrations.load_migrations() if item.version == "V144")
    assert migration.version in migrations.DEV_ONLY_MIGRATION_VERSIONS
    assert migration.version not in migrations.PROD_ONLY_MIGRATION_VERSIONS
    sql = (migrations.MIGRATIONS_DIR / migration.filename).read_text(encoding="utf-8")
    assert sql[sql.index("USE DATABASE") :].strip() == (
        "USE DATABASE {{ DATABASE }};\n\n"
        "GRANT SELECT ON TABLE GOVERNANCE.INGESTION_RUN_NORMALIZED_PARTITIONS\n"
        "    TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER;"
    )
