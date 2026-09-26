-- Data #449. Environment-local, append-oriented Dataset Discovery record.
-- Do not apply before data #454 recovery and the role ADR have owner/security approval.
-- Historical migrations and the GOVERNANCE migration ledger remain authoritative.
USE DATABASE {{ DATABASE }};
CREATE SCHEMA IF NOT EXISTS DATASET_DISCOVERY;

-- A single pre-created row serializes the low-volume v1 business procedures.
-- Each procedure must UPDATE this row inside an explicit DML transaction,
-- reread its operation key and state, and commit/rollback before returning.
-- Standard Snowflake table PRIMARY KEY/UNIQUE declarations are informational.
CREATE TABLE IF NOT EXISTS DATASET_DISCOVERY.WRITE_SERIALIZATION (
  lock_name VARCHAR NOT NULL,
  revision NUMBER NOT NULL,
  touched_at TIMESTAMP_LTZ NOT NULL
);
MERGE INTO DATASET_DISCOVERY.WRITE_SERIALIZATION t
USING (SELECT 'V1_WRITES' AS lock_name) s
ON t.lock_name = s.lock_name
WHEN NOT MATCHED THEN INSERT (lock_name, revision, touched_at)
  VALUES ('V1_WRITES', 0, CURRENT_TIMESTAMP());

CREATE TABLE IF NOT EXISTS DATASET_DISCOVERY.RUNS (
  run_id VARCHAR NOT NULL,
  operation_key VARCHAR NOT NULL,
  retry_of_run_id VARCHAR,
  mode VARCHAR NOT NULL,
  trigger_type VARCHAR NOT NULL,
  status VARCHAR NOT NULL,
  started_at TIMESTAMP_LTZ NOT NULL,
  heartbeat_at TIMESTAMP_LTZ,
  completed_at TIMESTAMP_LTZ,
  code_sha VARCHAR(40) NOT NULL,
  spec_version VARCHAR NOT NULL,
  graph_version VARCHAR NOT NULL,
  config_fingerprint VARCHAR(64) NOT NULL,
  search_fingerprint VARCHAR(64) NOT NULL,
  evidence_snapshot_id VARCHAR NOT NULL,
  provider VARCHAR,
  model_id VARCHAR,
  model_fingerprint VARCHAR(64),
  prompt_versions VARIANT,
  tool_versions VARIANT,
  eval_version VARCHAR,
  trace_id VARCHAR,
  host_session_id VARCHAR,
  counters VARIANT,
  stop_reason VARCHAR,
  redacted_error_code VARCHAR,
  request_fingerprint VARCHAR(64) NOT NULL
);

