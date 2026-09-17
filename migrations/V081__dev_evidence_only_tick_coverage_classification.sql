-- DEV-only parity classification for the accepted Tier D tick evidence exception.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS GOVERNANCE.EVIDENCE_ONLY_SOURCE_COVERAGE_CLASSIFICATIONS (
    classification_id VARCHAR PRIMARY KEY,
    resource_key VARCHAR NOT NULL,
    data_source_version_id VARCHAR NOT NULL,
    ingestion_run_id VARCHAR NOT NULL,
    canonical_count NUMBER NOT NULL,
    reported_county_count NUMBER NOT NULL,
    unresolved_county_count NUMBER NOT NULL,
    classification VARCHAR NOT NULL,
    rationale VARCHAR NOT NULL,
    approved_by VARCHAR NOT NULL,
    approved_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_CLASSIFY_EVIDENCE_ONLY_TICK_COVERAGE_DEV(
    INGESTION_RUN_ID VARCHAR, RATIONALE VARCHAR, APPROVED_BY VARCHAR
)
RETURNS VARIANT LANGUAGE SQL EXECUTE AS OWNER AS
$$
DECLARE
  invalid_environment EXCEPTION (-20121, 'Evidence-only tick coverage classification is DEV-only');
  invalid_input EXCEPTION (-20122, 'Coverage rationale and approver are required');
  invalid_run EXCEPTION (-20123, 'Tick evidence run is not the completed approved evidence path');
  canonical_count NUMBER DEFAULT 3144; source_version_id VARCHAR; classification_id VARCHAR DEFAULT UUID_STRING();
BEGIN
  IF (CURRENT_DATABASE() <> 'ONE_HEALTH_LYME_GAP_ATLAS_DEV') THEN RAISE invalid_environment; END IF;
  IF (INGESTION_RUN_ID IS NULL OR LENGTH(TRIM(RATIONALE)) < 10 OR NULLIF(TRIM(APPROVED_BY), '') IS NULL) THEN RAISE invalid_input; END IF;
  IF (NOT EXISTS (SELECT 1 FROM GOVERNANCE.INGESTION_RUNS WHERE ingestion_run_id=:INGESTION_RUN_ID AND resource_key='cdc_tick_ixodes_county_status' AND status='COMPLETED')) THEN RAISE invalid_run; END IF;
  SELECT data_source_version_id INTO :source_version_id FROM GOVERNANCE.DATA_SOURCE_VERSIONS WHERE resource_key='cdc_tick_ixodes_county_status' AND status IN ('APPROVED','CONDITIONAL') AND retired_at IS NULL QUALIFY ROW_NUMBER() OVER (ORDER BY created_at DESC)=1;
  IF (source_version_id IS NULL) THEN RAISE invalid_run; END IF;
  INSERT INTO GOVERNANCE.EVIDENCE_ONLY_SOURCE_COVERAGE_CLASSIFICATIONS
  VALUES (:classification_id, 'cdc_tick_ixodes_county_status', :source_version_id, :INGESTION_RUN_ID, :canonical_count, 0, :canonical_count, 'UNKNOWN_SOURCE_COVERAGE', :RATIONALE, :APPROVED_BY, CURRENT_TIMESTAMP());
  RETURN OBJECT_CONSTRUCT('classification_id', :classification_id, 'reported_count', 0, 'unresolved_count', :canonical_count, 'classification', 'UNKNOWN_SOURCE_COVERAGE');
END;
$$;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_CLASSIFY_EVIDENCE_ONLY_TICK_COVERAGE_DEV(VARCHAR, VARCHAR, VARCHAR) TO ROLE OH_LYME_DEV_OWNER;
