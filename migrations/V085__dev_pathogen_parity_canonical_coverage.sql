-- DEV-only correction: classify canonical coverage, not source-scope row count.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_CLASSIFY_RESTRICTED_PATHOGEN_PARITY_DEV(
    INGESTION_RUN_ID VARCHAR, RATIONALE VARCHAR, APPROVED_BY VARCHAR
)
RETURNS VARIANT LANGUAGE SQL EXECUTE AS OWNER AS
$$
DECLARE
  invalid_environment EXCEPTION (-20111, 'Restricted pathogen parity classification is DEV-only');
  invalid_input EXCEPTION (-20112, 'Parity classification rationale and approver are required');
  invalid_run EXCEPTION (-20113, 'Restricted pathogen derivation run is not complete');
  canonical_count NUMBER DEFAULT 3144; reported_count NUMBER; source_version_id VARCHAR; classification_id VARCHAR DEFAULT UUID_STRING();
BEGIN
  IF (CURRENT_DATABASE() <> 'ONE_HEALTH_LYME_GAP_ATLAS_DEV') THEN RAISE invalid_environment; END IF;
  IF (INGESTION_RUN_ID IS NULL OR LENGTH(TRIM(RATIONALE)) < 10 OR NULLIF(TRIM(APPROVED_BY), '') IS NULL) THEN RAISE invalid_input; END IF;
  SELECT COUNT(*) INTO :reported_count
  FROM CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS p
  WHERE p.ingestion_run_id=:INGESTION_RUN_ID
    AND EXISTS (SELECT 1 FROM CONFORMED.GOVERNED_SOURCE_RECORDS s WHERE s.resource_key='cdc_atsdr_svi_2022_county' AND COALESCE(s.payload:record:STCNTY::VARCHAR, s.payload:STCNTY::VARCHAR)=p.county_fips);
  SELECT data_source_version_id INTO :source_version_id FROM GOVERNANCE.DATA_SOURCE_VERSIONS WHERE resource_key='cdc_tick_ixodes_pathogen_status' AND status IN ('APPROVED','CONDITIONAL') AND retired_at IS NULL QUALIFY ROW_NUMBER() OVER (ORDER BY created_at DESC)=1;
  IF (reported_count < 1 OR reported_count >= canonical_count OR source_version_id IS NULL) THEN RAISE invalid_run; END IF;
  INSERT INTO GOVERNANCE.RESTRICTED_PATHOGEN_PARITY_CLASSIFICATIONS
  VALUES (:classification_id, 'cdc_tick_ixodes_pathogen_status', :source_version_id, :INGESTION_RUN_ID, :canonical_count, :reported_count, :canonical_count-:reported_count, 'UNKNOWN_SOURCE_COVERAGE', :RATIONALE, :APPROVED_BY, CURRENT_TIMESTAMP());
  RETURN OBJECT_CONSTRUCT('classification_id', :classification_id, 'reported_count', :reported_count, 'unresolved_count', :canonical_count-:reported_count, 'classification', 'UNKNOWN_SOURCE_COVERAGE');
END;
$$;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_CLASSIFY_RESTRICTED_PATHOGEN_PARITY_DEV(VARCHAR, VARCHAR, VARCHAR) TO ROLE OH_LYME_DEV_OWNER;
