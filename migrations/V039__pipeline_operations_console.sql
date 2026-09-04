USE DATABASE {{ DATABASE }};

-- A registration invocation is distinct from an artifact registration row.  This
-- durable, redacted summary lets operators understand bounded recovery passes
-- without reconstructing a run from mutable artifact leases or application logs.
CREATE TABLE IF NOT EXISTS GOVERNANCE.CATALOG_REGISTRATION_RUNS (
  registration_run_id VARCHAR PRIMARY KEY,
  config_sha256 VARCHAR(64) NOT NULL,
  status VARCHAR NOT NULL,
  started_at TIMESTAMP_LTZ NOT NULL,
  completed_at TIMESTAMP_LTZ,
  maximum_artifacts NUMBER NOT NULL,
  maximum_datasets NUMBER NOT NULL,
  claimed_artifacts NUMBER NOT NULL DEFAULT 0,
  available_artifacts NUMBER NOT NULL DEFAULT 0,
  processed_datasets NUMBER NOT NULL DEFAULT 0,
  registered_resources NUMBER NOT NULL DEFAULT 0,
  completed_artifacts NUMBER NOT NULL DEFAULT 0,
  failed_artifacts NUMBER NOT NULL DEFAULT 0,
  remaining_artifacts NUMBER,
  error_classification VARCHAR
);

CREATE OR REPLACE VIEW GOVERNANCE.V_PIPELINE_REGISTRATION_RUNS AS
SELECT registration_run_id,
       config_sha256,
       status,
       started_at,
       completed_at,
       IFF(completed_at IS NULL, NULL,
           DATEDIFF('second', started_at, completed_at)) AS duration_seconds,
       maximum_artifacts,
       maximum_datasets,
       claimed_artifacts,
       available_artifacts,
       processed_datasets,
       registered_resources,
       completed_artifacts,
       failed_artifacts,
       remaining_artifacts,
       error_classification
FROM GOVERNANCE.CATALOG_REGISTRATION_RUNS;

-- This view is deliberately scoped to the newest *completed* discovery chain.
-- Historical inventory remains visible in V_PIPELINE_OBSERVABILITY_OVERVIEW,
-- but is never represented as current queued work.
CREATE OR REPLACE VIEW GOVERNANCE.V_PIPELINE_COMMAND_CENTER AS
WITH latest_discovery AS (
  SELECT config_sha256, completed_at AS discovery_completed_at
  FROM GOVERNANCE.INGESTION_RUNS
  WHERE resource_key = 'catalog_discovery'
    AND status = 'COMPLETED'
    AND completed_at IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (ORDER BY completed_at DESC, ingestion_run_id DESC) = 1
),
registration AS (
  SELECT r.status, r.lease_expires_at, r.completed_at
  FROM GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS r
  JOIN latest_discovery d ON d.config_sha256 = r.config_sha256
),
latest_registration_run AS (
  SELECT rr.status, rr.started_at, rr.completed_at, rr.remaining_artifacts,
         rr.error_classification
  FROM GOVERNANCE.CATALOG_REGISTRATION_RUNS rr
  JOIN latest_discovery d ON d.config_sha256 = rr.config_sha256
  QUALIFY ROW_NUMBER() OVER (ORDER BY rr.started_at DESC, rr.registration_run_id DESC) = 1
)
SELECT d.config_sha256,
       d.discovery_completed_at,
       COUNT(r.status) AS active_chain_artifacts,
       COUNT_IF(r.status = 'COMPLETED') AS completed_artifacts,
       COUNT_IF(r.status = 'FAILED') AS failed_artifacts,
       COUNT_IF(r.status = 'IN_PROGRESS' AND r.lease_expires_at <= CURRENT_TIMESTAMP())
         AS expired_lease_artifacts,
       COUNT_IF(r.status IN ('PENDING', 'IN_PROGRESS')) AS pending_or_in_progress_artifacts,
       lr.status AS latest_registration_run_status,
       lr.started_at AS latest_registration_run_started_at,
       lr.completed_at AS latest_registration_run_completed_at,
       lr.remaining_artifacts AS latest_registration_run_remaining_artifacts,
       lr.error_classification AS latest_registration_run_error_classification,
       CASE
         WHEN d.config_sha256 IS NULL THEN 'NO_COMPLETED_DISCOVERY'
         WHEN COUNT_IF(r.status = 'FAILED') > 0
           OR COUNT_IF(r.status = 'IN_PROGRESS' AND r.lease_expires_at <= CURRENT_TIMESTAMP()) > 0
           THEN 'ATTENTION_REQUIRED'
         WHEN COUNT(r.status) = 0 THEN 'AWAITING_REGISTRATION'
         WHEN COUNT_IF(r.status <> 'COMPLETED') = 0 THEN 'COMPLETE'
         WHEN lr.status = 'FAILED' THEN 'ATTENTION_REQUIRED'
         ELSE 'IN_PROGRESS'
       END AS operational_state
