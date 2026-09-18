-- Epic #252: preserve the reviewed signature while avoiding SQL Scripting's
-- VARIANT-in-VALUES binding defect under caller rights.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_RECORD_RESTRICTED_SOURCE_REVIEW_PROD(
  RESOURCE_KEY VARCHAR, DECISION VARCHAR, RATIONALE VARCHAR, CONDITIONS VARIANT,
  REVIEWER_USERNAME VARCHAR, APP_VERSION VARCHAR, CORRELATION_ID VARCHAR
) RETURNS VARIANT LANGUAGE SQL EXECUTE AS CALLER AS
$$
DECLARE invalid_resource EXCEPTION (-20121, 'Only the two reviewed restricted CDC sources are accepted');
  invalid_input EXCEPTION (-20122, 'A supported approval and complete review metadata are required');
  incomplete_evidence EXCEPTION (-20123, 'Restricted-source approval requires completed private evidence');
  unauthorized EXCEPTION (-20124, 'Reviewer is not an active global steward');
  evidence_count NUMBER; steward_count NUMBER; decision_id VARCHAR DEFAULT UUID_STRING(); source_version_id VARCHAR DEFAULT UUID_STRING();
BEGIN
  IF (RESOURCE_KEY NOT IN ('cdc_tick_ixodes_county_status','cdc_tick_ixodes_pathogen_status')) THEN RAISE invalid_resource; END IF;
  IF (DECISION NOT IN ('APPROVED','APPROVED_WITH_CONDITIONS') OR LENGTH(TRIM(RATIONALE)) < 10 OR CONDITIONS IS NULL OR NOT IS_ARRAY(CONDITIONS) OR ARRAY_SIZE(CONDITIONS)=0 OR NULLIF(TRIM(REVIEWER_USERNAME),'') IS NULL OR NULLIF(TRIM(APP_VERSION),'') IS NULL OR NULLIF(TRIM(CORRELATION_ID),'') IS NULL) THEN RAISE invalid_input; END IF;
  SELECT COUNT(*) INTO :steward_count FROM GOVERNANCE.APPROVAL_STEWARDS WHERE username=:REVIEWER_USERNAME AND is_active=TRUE AND authorization_scope='GLOBAL';
  IF (steward_count <> 1) THEN RAISE unauthorized; END IF;
  SELECT COUNT(*) INTO :evidence_count FROM GOVERNANCE.INGESTION_RUNS r WHERE r.resource_key=:RESOURCE_KEY AND r.run_mode='EVIDENCE_ONLY' AND r.status='COMPLETED' AND EXISTS (SELECT 1 FROM GOVERNANCE.RAW_ARTIFACTS a WHERE a.ingestion_run_id=r.ingestion_run_id AND a.artifact_type='SOURCE_WORKBOOK_EVIDENCE') AND EXISTS (SELECT 1 FROM GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS d WHERE d.resource_key=:RESOURCE_KEY) AND EXISTS (SELECT 1 FROM GOVERNANCE.SCHEMA_SNAPSHOTS s WHERE s.resource_key=:RESOURCE_KEY);
  IF (evidence_count < 1) THEN RAISE incomplete_evidence; END IF;
  UPDATE GOVERNANCE.DATA_SOURCE_VERSIONS SET status='RETIRED', retired_at=CURRENT_TIMESTAMP() WHERE resource_key=:RESOURCE_KEY AND retired_at IS NULL AND status IN ('APPROVED','CONDITIONAL');
  INSERT INTO GOVERNANCE.DATA_SOURCE_VERSIONS(data_source_version_id,resource_key,status,approved_decision_id,created_at) VALUES(:source_version_id,:RESOURCE_KEY,IFF(:DECISION='APPROVED','APPROVED','CONDITIONAL'),:decision_id,CURRENT_TIMESTAMP());
  INSERT INTO GOVERNANCE.MANUAL_REVIEW_DECISIONS(manual_review_decision_id,resource_key,decision,rationale,conditions,reviewer_username,data_source_version_id,app_version,correlation_id,decided_at) SELECT :decision_id,:RESOURCE_KEY,:DECISION,:RATIONALE,CONDITIONS,:REVIEWER_USERNAME,:source_version_id,:APP_VERSION,:CORRELATION_ID,CURRENT_TIMESTAMP();
  RETURN OBJECT_CONSTRUCT('decision_id',:decision_id,'source_version_id',:source_version_id);
END;
$$;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_RECORD_RESTRICTED_SOURCE_REVIEW_PROD(VARCHAR,VARCHAR,VARCHAR,VARIANT,VARCHAR,VARCHAR,VARCHAR) TO ROLE OH_LYME_PROD_STREAMLIT_OWNER;
