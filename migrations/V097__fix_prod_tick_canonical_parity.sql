-- V093 counted all source rows.  Count only canonical SVI county identities so
-- source-scope extras cannot understate unresolved canonical coverage.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_CLASSIFY_RESTRICTED_TICK_PARITY_PROD(
    INGESTION_RUN_ID VARCHAR, RATIONALE VARCHAR, APPROVED_BY VARCHAR
)
RETURNS VARIANT LANGUAGE SQL EXECUTE AS OWNER AS
$$
DECLARE invalid_environment EXCEPTION (-20161, 'Restricted tick parity classification is PROD-only');
  invalid_input EXCEPTION (-20162, 'Parity classification rationale and approver are required');
  invalid_run EXCEPTION (-20163, 'Restricted tick derivation run is not eligible');
  canonical_count NUMBER; reported_count NUMBER; source_version_id VARCHAR; classification_id VARCHAR DEFAULT UUID_STRING();
BEGIN
  IF (CURRENT_DATABASE() <> 'ONE_HEALTH_LYME_GAP_ATLAS_PROD') THEN RAISE invalid_environment; END IF;
  IF (INGESTION_RUN_ID IS NULL OR LENGTH(TRIM(RATIONALE)) < 10 OR NULLIF(TRIM(APPROVED_BY), '') IS NULL) THEN RAISE invalid_input; END IF;
  IF (NOT EXISTS (SELECT 1 FROM GOVERNANCE.INGESTION_RUNS WHERE ingestion_run_id=:INGESTION_RUN_ID AND resource_key='cdc_tick_ixodes_county_status' AND run_mode='RESTRICTED_FULL_PROD' AND status='COMPLETED')) THEN RAISE invalid_run; END IF;
  SELECT COUNT(*), COUNT(t.county_fips)
    INTO :canonical_count, :reported_count
    FROM (
      SELECT DISTINCT payload:record:STCNTY::VARCHAR AS county_fips
      FROM CONFORMED.GOVERNED_SOURCE_RECORDS
      WHERE resource_key='cdc_atsdr_svi_2022_county'
    ) canonical
    LEFT JOIN (
      SELECT DISTINCT county_fips
      FROM CONFORMED.RESTRICTED_CDC_TICK_COUNTY_STATUS
      WHERE ingestion_run_id=:INGESTION_RUN_ID
    ) t ON t.county_fips=canonical.county_fips;
  SELECT data_source_version_id INTO :source_version_id FROM GOVERNANCE.DATA_SOURCE_VERSIONS WHERE resource_key='cdc_tick_ixodes_county_status' AND status IN ('APPROVED','CONDITIONAL') AND retired_at IS NULL QUALIFY ROW_NUMBER() OVER (ORDER BY created_at DESC)=1;
  IF (canonical_count <> 3144 OR reported_count < 1 OR reported_count >= canonical_count OR source_version_id IS NULL) THEN RAISE invalid_run; END IF;
  INSERT INTO GOVERNANCE.RESTRICTED_TICK_PARITY_CLASSIFICATIONS
  VALUES (:classification_id, 'cdc_tick_ixodes_county_status', :source_version_id, :INGESTION_RUN_ID, :canonical_count, :reported_count, :canonical_count-:reported_count, 'UNKNOWN_SOURCE_COVERAGE', :RATIONALE, :APPROVED_BY, CURRENT_TIMESTAMP());
  RETURN OBJECT_CONSTRUCT('classification_id', :classification_id, 'reported_count', :reported_count, 'unresolved_count', :canonical_count-:reported_count, 'classification', 'UNKNOWN_SOURCE_COVERAGE');
END;
$$;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_CLASSIFY_RESTRICTED_TICK_PARITY_PROD(VARCHAR, VARCHAR, VARCHAR) TO ROLE OH_LYME_PROD_STREAMLIT_OWNER;
