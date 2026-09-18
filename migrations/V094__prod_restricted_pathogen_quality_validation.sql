-- Forward-only aggregate validation for production restricted pathogen rows.
-- It records technical quality evidence without returning restricted source data.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_RECORD_RESTRICTED_PATHOGEN_QUALITY_PROD(
    INGESTION_RUN_ID VARCHAR
)
RETURNS VARIANT LANGUAGE SQL EXECUTE AS OWNER AS
$$
DECLARE invalid_environment EXCEPTION (-20171, 'Restricted pathogen quality validation is PROD-only');
  invalid_run EXCEPTION (-20172, 'Restricted pathogen derivation run is not eligible');
  invalid_rows EXCEPTION (-20173, 'Restricted pathogen rows failed closed quality validation');
  row_count NUMBER; distinct_fips NUMBER; invalid_status_count NUMBER;
BEGIN
  IF (CURRENT_DATABASE() <> 'ONE_HEALTH_LYME_GAP_ATLAS_PROD') THEN RAISE invalid_environment; END IF;
  IF (NOT EXISTS (SELECT 1 FROM GOVERNANCE.INGESTION_RUNS WHERE ingestion_run_id=:INGESTION_RUN_ID AND resource_key='cdc_tick_ixodes_pathogen_status' AND run_mode='RESTRICTED_FULL_PROD' AND status='COMPLETED')) THEN RAISE invalid_run; END IF;
  SELECT COUNT(*), COUNT(DISTINCT county_fips), COUNT_IF(burgdorferi_status NOT IN ('Present','No records'))
    INTO :row_count, :distinct_fips, :invalid_status_count
    FROM CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS
    WHERE ingestion_run_id=:INGESTION_RUN_ID;
  IF (row_count < 1 OR row_count <> distinct_fips OR invalid_status_count <> 0) THEN RAISE invalid_rows; END IF;
  INSERT INTO GOVERNANCE.DATA_QUALITY_RESULTS
  SELECT UUID_STRING(), :INGESTION_RUN_ID, 'restricted_pathogen_source_rows', 'BLOCKING', 'PASSED',
         OBJECT_CONSTRUCT('minimum', 1), OBJECT_CONSTRUCT('observed', :row_count), CURRENT_TIMESTAMP()
  WHERE NOT EXISTS (SELECT 1 FROM GOVERNANCE.DATA_QUALITY_RESULTS WHERE ingestion_run_id=:INGESTION_RUN_ID AND check_name='restricted_pathogen_source_rows');
  INSERT INTO GOVERNANCE.DATA_QUALITY_RESULTS
  SELECT UUID_STRING(), :INGESTION_RUN_ID, 'restricted_pathogen_unique_fips', 'BLOCKING', 'PASSED',
         OBJECT_CONSTRUCT('expected', :row_count), OBJECT_CONSTRUCT('observed', :distinct_fips), CURRENT_TIMESTAMP()
  WHERE NOT EXISTS (SELECT 1 FROM GOVERNANCE.DATA_QUALITY_RESULTS WHERE ingestion_run_id=:INGESTION_RUN_ID AND check_name='restricted_pathogen_unique_fips');
  INSERT INTO GOVERNANCE.DATA_QUALITY_RESULTS
  SELECT UUID_STRING(), :INGESTION_RUN_ID, 'restricted_pathogen_status_values', 'BLOCKING', 'PASSED',
         OBJECT_CONSTRUCT('expected_invalid', 0), OBJECT_CONSTRUCT('observed_invalid', :invalid_status_count), CURRENT_TIMESTAMP()
  WHERE NOT EXISTS (SELECT 1 FROM GOVERNANCE.DATA_QUALITY_RESULTS WHERE ingestion_run_id=:INGESTION_RUN_ID AND check_name='restricted_pathogen_status_values');
  RETURN OBJECT_CONSTRUCT('ingestion_run_id', :INGESTION_RUN_ID, 'quality_checks', 3, 'row_count', :row_count);
END;
$$;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_RECORD_RESTRICTED_PATHOGEN_QUALITY_PROD(VARCHAR) TO ROLE OH_LYME_PROD_RUNTIME;
