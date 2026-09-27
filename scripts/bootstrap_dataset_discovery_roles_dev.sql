-- Reviewed account-level DEV bootstrap for ADR 0041. Execute once with an
-- explicitly authorized administrative named snow connection after verifying
-- CURRENT_USER/ROLE/DATABASE/WAREHOUSE. This is not a schema migration:
-- the protected migration role lacks account CREATE ROLE and READ SESSION.
-- Never use this file for PROD or assign runtime/reviewer to a user here.

CREATE ROLE IF NOT EXISTS OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME;
CREATE ROLE IF NOT EXISTS OH_LYME_DEV_DATASET_DISCOVERY_REVIEWER;
CREATE ROLE IF NOT EXISTS OH_LYME_DEV_DATASET_DISCOVERY_WRITE_OWNER;

-- Only the non-login procedure owner may inspect the invoking session in
-- owner-rights review/handoff procedures. Runtime and reviewer get no READ SESSION.
GRANT READ SESSION ON ACCOUNT
  TO ROLE OH_LYME_DEV_DATASET_DISCOVERY_WRITE_OWNER;

-- Snowflake requires the ownership-transfer target to be in the deployer's
-- active role hierarchy. Do not grant this role to routine users or services.
GRANT ROLE OH_LYME_DEV_DATASET_DISCOVERY_WRITE_OWNER
  TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER;
