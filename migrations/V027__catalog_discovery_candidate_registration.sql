USE DATABASE {{ DATABASE }};

-- Every raw catalog response remains immutable in Spaces. This table records
-- each normalized observation so mirrors and repeated term matches are
-- traceable rather than collapsed away during candidate deduplication.
CREATE TABLE IF NOT EXISTS GOVERNANCE.CATALOG_DISCOVERY_OBSERVATIONS (
  observation_id VARCHAR PRIMARY KEY,
  ingestion_run_id VARCHAR NOT NULL,
  ingestion_request_id VARCHAR NOT NULL,
  artifact_id VARCHAR NOT NULL,
  catalog_id VARCHAR NOT NULL,
  catalog_record_id VARCHAR NOT NULL,
  matched_term VARCHAR NOT NULL,
  catalog_dataset_id VARCHAR NOT NULL,
  catalog_resource_id VARCHAR NOT NULL,
  canonical_resource_key VARCHAR NOT NULL,
  observed_at TIMESTAMP_LTZ NOT NULL
);

-- This is a triage view, not an approval queue. It intentionally exposes only
-- metadata already preserved by discovery and gives no source the ability to
-- bypass its later documentation/sample/assessment/steward-review gates.
CREATE OR REPLACE VIEW GOVERNANCE.V_DISCOVERY_CANDIDATES AS
SELECT r.resource_key,
       r.resource_type,
       r.canonical_source_url,
       r.api_dataset_id,
       MIN(r.resource_payload:title::VARCHAR) AS title,
       MIN(r.resource_payload:publisher::VARCHAR) AS publisher,
       COUNT(DISTINCT o.observation_id) AS catalog_observation_count,
       COUNT(DISTINCT o.catalog_id) AS catalog_count,
       COUNT(DISTINCT o.matched_term) AS matched_term_count,
       CASE
         WHEN r.resource_type IN ('API', 'DATA') THEN 'COLLECT_METADATA_AND_SAMPLE'
         WHEN r.resource_type = 'CONTROLLED_ACCESS' THEN 'NO_AUTOMATED_ACQUISITION'
         ELSE 'RESEARCH_LEAD'
       END AS next_action
FROM GOVERNANCE.CATALOG_RESOURCES r
JOIN GOVERNANCE.CATALOG_DISCOVERY_OBSERVATIONS o
  ON o.catalog_resource_id = r.catalog_resource_id
WHERE r.is_active = TRUE
GROUP BY r.resource_key, r.resource_type, r.canonical_source_url, r.api_dataset_id;

-- The pipeline runtime may materialize completed private catalog artifacts,
-- but remains unable to make approval decisions or activate source versions.
GRANT SELECT ON TABLE GOVERNANCE.INGESTION_RUNS
  TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT SELECT, INSERT ON TABLE GOVERNANCE.CATALOG_DATASETS
  TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT SELECT, INSERT ON TABLE GOVERNANCE.CATALOG_RESOURCES
  TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT SELECT, INSERT ON TABLE GOVERNANCE.CATALOG_DISCOVERY_OBSERVATIONS
  TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT SELECT ON VIEW GOVERNANCE.V_DISCOVERY_CANDIDATES
  TO ROLE OH_LYME_{{ ENV }}_APPROVAL_VIEWER;
GRANT SELECT ON VIEW GOVERNANCE.V_DISCOVERY_CANDIDATES
  TO ROLE OH_LYME_{{ ENV }}_DATA_STEWARD;
