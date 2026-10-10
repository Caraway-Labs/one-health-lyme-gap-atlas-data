from lyme_gap_atlas_data import migrations


def test_v145_is_only_exact_dev_release_source_reads() -> None:
    migration = next(item for item in migrations.load_migrations() if item.version == "V145")
    assert migration.version in migrations.DEV_ONLY_MIGRATION_VERSIONS
    assert migration.version not in migrations.PROD_ONLY_MIGRATION_VERSIONS
    sql = (migrations.MIGRATIONS_DIR / migration.filename).read_text(encoding="utf-8")
    assert sql[sql.index("USE DATABASE") :].strip() == (
        "USE DATABASE {{ DATABASE }};\n\n"
        "GRANT SELECT ON VIEW CONFORMED.CONFORMED_CDC_LYME_X5J9_WYBP\n"
        "    TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER;\n"
        "GRANT SELECT ON TABLE CONFORMED.GOVERNED_SOURCE_RECORDS\n"
        "    TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER;\n"
        "GRANT SELECT ON TABLE CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS\n"
        "    TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER;"
    )