CREATE TABLE IF NOT EXISTS DATASET_DISCOVERY.CANDIDATE_OUTCOMES (
  outcome_id VARCHAR NOT NULL,
  operation_key VARCHAR NOT NULL,
  run_id VARCHAR NOT NULL,
  resource_key VARCHAR NOT NULL,
  catalog_dataset_id VARCHAR NOT NULL,
  catalog_resource_id VARCHAR NOT NULL,
  evidence_snapshot_id VARCHAR NOT NULL,
  outcome VARCHAR NOT NULL,
  reason_code VARCHAR,
  recommendation_version_id VARCHAR,
  observed_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

-- recommendation_id is stable per canonical resource; every new run's
-- assertion gets its own immutable recommendation_version_id, including
-- equivalent content. A same-run transport replay returns that version.
CREATE TABLE IF NOT EXISTS DATASET_DISCOVERY.RECOMMENDATIONS (
  recommendation_version_id VARCHAR NOT NULL,
  recommendation_id VARCHAR NOT NULL,
  run_id VARCHAR NOT NULL,
  operation_key VARCHAR NOT NULL,
  resource_key VARCHAR NOT NULL,
  catalog_dataset_id VARCHAR NOT NULL,
  catalog_resource_id VARCHAR NOT NULL,
  evidence_snapshot_id VARCHAR NOT NULL,
  assertion_sha256 VARCHAR(64) NOT NULL,
  equivalent_to_version_id VARCHAR,
  supersedes_version_id VARCHAR,
  classification VARCHAR NOT NULL,
  relationship_type VARCHAR NOT NULL,
  relationship_uncertainty VARCHAR,
  rights_state VARCHAR NOT NULL,
  observed_facts VARIANT NOT NULL,
  inferences VARIANT NOT NULL,
  unknowns VARIANT NOT NULL,
  dimensions VARIANT NOT NULL,
  ranking_formula_version VARCHAR NOT NULL,
  relationship_adjustment NUMBER NOT NULL,
  missing_count NUMBER NOT NULL,
  priority_score NUMBER NOT NULL,
  priority_bucket VARCHAR NOT NULL,
  rationale VARCHAR NOT NULL,
  created_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  commit_complete BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS DATASET_DISCOVERY.RECOMMENDATION_EVIDENCE (
  recommendation_version_id VARCHAR NOT NULL,
  observation_id VARCHAR NOT NULL,
  catalog_dataset_id VARCHAR NOT NULL,
  catalog_resource_id VARCHAR NOT NULL,
  field_name VARCHAR NOT NULL,
  metadata_sha256 VARCHAR(64),
  observed_at TIMESTAMP_LTZ NOT NULL,
  recorded_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS DATASET_DISCOVERY.SEARCH_EXPANSION_PROPOSALS (
  proposal_id VARCHAR NOT NULL,
  recommendation_version_id VARCHAR NOT NULL,
  run_id VARCHAR NOT NULL,
  proposed_term VARCHAR NOT NULL,
  catalog_scope VARCHAR NOT NULL,
  evidence_observation_ids VARIANT NOT NULL,
  rationale VARCHAR NOT NULL,
  review_status VARCHAR NOT NULL DEFAULT 'PENDING',
  created_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS DATASET_DISCOVERY.REVIEW_EVENTS (
  review_event_id VARCHAR NOT NULL,
  command_key VARCHAR NOT NULL,
  recommendation_version_id VARCHAR NOT NULL,
  prior_state VARCHAR NOT NULL,
  new_state VARCHAR NOT NULL,
  decision VARCHAR NOT NULL,
  rationale VARCHAR NOT NULL,
  conditions VARIANT,
  reviewer_user VARCHAR NOT NULL,
  reviewer_role VARCHAR NOT NULL,
  reviewed_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  correction_of_event_id VARCHAR
);

CREATE TABLE IF NOT EXISTS DATASET_DISCOVERY.REVIEWER_ALLOWLIST (
  reviewer_user VARCHAR NOT NULL,
  is_active BOOLEAN NOT NULL,
  granted_at TIMESTAMP_LTZ NOT NULL,
  granted_by VARCHAR NOT NULL
);

-- Bounded projections omit full catalog resource_payload and private artifacts.
-- Registration may retain multiple observations; pagination uses stable IDs.
CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CANDIDATE_SUMMARY AS
SELECT o.ingestion_run_id AS discovery_run_id,
       r.resource_key, r.catalog_resource_id, d.catalog_dataset_id,
       d.catalog_name, d.catalog_record_id, d.metadata_sha256,
       r.resource_type, r.canonical_source_url, r.api_dataset_id,
       r.is_active AS resource_is_active, d.is_current AS dataset_is_current,
       IFF(LENGTH(r.resource_payload:title::VARCHAR) <= 300,
           r.resource_payload:title::VARCHAR, NULL) AS title,
       IFF(LENGTH(r.resource_payload:publisher::VARCHAR) <= 200,
           r.resource_payload:publisher::VARCHAR, NULL) AS publisher,
       d.discovered_at, r.registered_at,
       IFF(r.resource_type = 'CONTROLLED_ACCESS',
           'NO_AUTOMATED_ACQUISITION', 'RESEARCH_LEAD') AS acquisition_boundary
FROM GOVERNANCE.CATALOG_RESOURCES r
JOIN GOVERNANCE.CATALOG_DATASETS d
  ON d.catalog_dataset_id = r.catalog_dataset_id
JOIN GOVERNANCE.CATALOG_DISCOVERY_OBSERVATIONS o
  ON o.catalog_resource_id = r.catalog_resource_id
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY o.ingestion_run_id, r.resource_key
  ORDER BY o.observed_at DESC, d.discovered_at DESC, r.registered_at DESC,
           d.catalog_dataset_id DESC, r.catalog_resource_id DESC
) = 1;

CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CANDIDATE_EVIDENCE AS
SELECT o.ingestion_run_id AS discovery_run_id,
       o.observation_id, o.catalog_dataset_id, o.catalog_resource_id,
       o.canonical_resource_key AS resource_key, o.catalog_id,
       o.catalog_record_id, o.matched_term, o.observed_at,
       o.artifact_id, d.metadata_sha256
FROM GOVERNANCE.CATALOG_DISCOVERY_OBSERVATIONS o
JOIN GOVERNANCE.CATALOG_DATASETS d
  ON d.catalog_dataset_id = o.catalog_dataset_id;

-- Only reviewed metadata fields are available for fact validation. Oversize
-- values become unknown rather than silently truncated facts. This view does
-- not expose raw payload columns or private artifact bytes.
CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CANDIDATE_OBSERVATION_FIELDS AS
SELECT o.ingestion_run_id AS discovery_run_id,
       o.observation_id, o.canonical_resource_key AS resource_key,
       o.catalog_dataset_id, o.catalog_resource_id, o.observed_at,
       d.metadata_sha256,
       OBJECT_CONSTRUCT_KEEP_NULL(
         'title', IFF(LENGTH(r.resource_payload:title::VARCHAR) <= 300,
                      r.resource_payload:title::VARCHAR, NULL),
         'publisher', IFF(LENGTH(r.resource_payload:publisher::VARCHAR) <= 200,
                          r.resource_payload:publisher::VARCHAR, NULL),
         'description', IFF(LENGTH(d.metadata_payload:description::VARCHAR) <= 500,
                            d.metadata_payload:description::VARCHAR, NULL),
         'issued', IFF(LENGTH(d.metadata_payload:issued::VARCHAR) <= 100,
                       d.metadata_payload:issued::VARCHAR, NULL),
         'modified', IFF(LENGTH(d.metadata_payload:modified::VARCHAR) <= 100,
                         d.metadata_payload:modified::VARCHAR, NULL),
         'spatial', IFF(LENGTH(d.metadata_payload:spatial::VARCHAR) <= 300,
                        d.metadata_payload:spatial::VARCHAR, NULL),
         'temporal', IFF(LENGTH(d.metadata_payload:temporal::VARCHAR) <= 300,
                         d.metadata_payload:temporal::VARCHAR, NULL),
         'license', IFF(LENGTH(d.metadata_payload:license::VARCHAR) <= 300,
                        d.metadata_payload:license::VARCHAR, NULL),
         'access_level', IFF(LENGTH(d.metadata_payload:accessLevel::VARCHAR) <= 100,
                             d.metadata_payload:accessLevel::VARCHAR, NULL)
       ) AS field_values
FROM GOVERNANCE.CATALOG_DISCOVERY_OBSERVATIONS o
JOIN GOVERNANCE.CATALOG_DATASETS d
  ON d.catalog_dataset_id = o.catalog_dataset_id
JOIN GOVERNANCE.CATALOG_RESOURCES r
  ON r.catalog_resource_id = o.catalog_resource_id;

CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CANDIDATE_GOVERNED_STATUS AS
SELECT r.resource_key,
       MAX(IFF(v.retired_at IS NULL AND v.status IN ('APPROVED','CONDITIONAL'),
               1, 0)) = 1 AS already_governed,
       MAX(v.created_at) AS latest_source_version_at
FROM GOVERNANCE.CATALOG_RESOURCES r
LEFT JOIN GOVERNANCE.DATA_SOURCE_VERSIONS v ON v.resource_key = r.resource_key
GROUP BY r.resource_key;

-- Sequential writes cannot know the final ordinal until the run is complete.
-- Derive it deterministically from immutable priority inputs for each read.
CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_RANKED_RECOMMENDATIONS AS
SELECT rec.*,
       ROW_NUMBER() OVER (
         PARTITION BY rec.run_id
         ORDER BY CASE rec.priority_bucket
                    WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1
                    WHEN 'LOW' THEN 2 ELSE 3 END,
                  rec.priority_score DESC, rec.missing_count ASC,
                  rec.resource_key ASC, rec.recommendation_version_id ASC
       ) AS rank_in_run
FROM DATASET_DISCOVERY.RECOMMENDATIONS rec
WHERE rec.commit_complete = TRUE;

CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_PENDING_RECOMMENDATIONS AS
SELECT rec.recommendation_version_id, rec.recommendation_id, rec.run_id,
       rec.resource_key, rec.priority_bucket, rec.priority_score,
       rec.rank_in_run, rec.rationale, rec.rights_state, rec.created_at
FROM DATASET_DISCOVERY.V_RANKED_RECOMMENDATIONS rec
LEFT JOIN DATASET_DISCOVERY.REVIEW_EVENTS rev
  ON rev.recommendation_version_id = rec.recommendation_version_id
WHERE rec.commit_complete = TRUE
GROUP BY rec.recommendation_version_id, rec.recommendation_id, rec.run_id,
         rec.resource_key, rec.priority_bucket, rec.priority_score,
         rec.rank_in_run, rec.rationale, rec.rights_state, rec.created_at
HAVING COUNT(rev.review_event_id) = 0;

CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_RECOMMENDATION_HISTORY AS
SELECT rec.recommendation_id, rec.recommendation_version_id, rec.run_id,
       rec.resource_key, rec.assertion_sha256, rec.equivalent_to_version_id,
       rec.supersedes_version_id, rec.created_at, rev.review_event_id,
       rev.decision, rev.new_state, rev.reviewer_user, rev.reviewed_at
FROM DATASET_DISCOVERY.V_RANKED_RECOMMENDATIONS rec
LEFT JOIN DATASET_DISCOVERY.REVIEW_EVENTS rev
  ON rev.recommendation_version_id = rec.recommendation_version_id
WHERE rec.commit_complete = TRUE;

CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_ACCEPTED_RECOMMENDATIONS_FOR_HANDOFF AS
SELECT h.recommendation_id, h.recommendation_version_id, h.run_id,
       h.resource_key, h.review_event_id, h.reviewer_user, h.rights_state
FROM (
  SELECT rec.recommendation_id, rec.recommendation_version_id,
         rec.run_id, rec.resource_key, rec.rights_state,
         rev.review_event_id, rev.reviewer_user, rev.new_state,
         ROW_NUMBER() OVER (
           PARTITION BY rec.recommendation_version_id
           ORDER BY rev.reviewed_at DESC, rev.review_event_id DESC
         ) AS rn
  FROM DATASET_DISCOVERY.RECOMMENDATIONS rec
  JOIN DATASET_DISCOVERY.REVIEW_EVENTS rev
    ON rev.recommendation_version_id = rec.recommendation_version_id
  WHERE rec.commit_complete = TRUE
) h
WHERE h.rn = 1 AND h.new_state = 'ACCEPTED_FOR_INVESTIGATION';

CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_DISCOVERY_RUN_SUMMARY AS
SELECT r.run_id, r.retry_of_run_id, r.mode, r.status,
       r.started_at, r.heartbeat_at, r.completed_at, r.counters,
       r.stop_reason, r.redacted_error_code,
       COUNT(o.outcome_id) AS committed_candidate_outcomes
FROM DATASET_DISCOVERY.RUNS r
LEFT JOIN DATASET_DISCOVERY.CANDIDATE_OUTCOMES o ON o.run_id = r.run_id
GROUP BY r.run_id, r.retry_of_run_id, r.mode, r.status,
         r.started_at, r.heartbeat_at, r.completed_at, r.counters,
         r.stop_reason, r.redacted_error_code;
