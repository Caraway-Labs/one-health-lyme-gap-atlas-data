USE DATABASE {{ DATABASE }};

-- The scheduled worker needs a dedicated auto-suspending warehouse plus the
-- database-level usage prerequisite for its existing, schema-scoped grants.
-- This does not grant approval-console, steward, or Alpha POC access.
CREATE ROLE IF NOT EXISTS OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
CREATE WAREHOUSE IF NOT EXISTS OH_LYME_{{ ENV }}_INGEST_XS_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE;
GRANT USAGE ON DATABASE {{ DATABASE }} TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT USAGE ON WAREHOUSE OH_LYME_{{ ENV }}_INGEST_XS_WH
  TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
