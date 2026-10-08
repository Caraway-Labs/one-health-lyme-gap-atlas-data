-- DATA #132/#135: reviewed DEV security prerequisite for V143.
-- NOT a numbered migration. Do not run through the migration service.
-- Requires the separately governed security administrator and exact owner/grant
-- preflight; no ACCOUNTADMIN or PROD execution is authorized by this file.
-- Apply only after independent approval of the security bootstrap and before
-- dispatching V143. Verify every role/user/object/grant after execution.

CREATE ROLE IF NOT EXISTS OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP;
CREATE ROLE IF NOT EXISTS OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER;

GRANT USAGE ON DATABASE ONE_HEALTH_LYME_GAP_ATLAS_DEV
  TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP;
GRANT USAGE ON SCHEMA ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE
  TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP;
GRANT USAGE ON WAREHOUSE OH_LYME_DEV_INGEST_XS_WH
  TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_CLEANUP;

GRANT USAGE ON DATABASE ONE_HEALTH_LYME_GAP_ATLAS_DEV
  TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER;
GRANT USAGE ON SCHEMA ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE
  TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER;
GRANT SELECT, DELETE ON TABLE
  ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.INGESTION_RUN_PAYLOADS
  TO ROLE OH_LYME_DEV_INTELLIGENCE_RAW_PURGE_OWNER;

-- Separately provision a dedicated cleanup service user, scoped PAT, and
-- DEV Spaces delete credential. Grant the cleanup role only to that service
-- user; never grant the purge-owner role to a user or the ingestion runtime.
-- The migration/approval service remains separate and is the sole approver.
