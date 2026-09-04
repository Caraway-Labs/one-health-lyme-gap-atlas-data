USE DATABASE {{ DATABASE }};

-- Read-only, summary-first operational views for the internal Streamlit console.
-- They deliberately exclude artifact URIs, payloads, request bodies, and secrets.
CREATE OR REPLACE VIEW GOVERNANCE.V_PIPELINE_OBSERVABILITY_OVERVIEW AS
SELECT
  (SELECT COUNT(*) FROM GOVERNANCE.RAW_ARTIFACTS WHERE artifact_type = 'CATALOG_METADATA')
    AS captured_artifacts,
  COUNT(*) AS active_chain_artifacts,
  COUNT_IF(status = 'COMPLETED') AS completed_artifacts,
  COUNT_IF(status <> 'COMPLETED') AS unresolved_artifacts,
  COUNT_IF(status = 'FAILED') AS failed_artifacts,
  COUNT_IF(status = 'IN_PROGRESS' AND lease_expires_at <= CURRENT_TIMESTAMP())
    AS expired_lease_artifacts,
  MAX(IFF(status = 'COMPLETED', completed_at, NULL)) AS latest_registration_completed_at
FROM GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS;

CREATE OR REPLACE VIEW GOVERNANCE.V_PIPELINE_ARTIFACT_BACKLOG AS
SELECT r.artifact_id,
       q.redacted_request:catalog_id::VARCHAR AS catalog,
       q.redacted_request:term::VARCHAR AS matched_term,
       a.created_at AS captured_at,
       a.byte_count,
       r.status,
       r.attempt_count,
       r.started_at,
       r.lease_expires_at,
       IFF(r.status = 'IN_PROGRESS' AND r.lease_expires_at <= CURRENT_TIMESTAMP(),
           TRUE, FALSE) AS has_expired_lease,
       r.redacted_error
FROM GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS r
JOIN GOVERNANCE.RAW_ARTIFACTS a ON a.artifact_id = r.artifact_id
JOIN GOVERNANCE.INGESTION_REQUESTS q ON q.ingestion_request_id = a.ingestion_request_id;

CREATE OR REPLACE VIEW GOVERNANCE.V_PIPELINE_DISCOVERY_RUNS AS
SELECT ingestion_run_id, resource_key, run_mode, trigger_type, status, config_sha256,
       started_at, completed_at, resumed_from_ingestion_run_id, error_classification
FROM GOVERNANCE.INGESTION_RUNS
WHERE resource_key = 'catalog_discovery';

CREATE OR REPLACE VIEW GOVERNANCE.V_PIPELINE_CATALOG_COVERAGE AS
SELECT q.redacted_request:catalog_id::VARCHAR AS catalog,
       COUNT(*) AS captured_artifacts,
       COUNT(DISTINCT q.redacted_request:term::VARCHAR) AS distinct_terms,
       SUM(a.byte_count) AS captured_bytes,
       COUNT_IF(r.status = 'COMPLETED') AS registered_artifacts,
       COUNT_IF(r.status <> 'COMPLETED' OR r.status IS NULL) AS unresolved_artifacts
FROM GOVERNANCE.RAW_ARTIFACTS a
JOIN GOVERNANCE.INGESTION_REQUESTS q ON q.ingestion_request_id = a.ingestion_request_id
LEFT JOIN GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS r ON r.artifact_id = a.artifact_id
WHERE a.artifact_type = 'CATALOG_METADATA' AND q.status_code = 200
GROUP BY q.redacted_request:catalog_id::VARCHAR;

CREATE OR REPLACE VIEW GOVERNANCE.V_PIPELINE_REGISTRATION_OUTCOMES AS
SELECT
  (SELECT COUNT(*) FROM GOVERNANCE.CATALOG_DATASETS) AS unique_catalog_datasets,
  (SELECT COUNT(*) FROM GOVERNANCE.CATALOG_RESOURCES) AS unique_catalog_resources,
  (SELECT COUNT(*) FROM GOVERNANCE.CATALOG_DISCOVERY_OBSERVATIONS) AS immutable_observations,
  (SELECT COUNT(*) FROM GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS
   WHERE status = 'COMPLETED') AS completed_artifacts,
  (SELECT COUNT(*) FROM GOVERNANCE.DATA_SOURCE_VERSIONS) AS source_versions;

CREATE OR REPLACE VIEW GOVERNANCE.V_PIPELINE_SOURCE_GOVERNANCE AS
SELECT COALESCE(status, 'NO_SOURCE_VERSION') AS source_version_status,
       COUNT(*) AS source_versions
FROM GOVERNANCE.DATA_SOURCE_VERSIONS
GROUP BY status;

GRANT SELECT ON VIEW GOVERNANCE.V_PIPELINE_OBSERVABILITY_OVERVIEW
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_PIPELINE_ARTIFACT_BACKLOG
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_PIPELINE_DISCOVERY_RUNS
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_PIPELINE_CATALOG_COVERAGE
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_PIPELINE_REGISTRATION_OUTCOMES
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_PIPELINE_SOURCE_GOVERNANCE
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;

-- Owner-rights Streamlit requires direct privileges on view dependencies.
GRANT SELECT ON TABLE GOVERNANCE.RAW_ARTIFACTS TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON TABLE GOVERNANCE.INGESTION_REQUESTS TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON TABLE GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON TABLE GOVERNANCE.CATALOG_RESOURCES TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON TABLE GOVERNANCE.CATALOG_DISCOVERY_OBSERVATIONS
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON TABLE GOVERNANCE.DATA_SOURCE_VERSIONS TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
