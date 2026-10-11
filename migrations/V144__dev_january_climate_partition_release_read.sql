-- DATA #443: allow the existing protected DEV semantic-release identity to
-- reconstruct and verify the retained January candidate in its own session.
-- Owner-approved exact table/role SELECT only; no runtime or PROD expansion.
USE DATABASE {{ DATABASE }};

GRANT SELECT ON TABLE GOVERNANCE.INGESTION_RUN_NORMALIZED_PARTITIONS
    TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER;
