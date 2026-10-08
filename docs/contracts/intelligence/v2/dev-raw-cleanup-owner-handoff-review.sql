-- DATA #132/#135: post-V143 DEV security-owner handoff, review only.
-- NOT a migration and NOT authorized for execution by this PR.
-- Run only after V143 is recorded with the reviewed checksum. SECURITYADMIN
-- must have its existing MANAGE GRANTS authority; do not change the migration
-- service role or assign the purge-owner role to any user/service.

USE ROLE SECURITYADMIN;
-- STOP unless a separate migration-service readback has verified the V143
-- ledger row, four-argument SQL EXECUTE AS OWNER definition, and current
-- migration-deployer ownership. SECURITYADMIN need not be granted SELECT on
-- the migration ledger or USAGE on DEV solely for this handoff.
-- Under SECURITYADMIN, verify no outbound procedure grants and the exact
-- purge-owner dependency grants. Use fully qualified names throughout.
-- Also STOP if the procedure is missing or has any unexpected definition,
-- owner, grant, overload, or dependency. Record that preflight externally.
SELECT CURRENT_USER(), CURRENT_ROLE();
SHOW GRANTS ON PROCEDURE ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(
  VARCHAR,VARCHAR,VARCHAR,VARCHAR);
SHOW GRANTS TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER;
SHOW GRANTS TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP;

-- Phase 1: with zero outbound procedure grants, transfer only this procedure.
-- REVOKE CURRENT GRANTS is explicit; it never silently carries an early grant
-- forward. If this statement fails, V143 remains recorded and executor USAGE
-- is still absent. Inspect and retry this phase; do not rerun V143 DDL.
GRANT OWNERSHIP ON PROCEDURE
  ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(VARCHAR,VARCHAR,VARCHAR,VARCHAR)
  TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER REVOKE CURRENT GRANTS;

-- STOP again: read back owner, exact definition, dependencies, and no USAGE.
-- Phase 2 is permitted only after those checks succeed. If this final grant
-- fails, the procedure remains under the intended owner but cannot be called
-- by the cleanup executor; correct the cause and retry only Phase 2.
GRANT USAGE ON PROCEDURE
  ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(VARCHAR,VARCHAR,VARCHAR,VARCHAR)
  TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP;

-- Final readback: exactly OWNERSHIP to purge-owner and USAGE to cleanup role,
-- without grant options or other grantees. Record the grant/definition/owner
-- evidence and run the credential-free plus live cleanup authority preflight.
SHOW GRANTS ON PROCEDURE ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(
  VARCHAR,VARCHAR,VARCHAR,VARCHAR);
