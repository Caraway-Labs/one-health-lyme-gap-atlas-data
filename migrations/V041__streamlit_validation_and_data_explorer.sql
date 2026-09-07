USE DATABASE {{ DATABASE }};

-- These views expose bounded, provenance-bearing validation and exploration
-- data.  They deliberately exclude RAW payloads, request details, artifact
-- locations, and credentials.
CREATE OR REPLACE VIEW GOVERNANCE.V_SOURCE_INGESTION_VALIDATION AS
WITH raw_rollup AS (
  SELECT data_source_version_id, ingestion_run_id, COUNT(*) AS raw_row_count,
         COUNT(DISTINCT artifact_id) AS artifact_count,
         MIN(retrieved_at) AS first_retrieved_at, MAX(retrieved_at) AS last_retrieved_at
  FROM RAW.CDC_LYME_X5J9_WYBP
  GROUP BY data_source_version_id, ingestion_run_id
), latest_run AS (
  SELECT raw.data_source_version_id, run.ingestion_run_id, run.status AS ingestion_status,
         run.started_at, run.completed_at, run.code_version,
         raw.raw_row_count, raw.artifact_count, raw.first_retrieved_at, raw.last_retrieved_at,
         ROW_NUMBER() OVER (
           PARTITION BY raw.data_source_version_id ORDER BY run.started_at DESC
         ) AS row_number
  FROM raw_rollup raw
  JOIN GOVERNANCE.INGESTION_RUNS run ON run.ingestion_run_id = raw.ingestion_run_id
), conformed_rollup AS (
  SELECT data_source_version_id, COUNT(*) AS conformed_row_count,
         COUNT(DISTINCT ingestion_run_id) AS conformed_run_count,
         MIN(retrieved_at) AS conformed_first_retrieved_at,
         MAX(retrieved_at) AS conformed_last_retrieved_at
  FROM CONFORMED.CONFORMED_CDC_LYME_X5J9_WYBP
  GROUP BY data_source_version_id
), quality_rollup AS (
  SELECT ingestion_run_id,
         COUNT(*) AS quality_result_count,
         COUNT_IF(status = 'FAILED') AS failed_quality_result_count
  FROM GOVERNANCE.DATA_QUALITY_RESULTS
  GROUP BY ingestion_run_id
)
SELECT version.data_source_version_id, version.resource_key, version.status AS source_version_status,
       version.created_at AS source_version_created_at, version.retired_at,
       run.ingestion_run_id, run.ingestion_status, run.started_at AS ingestion_started_at,
       run.completed_at AS ingestion_completed_at, run.code_version,
       COALESCE(run.artifact_count, 0) AS artifact_count,
       COALESCE(run.raw_row_count, 0) AS raw_row_count,
       run.first_retrieved_at, run.last_retrieved_at,
       COALESCE(conformed.conformed_row_count, 0) AS conformed_row_count,
       COALESCE(conformed.conformed_run_count, 0) AS conformed_run_count,
       conformed.conformed_first_retrieved_at, conformed.conformed_last_retrieved_at,
       COALESCE(quality.quality_result_count, 0) AS quality_result_count,
       COALESCE(quality.failed_quality_result_count, 0) AS failed_quality_result_count,
       IFF(COALESCE(conformed.conformed_row_count, 0) > 0, 'MATERIALIZED', 'NOT_MATERIALIZED')
         AS conformed_materialization_status,
       '2022-current surveillance era; not comparable to prior eras without reviewed methodology'
         AS caveat
FROM GOVERNANCE.DATA_SOURCE_VERSIONS version
LEFT JOIN latest_run run ON run.data_source_version_id = version.data_source_version_id
  AND run.row_number = 1
LEFT JOIN conformed_rollup conformed ON conformed.data_source_version_id = version.data_source_version_id
LEFT JOIN quality_rollup quality ON quality.ingestion_run_id = run.ingestion_run_id
WHERE version.resource_key = 'cdc_lyme_x5j9_wybp';

CREATE OR REPLACE VIEW GOVERNANCE.V_DATA_EXPLORER_SOURCE_VERSIONS AS
SELECT data_source_version_id, resource_key, source_version_status, source_version_created_at,
       retired_at, ingestion_run_id, ingestion_status, ingestion_completed_at,
       raw_row_count, conformed_row_count, conformed_materialization_status, caveat
FROM GOVERNANCE.V_SOURCE_INGESTION_VALIDATION;

CREATE OR REPLACE VIEW GOVERNANCE.V_DATA_EXPLORER_CONFORMED_CDC AS
SELECT source_record_id, data_source_version_id, ingestion_run_id, artifact_id,
       county_fips, report_year, case_status, sex, age_category_years, frequency,
       source_value_status, geography_semantics, source_resolution, temporal_window,
       caveat, retrieved_at
FROM CONFORMED.CONFORMED_CDC_LYME_X5J9_WYBP;

CREATE OR REPLACE VIEW GOVERNANCE.V_DATA_EXPLORER_ANALYTICS_CDC AS
-- No reviewed aggregate has been defined for this surveillance source. This
-- analytics-ready projection therefore preserves the CONFORMED grain and its
-- provenance rather than inventing a metric or cross-era comparison.
SELECT source_record_id, data_source_version_id, ingestion_run_id, artifact_id,
       county_fips, report_year, case_status, sex, age_category_years, frequency,
       source_value_status, geography_semantics, source_resolution, temporal_window,
       caveat, retrieved_at
FROM CONFORMED.CONFORMED_CDC_LYME_X5J9_WYBP;

-- Both apps run with the existing constrained owner role.  They query only
-- the explicit views above, never their underlying RAW/STAGING/CONFORMED tables.
GRANT SELECT ON VIEW GOVERNANCE.V_SOURCE_INGESTION_VALIDATION
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_DATA_EXPLORER_SOURCE_VERSIONS
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_DATA_EXPLORER_CONFORMED_CDC
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_DATA_EXPLORER_ANALYTICS_CDC
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
