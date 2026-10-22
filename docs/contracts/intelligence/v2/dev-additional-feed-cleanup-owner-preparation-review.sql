-- DATA #132 V166 prerequisite, review only; NOT authorized for execution.
-- Requires the already-installed and handed-off V143 procedure.
-- V166 is applied alone, never as a new initial bootstrap chain.
-- Separate owner approval must bind the exact reviewed V143/V166 source, owner,
-- definition, dependency, ledger and grant readbacks. Stop on any discrepancy.
USE ROLE SECURITYADMIN;
SELECT CURRENT_USER(),CURRENT_ROLE();
SHOW GRANTS ON PROCEDURE ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(VARCHAR,VARCHAR,VARCHAR,VARCHAR);
SHOW GRANTS ON VIEW ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_EXPECTED_HANDOFF_V;
-- MANAGE GRANTS permits these exact object transfers; do not assign the
-- unassigned purge-owner role or broaden the migration service role.
-- REVOKE CURRENT GRANTS closes executor access before replacement and removes
-- the expected-view grant until the reviewed V166 migration recreates it.
GRANT OWNERSHIP ON PROCEDURE ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(VARCHAR,VARCHAR,VARCHAR,VARCHAR)
  TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER REVOKE CURRENT GRANTS;
GRANT OWNERSHIP ON VIEW ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_EXPECTED_HANDOFF_V
  TO ROLE OH_LYME_DEV_MIGRATION_DEPLOYER REVOKE CURRENT GRANTS;
SHOW GRANTS ON PROCEDURE ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(VARCHAR,VARCHAR,VARCHAR,VARCHAR);
SHOW GRANTS ON VIEW ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_EXPECTED_HANDOFF_V;
-- STOP unless exact migration ownership and no executor USAGE are verified.
-- Then dispatch only the separately approved protected V166 migration.
-- Only the separate V166 handoff template may restore the reviewed execution.
