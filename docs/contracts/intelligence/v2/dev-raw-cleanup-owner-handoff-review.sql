-- DATA #132/#135: post-V143 DEV security-owner handoff, review only.
-- NOT a migration and NOT authorized for execution by this PR.
-- Run only after V143 is recorded with the reviewed checksum. SECURITYADMIN
-- must have its existing MANAGE GRANTS authority; do not change the migration
-- service role or assign the purge-owner role to any user/service.

USE ROLE SECURITYADMIN;
-- STOP unless a separate migration-service owner readback has verified the
-- V143 ledger row, four-argument SQL EXECUTE AS OWNER definition, current
-- migration-deployer ownership, and exact procedure body SHA256 against the
-- reviewed V143 source. SECURITYADMIN does not need ledger SELECT or owner-
-- only definition access; it receives narrow DEV container USAGE and SELECT,
-- INSERT on only the handoff-attestation table.
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

-- STOP again: read back owner, creation timestamp, dependencies, and no USAGE.
-- The reviewed definition binding is the migration owner's pre-transfer hash;
-- SECURITYADMIN cannot claim an owner-only post-transfer source readback.
-- Phase 2 is permitted only after those checks succeed. If this final grant
-- fails, the procedure remains under the intended owner but cannot be called
-- by the cleanup executor; correct the cause and retry only Phase 2.
GRANT USAGE ON PROCEDURE
  ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(VARCHAR,VARCHAR,VARCHAR,VARCHAR)
  TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP;

-- Final readback: exactly OWNERSHIP to purge-owner and USAGE to cleanup role,
-- without executor grant options or other grantees. Record the grant/owner
-- evidence. SHOW PROCEDURES is visible to SECURITYADMIN through MANAGE GRANTS.
SHOW GRANTS ON PROCEDURE ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(
  VARCHAR,VARCHAR,VARCHAR,VARCHAR);

-- STOP unless the prior owner-only body readback and current owner/grants match
-- the reviewed evidence. One immutable security-attested row binds the exact
-- migration/body hashes to this physical procedure's creation timestamp.
-- Fill the independently approved HANDOFF_REF in a private reviewed copy;
-- no arbitrary ref or second attestation is permitted. CREATE OR REPLACE
-- changes created_on, invalidating cleanup; EXECUTE AS CALLER also fails the
-- procedure's INVOKER_ROLE self-gate.
SHOW PROCEDURES LIKE 'PURGE_INTELLIGENCE_RAW_CHECKPOINT'
  IN SCHEMA ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE;
INSERT INTO ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_HANDOFF_ATTESTATIONS
  (MIGRATION_SHA256,PROCEDURE_BODY_SHA256,PROCEDURE_CREATED_ON,OWNER_ROLE,
   HANDOFF_REF,ATTESTED_BY)
SELECT 'e2b1b78e6d85eb76dd8e6768e0afdff6fbe3fa9b4a5ced40984eeb575f94445f',
       '0c86fff943120bad10d05a3baa45e8ce31fe0f7c19e74bc1ce1b5bee7723cf53',
       "created_on"::TIMESTAMP_LTZ,
       'OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER',
       '{{ APPROVED_HANDOFF_REF }}', CURRENT_USER()
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
WHERE "name"='PURGE_INTELLIGENCE_RAW_CHECKPOINT'
  AND "catalog_name"='ONE_HEALTH_LYME_GAP_ATLAS_DEV'
  AND "schema_name"='GOVERNANCE'
  AND "min_num_arguments"=4 AND "max_num_arguments"=4
  AND NOT EXISTS (
    SELECT 1 FROM ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_HANDOFF_ATTESTATIONS
  )
QUALIFY COUNT(*) OVER ()=1;

-- The post-handoff cleanup service must read back exactly one attestation,
-- matching SHOW PROCEDURES created_on, owner grant, and exact executor USAGE.
-- Zero inserted rows or a mismatch is a failed handoff, never authorization.
