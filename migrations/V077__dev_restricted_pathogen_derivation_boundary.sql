-- DEV-only Tier D boundary for the requestor-restricted CDC ArboNET workbook.
-- The runtime can execute the owner-rights procedure but cannot read these tables.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS RAW.RESTRICTED_CDC_PATHOGEN_WORKBOOK_ROWS (
    restricted_row_id VARCHAR PRIMARY KEY,
    ingestion_run_id VARCHAR NOT NULL,
    evidence_run_id VARCHAR NOT NULL,
    workbook_sha256 VARCHAR(64) NOT NULL,
    source_row_number NUMBER NOT NULL,
    source_row_hash VARCHAR(64) NOT NULL,
    source_payload VARIANT NOT NULL,
    retrieved_at TIMESTAMP_LTZ NOT NULL,
    loaded_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS STAGING.RESTRICTED_CDC_PATHOGEN_WORKBOOK_ROWS (
    restricted_row_id VARCHAR PRIMARY KEY,
    ingestion_run_id VARCHAR NOT NULL,
    evidence_run_id VARCHAR NOT NULL,
    county_fips VARCHAR(5) NOT NULL,
    source_row_hash VARCHAR(64) NOT NULL,
    normalized_payload VARIANT NOT NULL,
    retrieved_at TIMESTAMP_LTZ NOT NULL,
    normalized_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS (
    conformed_record_id VARCHAR PRIMARY KEY,
    resource_key VARCHAR NOT NULL,
    source_definition_version NUMBER NOT NULL,
    ingestion_run_id VARCHAR NOT NULL,
    evidence_run_id VARCHAR NOT NULL,
    source_record_id VARCHAR NOT NULL,
    source_row_hash VARCHAR(64) NOT NULL,
    county_fips VARCHAR(5) NOT NULL,
    burgdorferi_status VARCHAR NOT NULL,
    coverage_state VARCHAR NOT NULL,
    workbook_sha256 VARCHAR(64) NOT NULL,
    retrieved_at TIMESTAMP_LTZ NOT NULL,
    conformed_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_LOAD_RESTRICTED_PATHOGEN_DEV(
    INGESTION_RUN_ID VARCHAR,
    EVIDENCE_RUN_ID VARCHAR,
    WORKBOOK_SHA256 VARCHAR,
    RAW_ROWS VARIANT,
    RETRIEVED_AT TIMESTAMP_LTZ
)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  invalid_environment EXCEPTION (-20101, 'Restricted pathogen derivation is DEV-only');
  invalid_input EXCEPTION (-20102, 'Restricted pathogen derivation input is invalid');
  missing_evidence EXCEPTION (-20103, 'Approved restricted evidence artifact was not found');
  missing_approval EXCEPTION (-20104, 'No active approved pathogen source version exists');
  invalid_rows EXCEPTION (-20105, 'Restricted pathogen rows failed closed validation');
  row_count NUMBER; distinct_fips NUMBER; invalid_count NUMBER; artifact_id VARCHAR; source_version_id VARCHAR;
BEGIN
  IF CURRENT_DATABASE() <> 'ONE_HEALTH_LYME_GAP_ATLAS_DEV' THEN RAISE invalid_environment; END IF;
  IF INGESTION_RUN_ID IS NULL OR EVIDENCE_RUN_ID IS NULL OR WORKBOOK_SHA256 IS NULL
     OR LENGTH(WORKBOOK_SHA256) <> 64 OR RAW_ROWS IS NULL OR RETRIEVED_AT IS NULL THEN
    RAISE invalid_input;
  END IF;
  SELECT artifact_id INTO :artifact_id
  FROM GOVERNANCE.RAW_ARTIFACTS
  WHERE ingestion_run_id = :EVIDENCE_RUN_ID
    AND artifact_type = 'SOURCE_WORKBOOK_EVIDENCE'
    AND sha256 = :WORKBOOK_SHA256
  QUALIFY ROW_NUMBER() OVER (ORDER BY created_at DESC) = 1;
  IF artifact_id IS NULL THEN RAISE missing_evidence; END IF;
  SELECT data_source_version_id INTO :source_version_id
  FROM GOVERNANCE.DATA_SOURCE_VERSIONS
  WHERE resource_key = 'cdc_tick_ixodes_pathogen_status'
    AND status IN ('APPROVED', 'CONDITIONAL') AND retired_at IS NULL
  QUALIFY ROW_NUMBER() OVER (ORDER BY created_at DESC) = 1;
  IF source_version_id IS NULL THEN RAISE missing_approval; END IF;
  SELECT COUNT(*), COUNT(DISTINCT value:fips::VARCHAR) INTO :row_count, :distinct_fips
  FROM TABLE(FLATTEN(INPUT => :RAW_ROWS));
  SELECT COUNT(*) INTO :invalid_count FROM TABLE(FLATTEN(INPUT => :RAW_ROWS))
  WHERE NOT REGEXP_LIKE(value:fips::VARCHAR, '^[0-9]{5}$')
     OR value:burgdorferi_status::VARCHAR NOT IN ('Present', 'No records')
     OR NOT REGEXP_LIKE(value:source_row_hash::VARCHAR, '^[0-9a-f]{64}$');
  IF row_count < 1 OR row_count <> distinct_fips OR invalid_count <> 0 THEN RAISE invalid_rows; END IF;

  BEGIN TRANSACTION;
  INSERT INTO RAW.RESTRICTED_CDC_PATHOGEN_WORKBOOK_ROWS
  SELECT UUID_STRING(), :INGESTION_RUN_ID, :EVIDENCE_RUN_ID, :WORKBOOK_SHA256,
         value:source_row_number::NUMBER, value:source_row_hash::VARCHAR,
         value:raw, :RETRIEVED_AT, CURRENT_TIMESTAMP()
  FROM TABLE(FLATTEN(INPUT => :RAW_ROWS));
  INSERT INTO STAGING.RESTRICTED_CDC_PATHOGEN_WORKBOOK_ROWS
  SELECT UUID_STRING(), :INGESTION_RUN_ID, :EVIDENCE_RUN_ID, value:fips::VARCHAR,
         value:source_row_hash::VARCHAR,
         OBJECT_CONSTRUCT('fips', value:fips::VARCHAR,
                          'burgdorferi_status', value:burgdorferi_status::VARCHAR,
                          'burgdorferi_source', value:burgdorferi_source::VARCHAR),
         :RETRIEVED_AT, CURRENT_TIMESTAMP()
  FROM TABLE(FLATTEN(INPUT => :RAW_ROWS));
  INSERT INTO CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS
  SELECT UUID_STRING(), 'cdc_tick_ixodes_pathogen_status', 1, :INGESTION_RUN_ID,
         :EVIDENCE_RUN_ID, value:fips::VARCHAR, value:source_row_hash::VARCHAR,
         value:fips::VARCHAR, value:burgdorferi_status::VARCHAR, 'REPORTED',
         :WORKBOOK_SHA256, :RETRIEVED_AT, CURRENT_TIMESTAMP()
  FROM TABLE(FLATTEN(INPUT => :RAW_ROWS));
  INSERT INTO GOVERNANCE.INGESTION_REQUESTS
  SELECT UUID_STRING(), :INGESTION_RUN_ID, 1, 'PRIVATE_OPERATOR_VERIFIED_WORKBOOK',
         'restricted://cdc-arbonet/pathogen-workbook',
         OBJECT_CONSTRUCT('evidence_run_id', :EVIDENCE_RUN_ID,
                          'workbook_sha256', :WORKBOOK_SHA256,
                          'transport', 'PRIVATE_OPERATOR_ENVELOPE'),
         NULL, :WORKBOOK_SHA256, :row_count, CURRENT_TIMESTAMP();
  INSERT INTO GOVERNANCE.DATA_QUALITY_RESULTS
  SELECT UUID_STRING(), :INGESTION_RUN_ID, 'restricted_pathogen_source_rows', 'BLOCKING',
         'PASSED', OBJECT_CONSTRUCT('minimum', 1), OBJECT_CONSTRUCT('observed', :row_count), CURRENT_TIMESTAMP()
  UNION ALL
  SELECT UUID_STRING(), :INGESTION_RUN_ID, 'restricted_pathogen_unique_fips', 'BLOCKING',
         'PASSED', OBJECT_CONSTRUCT('expected', :row_count), OBJECT_CONSTRUCT('observed', :distinct_fips), CURRENT_TIMESTAMP()
  UNION ALL
  SELECT UUID_STRING(), :INGESTION_RUN_ID, 'restricted_pathogen_derived_output_only', 'BLOCKING',
         'PASSED', OBJECT_CONSTRUCT('columns', ARRAY_CONSTRUCT('county_fips', 'burgdorferi_status', 'coverage_state')),
         OBJECT_CONSTRUCT('target', 'CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS'), CURRENT_TIMESTAMP();
  INSERT INTO GOVERNANCE.INGESTION_PUBLICATIONS
  SELECT UUID_STRING(), 'cdc_tick_ixodes_pathogen_status', :INGESTION_RUN_ID, 1, 'STAGED',
         'CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS', :row_count,
         OBJECT_CONSTRUCT('source_version_id', :source_version_id, 'artifact_id', :artifact_id,
                          'eligibility', 'DERIVED_COUNTY_STATUS_ONLY_PENDING_PARITY'), CURRENT_TIMESTAMP();
  UPDATE GOVERNANCE.INGESTION_RUNS SET status='COMPLETED', completed_at=CURRENT_TIMESTAMP()
  WHERE ingestion_run_id=:INGESTION_RUN_ID;
  COMMIT;
  RETURN OBJECT_CONSTRUCT('ingestion_run_id', :INGESTION_RUN_ID, 'source_version_id', :source_version_id,
                          'artifact_id', :artifact_id, 'conformed_count', :row_count,
                          'coverage_state', 'REPORTED', 'semantic_release_state', 'PENDING_PARITY_CLASSIFICATION');
EXCEPTION WHEN OTHER THEN
  ROLLBACK;
  UPDATE GOVERNANCE.INGESTION_RUNS SET status='FAILED', completed_at=CURRENT_TIMESTAMP(),
    error_classification='RESTRICTED_PATHOGEN_DERIVATION_FAILED',
    redacted_error='Restricted pathogen derivation failed; inspect owner-controlled run evidence.'
  WHERE ingestion_run_id=:INGESTION_RUN_ID;
  RAISE;
END;
$$;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_LOAD_RESTRICTED_PATHOGEN_DEV(
  VARCHAR, VARCHAR, VARCHAR, VARIANT, TIMESTAMP_LTZ
) TO ROLE OH_LYME_DEV_RUNTIME;

CREATE OR REPLACE VIEW GOVERNANCE.V_RESTRICTED_PATHOGEN_PARITY_SUMMARY AS
SELECT ingestion_run_id, COUNT(*) AS reported_county_rows,
       3144 - COUNT(*) AS unresolved_county_identity_delta,
       MIN(retrieved_at) AS retrieved_at,
       MAX(conformed_at) AS conformed_at
FROM CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS
GROUP BY ingestion_run_id;

GRANT SELECT ON VIEW GOVERNANCE.V_RESTRICTED_PATHOGEN_PARITY_SUMMARY
  TO ROLE OH_LYME_DEV_OWNER;
