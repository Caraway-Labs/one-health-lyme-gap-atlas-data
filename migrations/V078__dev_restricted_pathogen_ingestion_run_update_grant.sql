-- DEV-only least-privilege repair for the V077 owner-rights restricted loader.
-- The procedure records terminal status on its own governed ingestion run.
USE DATABASE {{ DATABASE }};

GRANT UPDATE ON TABLE GOVERNANCE.INGESTION_RUNS TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER;
