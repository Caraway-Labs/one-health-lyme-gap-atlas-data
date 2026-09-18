-- Production source-faithful derivation for the requestor-restricted Ixodes workbook.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS RAW.RESTRICTED_CDC_TICK_WORKBOOK_ROWS (
  restricted_row_id VARCHAR PRIMARY KEY, ingestion_run_id VARCHAR NOT NULL,
  evidence_run_id VARCHAR NOT NULL, workbook_sha256 VARCHAR(64) NOT NULL,
  source_row_number NUMBER NOT NULL, source_row_hash VARCHAR(64) NOT NULL,
  source_payload VARIANT NOT NULL, retrieved_at TIMESTAMP_LTZ NOT NULL,
  loaded_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
CREATE TABLE IF NOT EXISTS STAGING.RESTRICTED_CDC_TICK_WORKBOOK_ROWS (
  restricted_row_id VARCHAR PRIMARY KEY, ingestion_run_id VARCHAR NOT NULL,
  evidence_run_id VARCHAR NOT NULL, county_fips VARCHAR(5) NOT NULL,
  source_row_hash VARCHAR(64) NOT NULL, normalized_payload VARIANT NOT NULL,
  retrieved_at TIMESTAMP_LTZ NOT NULL, normalized_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
CREATE TABLE IF NOT EXISTS CONFORMED.RESTRICTED_CDC_TICK_COUNTY_STATUS (
  conformed_record_id VARCHAR PRIMARY KEY, resource_key VARCHAR NOT NULL,
  source_definition_version NUMBER NOT NULL, ingestion_run_id VARCHAR NOT NULL,
  evidence_run_id VARCHAR NOT NULL, source_record_id VARCHAR NOT NULL,
  source_row_hash VARCHAR(64) NOT NULL, county_fips VARCHAR(5) NOT NULL,
  scapularis_status VARCHAR NOT NULL, pacificus_status VARCHAR NOT NULL,
  coverage_state VARCHAR NOT NULL, workbook_sha256 VARCHAR(64) NOT NULL,
  retrieved_at TIMESTAMP_LTZ NOT NULL, conformed_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_LOAD_RESTRICTED_TICK_PROD(
  INGESTION_RUN_ID VARCHAR, EVIDENCE_RUN_ID VARCHAR, WORKBOOK_SHA256 VARCHAR, RAW_ROWS VARIANT, RETRIEVED_AT TIMESTAMP_LTZ
) RETURNS VARIANT LANGUAGE SQL EXECUTE AS OWNER AS
$$
DECLARE invalid_environment EXCEPTION (-20141, 'Restricted tick derivation is PROD-only');
  invalid_input EXCEPTION (-20142, 'Restricted tick derivation input is invalid');
  missing_evidence EXCEPTION (-20143, 'Approved restricted evidence was not found');
  missing_approval EXCEPTION (-20144, 'No approved restricted tick source version exists');
  invalid_rows EXCEPTION (-20145, 'Restricted tick rows failed closed validation');
  row_count NUMBER; distinct_fips NUMBER; invalid_count NUMBER; source_version_id VARCHAR;
BEGIN
  IF (CURRENT_DATABASE() <> 'ONE_HEALTH_LYME_GAP_ATLAS_PROD') THEN RAISE invalid_environment; END IF;
  IF (INGESTION_RUN_ID IS NULL OR EVIDENCE_RUN_ID IS NULL OR NOT REGEXP_LIKE(WORKBOOK_SHA256,'^[0-9a-f]{64}$') OR RAW_ROWS IS NULL OR RETRIEVED_AT IS NULL) THEN RAISE invalid_input; END IF;
  IF (NOT EXISTS (SELECT 1 FROM GOVERNANCE.RAW_ARTIFACTS WHERE ingestion_run_id=:EVIDENCE_RUN_ID AND artifact_type='SOURCE_WORKBOOK_EVIDENCE' AND sha256=:WORKBOOK_SHA256)) THEN RAISE missing_evidence; END IF;
  SELECT data_source_version_id INTO :source_version_id FROM GOVERNANCE.DATA_SOURCE_VERSIONS WHERE resource_key='cdc_tick_ixodes_county_status' AND status IN ('APPROVED','CONDITIONAL') AND retired_at IS NULL QUALIFY ROW_NUMBER() OVER (ORDER BY created_at DESC)=1;
  IF (source_version_id IS NULL) THEN RAISE missing_approval; END IF;
  SELECT COUNT(*),COUNT(DISTINCT value:fips::VARCHAR) INTO :row_count,:distinct_fips FROM TABLE(FLATTEN(INPUT=>:RAW_ROWS));
  SELECT COUNT(*) INTO :invalid_count FROM TABLE(FLATTEN(INPUT=>:RAW_ROWS)) WHERE NOT REGEXP_LIKE(value:fips::VARCHAR,'^[0-9]{5}$') OR value:scapularis_status::VARCHAR NOT IN ('Established','Reported','No records') OR value:pacificus_status::VARCHAR NOT IN ('Established','Reported','No records') OR NOT REGEXP_LIKE(value:source_row_hash::VARCHAR,'^[0-9a-f]{64}$');
  IF (row_count<1 OR row_count<>distinct_fips OR invalid_count<>0) THEN RAISE invalid_rows; END IF;
  BEGIN TRANSACTION;
  INSERT INTO RAW.RESTRICTED_CDC_TICK_WORKBOOK_ROWS SELECT UUID_STRING(),:INGESTION_RUN_ID,:EVIDENCE_RUN_ID,:WORKBOOK_SHA256,value:source_row_number::NUMBER,value:source_row_hash::VARCHAR,value:raw,:RETRIEVED_AT,CURRENT_TIMESTAMP() FROM TABLE(FLATTEN(INPUT=>:RAW_ROWS));
  INSERT INTO STAGING.RESTRICTED_CDC_TICK_WORKBOOK_ROWS SELECT UUID_STRING(),:INGESTION_RUN_ID,:EVIDENCE_RUN_ID,value:fips::VARCHAR,value:source_row_hash::VARCHAR,OBJECT_CONSTRUCT('fips',value:fips::VARCHAR,'scapularis_status',value:scapularis_status::VARCHAR,'pacificus_status',value:pacificus_status::VARCHAR),:RETRIEVED_AT,CURRENT_TIMESTAMP() FROM TABLE(FLATTEN(INPUT=>:RAW_ROWS));
  INSERT INTO CONFORMED.RESTRICTED_CDC_TICK_COUNTY_STATUS SELECT UUID_STRING(),'cdc_tick_ixodes_county_status',1,:INGESTION_RUN_ID,:EVIDENCE_RUN_ID,value:fips::VARCHAR,value:source_row_hash::VARCHAR,value:fips::VARCHAR,value:scapularis_status::VARCHAR,value:pacificus_status::VARCHAR,'REPORTED',:WORKBOOK_SHA256,:RETRIEVED_AT,CURRENT_TIMESTAMP() FROM TABLE(FLATTEN(INPUT=>:RAW_ROWS));
  INSERT INTO GOVERNANCE.INGESTION_REQUESTS SELECT UUID_STRING(),:INGESTION_RUN_ID,1,'PRIVATE_OPERATOR_VERIFIED_WORKBOOK','restricted://cdc-arbonet/tick-workbook',OBJECT_CONSTRUCT('evidence_run_id',:EVIDENCE_RUN_ID,'workbook_sha256',:WORKBOOK_SHA256,'transport','PRIVATE_OPERATOR_ENVELOPE'),NULL,:WORKBOOK_SHA256,:row_count,CURRENT_TIMESTAMP();
  INSERT INTO GOVERNANCE.DATA_QUALITY_RESULTS SELECT UUID_STRING(),:INGESTION_RUN_ID,'restricted_tick_source_rows','BLOCKING','PASSED',OBJECT_CONSTRUCT('minimum',1),OBJECT_CONSTRUCT('observed',:row_count),CURRENT_TIMESTAMP()
  UNION ALL SELECT UUID_STRING(),:INGESTION_RUN_ID,'restricted_tick_unique_fips','BLOCKING','PASSED',OBJECT_CONSTRUCT('expected',:row_count),OBJECT_CONSTRUCT('observed',:distinct_fips),CURRENT_TIMESTAMP();
  INSERT INTO GOVERNANCE.INGESTION_PUBLICATIONS SELECT UUID_STRING(),'cdc_tick_ixodes_county_status',:INGESTION_RUN_ID,1,'STAGED','CONFORMED.RESTRICTED_CDC_TICK_COUNTY_STATUS',:row_count,OBJECT_CONSTRUCT('source_version_id',:source_version_id,'eligibility','DERIVED_COUNTY_STATUS_ONLY_PENDING_FINAL_COPY'),CURRENT_TIMESTAMP();
  UPDATE GOVERNANCE.INGESTION_RUNS SET status='COMPLETED',completed_at=CURRENT_TIMESTAMP() WHERE ingestion_run_id=:INGESTION_RUN_ID;
  COMMIT;
  RETURN OBJECT_CONSTRUCT('ingestion_run_id',:INGESTION_RUN_ID,'source_version_id',:source_version_id,'conformed_count',:row_count,'semantic_release_state','PENDING_FINAL_COPY');
EXCEPTION WHEN OTHER THEN ROLLBACK; UPDATE GOVERNANCE.INGESTION_RUNS SET status='FAILED',completed_at=CURRENT_TIMESTAMP(),error_classification='RESTRICTED_TICK_DERIVATION_FAILED',redacted_error='Restricted tick derivation failed; inspect owner-controlled evidence.' WHERE ingestion_run_id=:INGESTION_RUN_ID; RAISE;
END;
$$;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_LOAD_RESTRICTED_TICK_PROD(VARCHAR,VARCHAR,VARCHAR,VARIANT,TIMESTAMP_LTZ) TO ROLE OH_LYME_PROD_RUNTIME;
