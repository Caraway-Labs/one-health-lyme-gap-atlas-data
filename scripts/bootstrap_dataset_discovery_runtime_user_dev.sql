-- Account-level, DEV-only identity bootstrap for ADR 0041. Run with the
-- explicitly authorized administrative connection after identity preflight.
-- This does not create a token or place credential material in Snowflake DDL.
-- The service user receives exactly the Dataset Discovery runtime role.

CREATE USER IF NOT EXISTS OH_LYME_DEV_DATASET_DISCOVERY_SVC
  TYPE = SERVICE
  DEFAULT_ROLE = OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME
  DEFAULT_WAREHOUSE = OH_LYME_DEV_INGEST_XS_WH
  DEFAULT_NAMESPACE = ONE_HEALTH_LYME_GAP_ATLAS_DEV.DATASET_DISCOVERY
  COMMENT = 'DEV Dataset Discovery recommendation runtime only';

GRANT ROLE OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME
  TO USER OH_LYME_DEV_DATASET_DISCOVERY_SVC;
