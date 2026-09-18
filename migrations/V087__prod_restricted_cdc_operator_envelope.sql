-- Epic #252: restricted CDC workbook production boundary.  The runtime may
-- execute these procedures but cannot SELECT raw, staging, or conformed rows.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS RAW.RESTRICTED_CDC_PATHOGEN_WORKBOOK_ROWS (
  restricted_row_id VARCHAR PRIMARY KEY, ingestion_run_id VARCHAR NOT NULL,
  evidence_run_id VARCHAR NOT NULL, workbook_sha256 VARCHAR(64) NOT NULL,
  source_row_number NUMBER NOT NULL, source_row_hash VARCHAR(64) NOT NULL,
  source_payload VARIANT NOT NULL, retrieved_at TIMESTAMP_LTZ NOT NULL,
  loaded_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
CREATE TABLE IF NOT EXISTS STAGING.RESTRICTED_CDC_PATHOGEN_WORKBOOK_ROWS (
  restricted_row_id VARCHAR PRIMARY KEY, ingestion_run_id VARCHAR NOT NULL,
  evidence_run_id VARCHAR NOT NULL, county_fips VARCHAR(5) NOT NULL,
  source_row_hash VARCHAR(64) NOT NULL, normalized_payload VARIANT NOT NULL,
  retrieved_at TIMESTAMP_LTZ NOT NULL, normalized_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
CREATE TABLE IF NOT EXISTS CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS (
  conformed_record_id VARCHAR PRIMARY KEY, resource_key VARCHAR NOT NULL,
  source_definition_version NUMBER NOT NULL, ingestion_run_id VARCHAR NOT NULL,
  evidence_run_id VARCHAR NOT NULL, source_record_id VARCHAR NOT NULL,
  source_row_hash VARCHAR(64) NOT NULL, county_fips VARCHAR(5) NOT NULL,
  burgdorferi_status VARCHAR NOT NULL, coverage_state VARCHAR NOT NULL,
  workbook_sha256 VARCHAR(64) NOT NULL, retrieved_at TIMESTAMP_LTZ NOT NULL,
  conformed_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS (
  attestation_id VARCHAR PRIMARY KEY, semantic_release_id VARCHAR NOT NULL,
  resource_key VARCHAR NOT NULL, data_source_version_id VARCHAR NOT NULL,
  delivery_reference VARCHAR NOT NULL, delivered_at TIMESTAMP_LTZ NOT NULL,
  attested_by VARCHAR NOT NULL, attested_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_RECORD_RESTRICTED_SOURCE_REVIEW_PROD(
  RESOURCE_KEY VARCHAR, DECISION VARCHAR, RATIONALE VARCHAR, CONDITIONS VARIANT,
  REVIEWER_USERNAME VARCHAR, APP_VERSION VARCHAR, CORRELATION_ID VARCHAR
) RETURNS VARIANT LANGUAGE SQL EXECUTE AS OWNER AS
$$
DECLARE invalid_resource EXCEPTION (-20121, 'Only the two reviewed restricted CDC sources are accepted');
  invalid_input EXCEPTION (-20122, 'A supported approval and complete review metadata are required');
  incomplete_evidence EXCEPTION (-20123, 'Restricted-source approval requires completed private evidence');
  unauthorized EXCEPTION (-20124, 'Reviewer is not an active global steward');
  evidence_count NUMBER; steward_count NUMBER; decision_id VARCHAR DEFAULT UUID_STRING(); source_version_id VARCHAR DEFAULT UUID_STRING();
BEGIN
  IF (RESOURCE_KEY NOT IN ('cdc_tick_ixodes_county_status','cdc_tick_ixodes_pathogen_status')) THEN RAISE invalid_resource; END IF;
  IF (DECISION NOT IN ('APPROVED','APPROVED_WITH_CONDITIONS') OR LENGTH(TRIM(RATIONALE)) < 10
      OR CONDITIONS IS NULL OR NOT IS_ARRAY(CONDITIONS) OR ARRAY_SIZE(CONDITIONS)=0
      OR NULLIF(TRIM(REVIEWER_USERNAME),'') IS NULL OR NULLIF(TRIM(APP_VERSION),'') IS NULL
      OR NULLIF(TRIM(CORRELATION_ID),'') IS NULL) THEN RAISE invalid_input; END IF;
  SELECT COUNT(*) INTO :steward_count FROM GOVERNANCE.APPROVAL_STEWARDS
    WHERE username=:REVIEWER_USERNAME AND is_active=TRUE AND authorization_scope='GLOBAL';
  IF (steward_count <> 1) THEN RAISE unauthorized; END IF;
  SELECT COUNT(*) INTO :evidence_count FROM GOVERNANCE.INGESTION_RUNS r
    WHERE r.resource_key=:RESOURCE_KEY AND r.run_mode='EVIDENCE_ONLY' AND r.status='COMPLETED'
    AND EXISTS (SELECT 1 FROM GOVERNANCE.RAW_ARTIFACTS a WHERE a.ingestion_run_id=r.ingestion_run_id AND a.artifact_type='SOURCE_WORKBOOK_EVIDENCE')
    AND EXISTS (SELECT 1 FROM GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS d WHERE d.resource_key=:RESOURCE_KEY)
    AND EXISTS (SELECT 1 FROM GOVERNANCE.SCHEMA_SNAPSHOTS s WHERE s.resource_key=:RESOURCE_KEY);
  IF (evidence_count < 1) THEN RAISE incomplete_evidence; END IF;
  UPDATE GOVERNANCE.DATA_SOURCE_VERSIONS SET status='RETIRED', retired_at=CURRENT_TIMESTAMP()
    WHERE resource_key=:RESOURCE_KEY AND retired_at IS NULL AND status IN ('APPROVED','CONDITIONAL');
  INSERT INTO GOVERNANCE.DATA_SOURCE_VERSIONS(data_source_version_id,resource_key,status,approved_decision_id,created_at)
    VALUES(:source_version_id,:RESOURCE_KEY,IFF(:DECISION='APPROVED','APPROVED','CONDITIONAL'),:decision_id,CURRENT_TIMESTAMP());
  INSERT INTO GOVERNANCE.MANUAL_REVIEW_DECISIONS(manual_review_decision_id,resource_key,decision,rationale,conditions,reviewer_username,data_source_version_id,app_version,correlation_id,decided_at)
    VALUES(:decision_id,:RESOURCE_KEY,:DECISION,:RATIONALE,:CONDITIONS,:REVIEWER_USERNAME,:source_version_id,:APP_VERSION,:CORRELATION_ID,CURRENT_TIMESTAMP());
  RETURN OBJECT_CONSTRUCT('decision_id',:decision_id,'source_version_id',:source_version_id);
END;
$$;

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_LOAD_RESTRICTED_PATHOGEN_PROD(
  INGESTION_RUN_ID VARCHAR, EVIDENCE_RUN_ID VARCHAR, WORKBOOK_SHA256 VARCHAR, RAW_ROWS VARIANT, RETRIEVED_AT TIMESTAMP_LTZ
) RETURNS VARIANT LANGUAGE SQL EXECUTE AS OWNER AS
$$
DECLARE invalid_environment EXCEPTION (-20131, 'Restricted pathogen derivation is PROD-only');
  invalid_input EXCEPTION (-20132, 'Restricted pathogen derivation input is invalid');
  missing_evidence EXCEPTION (-20133, 'Approved restricted evidence was not found');
  missing_approval EXCEPTION (-20134, 'No approved restricted pathogen source version exists');
  invalid_rows EXCEPTION (-20135, 'Restricted pathogen rows failed closed validation');
  row_count NUMBER; distinct_fips NUMBER; invalid_count NUMBER; source_version_id VARCHAR;
BEGIN
  IF (CURRENT_DATABASE() <> 'ONE_HEALTH_LYME_GAP_ATLAS_PROD') THEN RAISE invalid_environment; END IF;
  IF (INGESTION_RUN_ID IS NULL OR EVIDENCE_RUN_ID IS NULL OR NOT REGEXP_LIKE(WORKBOOK_SHA256,'^[0-9a-f]{64}$') OR RAW_ROWS IS NULL OR RETRIEVED_AT IS NULL) THEN RAISE invalid_input; END IF;
  IF (NOT EXISTS (SELECT 1 FROM GOVERNANCE.RAW_ARTIFACTS WHERE ingestion_run_id=:EVIDENCE_RUN_ID AND artifact_type='SOURCE_WORKBOOK_EVIDENCE' AND sha256=:WORKBOOK_SHA256)) THEN RAISE missing_evidence; END IF;
  SELECT data_source_version_id INTO :source_version_id FROM GOVERNANCE.DATA_SOURCE_VERSIONS WHERE resource_key='cdc_tick_ixodes_pathogen_status' AND status IN ('APPROVED','CONDITIONAL') AND retired_at IS NULL QUALIFY ROW_NUMBER() OVER (ORDER BY created_at DESC)=1;
  IF (source_version_id IS NULL) THEN RAISE missing_approval; END IF;
  SELECT COUNT(*),COUNT(DISTINCT value:fips::VARCHAR) INTO :row_count,:distinct_fips FROM TABLE(FLATTEN(INPUT=>:RAW_ROWS));
  SELECT COUNT(*) INTO :invalid_count FROM TABLE(FLATTEN(INPUT=>:RAW_ROWS)) WHERE NOT REGEXP_LIKE(value:fips::VARCHAR,'^[0-9]{5}$') OR value:burgdorferi_status::VARCHAR NOT IN ('Present','No records') OR NOT REGEXP_LIKE(value:source_row_hash::VARCHAR,'^[0-9a-f]{64}$');
  IF (row_count<1 OR row_count<>distinct_fips OR invalid_count<>0) THEN RAISE invalid_rows; END IF;
  BEGIN TRANSACTION;
  INSERT INTO RAW.RESTRICTED_CDC_PATHOGEN_WORKBOOK_ROWS SELECT UUID_STRING(),:INGESTION_RUN_ID,:EVIDENCE_RUN_ID,:WORKBOOK_SHA256,value:source_row_number::NUMBER,value:source_row_hash::VARCHAR,value:raw,:RETRIEVED_AT,CURRENT_TIMESTAMP() FROM TABLE(FLATTEN(INPUT=>:RAW_ROWS));
  INSERT INTO STAGING.RESTRICTED_CDC_PATHOGEN_WORKBOOK_ROWS SELECT UUID_STRING(),:INGESTION_RUN_ID,:EVIDENCE_RUN_ID,value:fips::VARCHAR,value:source_row_hash::VARCHAR,OBJECT_CONSTRUCT('fips',value:fips::VARCHAR,'burgdorferi_status',value:burgdorferi_status::VARCHAR),:RETRIEVED_AT,CURRENT_TIMESTAMP() FROM TABLE(FLATTEN(INPUT=>:RAW_ROWS));
  INSERT INTO CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS SELECT UUID_STRING(),'cdc_tick_ixodes_pathogen_status',1,:INGESTION_RUN_ID,:EVIDENCE_RUN_ID,value:fips::VARCHAR,value:source_row_hash::VARCHAR,value:fips::VARCHAR,value:burgdorferi_status::VARCHAR,'REPORTED',:WORKBOOK_SHA256,:RETRIEVED_AT,CURRENT_TIMESTAMP() FROM TABLE(FLATTEN(INPUT=>:RAW_ROWS));
  INSERT INTO GOVERNANCE.INGESTION_PUBLICATIONS SELECT UUID_STRING(),'cdc_tick_ixodes_pathogen_status',:INGESTION_RUN_ID,1,'STAGED','CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS',:row_count,OBJECT_CONSTRUCT('source_version_id',:source_version_id,'eligibility','PENDING_PARITY_AND_FINAL_COPY'),CURRENT_TIMESTAMP();
  UPDATE GOVERNANCE.INGESTION_RUNS SET status='COMPLETED',completed_at=CURRENT_TIMESTAMP() WHERE ingestion_run_id=:INGESTION_RUN_ID;
  COMMIT;
  RETURN OBJECT_CONSTRUCT('ingestion_run_id',:INGESTION_RUN_ID,'source_version_id',:source_version_id,'conformed_count',:row_count,'semantic_release_state','PENDING_PARITY_AND_FINAL_COPY');
EXCEPTION WHEN OTHER THEN ROLLBACK; UPDATE GOVERNANCE.INGESTION_RUNS SET status='FAILED',completed_at=CURRENT_TIMESTAMP(),error_classification='RESTRICTED_PATHOGEN_DERIVATION_FAILED',redacted_error='Restricted pathogen derivation failed; inspect owner-controlled evidence.' WHERE ingestion_run_id=:INGESTION_RUN_ID; RAISE;
END;
$$;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_RECORD_RESTRICTED_SOURCE_REVIEW_PROD(VARCHAR,VARCHAR,VARCHAR,VARIANT,VARCHAR,VARCHAR,VARCHAR) TO ROLE OH_LYME_PROD_STREAMLIT_OWNER;
GRANT USAGE ON PROCEDURE GOVERNANCE.SP_LOAD_RESTRICTED_PATHOGEN_PROD(VARCHAR,VARCHAR,VARCHAR,VARIANT,TIMESTAMP_LTZ) TO ROLE OH_LYME_PROD_RUNTIME;
