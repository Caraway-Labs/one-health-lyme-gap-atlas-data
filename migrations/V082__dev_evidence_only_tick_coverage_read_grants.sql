-- DEV-only read grants required by the V081 owner-rights coverage classifier.
-- No restricted source relation, API role, or public runtime receives these grants.
USE DATABASE {{ DATABASE }};

GRANT SELECT ON TABLE GOVERNANCE.INGESTION_RUNS TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER;
GRANT SELECT ON TABLE GOVERNANCE.DATA_SOURCE_VERSIONS TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER;
