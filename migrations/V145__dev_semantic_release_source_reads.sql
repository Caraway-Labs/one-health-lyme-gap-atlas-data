-- DATA #443: verify the exact DEV-only reads for the protected release builder.
-- The view is owned by OH_LYME_DEV_RUNTIME, not the migration deployer.
-- A qualified grant owner must apply the three approved object grants before
-- this migration records their successful readback in the DEV ledger.
USE DATABASE {{ DATABASE }};

SELECT 1 FROM CONFORMED.CONFORMED_CDC_LYME_X5J9_WYBP LIMIT 0;
SELECT 1 FROM CONFORMED.GOVERNED_SOURCE_RECORDS LIMIT 0;
SELECT 1 FROM CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS LIMIT 0;
