-- Forward-only private-envelope retrieval evidence for the production
-- restricted pathogen derivation.  It records only immutable identifiers and
-- aggregate row count; it never returns source rows or workbook bytes.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_RECORD_RESTRICTED_PATHOGEN_RETRIEVAL_PROD(
    INGESTION_RUN_ID VARCHAR
)
RETURNS VARIANT LANGUAGE SQL EXECUTE AS OWNER AS
$$
DECLARE invalid_environment EXCEPTION (-20181, 'Restricted pathogen retrieval evidence is PROD-only');
  invalid_run EXCEPTION (-20182, 'Restricted pathogen derivation run is not eligible');
  invalid_lineage EXCEPTION (-20183, 'Restricted pathogen retrieval lineage is not singular and retained');
  evidence_run_id VARCHAR; workbook_sha256 VARCHAR; retrieved_at TIMESTAMP_LTZ;
  row_count NUMBER; evidence_count NUMBER; workbook_count NUMBER; retrieval_count NUMBER;
BEGIN
  IF (CURRENT_DATABASE() <> 'ONE_HEALTH_LYME_GAP_ATLAS_PROD') THEN RAISE invalid_environment; END IF;
  IF (NOT EXISTS (SELECT 1 FROM GOVERNANCE.INGESTION_RUNS WHERE ingestion_run_id=:INGESTION_RUN_ID AND resource_key='cdc_tick_ixodes_pathogen_status' AND run_mode='RESTRICTED_FULL_PROD' AND status='COMPLETED')) THEN RAISE invalid_run; END IF;
  SELECT MIN(evidence_run_id), MIN(workbook_sha256), MIN(retrieved_at), COUNT(*),
         COUNT(DISTINCT evidence_run_id), COUNT(DISTINCT workbook_sha256), COUNT(DISTINCT retrieved_at)
    INTO :evidence_run_id, :workbook_sha256, :retrieved_at, :row_count,
         :evidence_count, :workbook_count, :retrieval_count
    FROM CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS
    WHERE ingestion_run_id=:INGESTION_RUN_ID;
  IF (row_count < 1 OR evidence_count <> 1 OR workbook_count <> 1 OR retrieval_count <> 1
      OR NOT EXISTS (SELECT 1 FROM GOVERNANCE.RAW_ARTIFACTS WHERE ingestion_run_id=:evidence_run_id AND artifact_type='SOURCE_WORKBOOK_EVIDENCE' AND sha256=:workbook_sha256)) THEN RAISE invalid_lineage; END IF;
  INSERT INTO GOVERNANCE.INGESTION_REQUESTS
  SELECT UUID_STRING(), :INGESTION_RUN_ID, 1, 'PRIVATE_OPERATOR_VERIFIED_WORKBOOK',
         'restricted://cdc-arbonet/pathogen-workbook',
         OBJECT_CONSTRUCT('evidence_run_id', :evidence_run_id, 'workbook_sha256', :workbook_sha256, 'transport', 'PRIVATE_OPERATOR_ENVELOPE'),
         NULL, :workbook_sha256, :row_count, :retrieved_at
  WHERE NOT EXISTS (SELECT 1 FROM GOVERNANCE.INGESTION_REQUESTS WHERE ingestion_run_id=:INGESTION_RUN_ID AND request_purpose='PRIVATE_OPERATOR_VERIFIED_WORKBOOK');
  RETURN OBJECT_CONSTRUCT('ingestion_run_id', :INGESTION_RUN_ID, 'evidence_run_id', :evidence_run_id, 'row_count', :row_count);
END;
$$;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_RECORD_RESTRICTED_PATHOGEN_RETRIEVAL_PROD(VARCHAR) TO ROLE OH_LYME_PROD_RUNTIME;