FROM latest_discovery d
LEFT JOIN registration r ON TRUE
LEFT JOIN latest_registration_run lr ON TRUE
GROUP BY d.config_sha256, d.discovery_completed_at, lr.status, lr.started_at,
         lr.completed_at, lr.remaining_artifacts, lr.error_classification;

-- A request-level coverage view makes zero-result searches visible.  It does
-- not infer an unattempted search: that requires an explicitly deployed search
-- plan and is intentionally not guessed from absence of a request row.
CREATE OR REPLACE VIEW GOVERNANCE.V_PIPELINE_SEARCH_COVERAGE AS
SELECT i.ingestion_run_id,
       q.request_sequence,
       q.redacted_request:catalog_id::VARCHAR AS catalog,
       q.redacted_request:term::VARCHAR AS matched_term,
       q.created_at AS requested_at,
       q.status_code,
       q.retrieved_row_count,
       COUNT(DISTINCT a.artifact_id) AS captured_artifacts,
       COUNT_IF(r.status = 'COMPLETED') AS registered_artifacts,
       COUNT_IF(r.status = 'FAILED') AS failed_artifacts,
       CASE
         WHEN q.status_code IS NULL OR q.status_code >= 400 THEN 'REQUEST_FAILED'
         WHEN COALESCE(q.retrieved_row_count, 0) = 0 THEN 'ZERO_RESULTS'
         WHEN COUNT(DISTINCT a.artifact_id) = 0 THEN 'CAPTURE_NOT_RECORDED'
         WHEN COUNT_IF(r.status = 'FAILED') > 0 THEN 'REGISTRATION_FAILED'
         WHEN COUNT_IF(r.status = 'COMPLETED') = COUNT(DISTINCT a.artifact_id)
           THEN 'REGISTERED'
         ELSE 'AWAITING_REGISTRATION'
       END AS coverage_state
FROM GOVERNANCE.INGESTION_REQUESTS q
JOIN GOVERNANCE.INGESTION_RUNS i ON i.ingestion_run_id = q.ingestion_run_id
LEFT JOIN GOVERNANCE.RAW_ARTIFACTS a ON a.ingestion_request_id = q.ingestion_request_id
  AND a.artifact_type = 'CATALOG_METADATA'
LEFT JOIN GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS r ON r.artifact_id = a.artifact_id
WHERE i.resource_key = 'catalog_discovery'
GROUP BY i.ingestion_run_id, q.request_sequence,
         q.redacted_request:catalog_id::VARCHAR, q.redacted_request:term::VARCHAR,
         q.created_at, q.status_code, q.retrieved_row_count;

GRANT SELECT, INSERT, UPDATE ON TABLE GOVERNANCE.CATALOG_REGISTRATION_RUNS
  TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT SELECT ON VIEW GOVERNANCE.V_PIPELINE_REGISTRATION_RUNS
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_PIPELINE_COMMAND_CENTER
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_PIPELINE_SEARCH_COVERAGE
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON TABLE GOVERNANCE.CATALOG_REGISTRATION_RUNS
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON TABLE GOVERNANCE.INGESTION_RUNS
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
