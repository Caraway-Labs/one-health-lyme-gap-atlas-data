USE DATABASE {{ DATABASE }};

-- The initial governed approval-console delivery is deliberately limited to
-- the DEV CDC/Socrata x5j9-wybp candidate.  The ledger remains append-only;
-- later decisions supersede rather than mutate a prior decision.
CREATE OR REPLACE VIEW GOVERNANCE.V_SOURCE_APPROVAL_QUEUE AS
WITH latest_resource AS (
  SELECT r.*, d.catalog_name, d.dataset_key, d.catalog_record_id, d.metadata_payload,
         d.discovered_at
  FROM GOVERNANCE.CATALOG_RESOURCES r
  JOIN GOVERNANCE.CATALOG_DATASETS d ON d.catalog_dataset_id = r.catalog_dataset_id
  WHERE r.is_active = TRUE AND r.resource_key = 'cdc_lyme_x5j9_wybp'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY r.resource_key ORDER BY r.registered_at DESC) = 1
), latest_assessment AS (
  SELECT * FROM GOVERNANCE.DATASET_QUALITY_ASSESSMENTS
  WHERE resource_key = 'cdc_lyme_x5j9_wybp'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY resource_key ORDER BY assessed_at DESC) = 1
), latest_decision AS (
  SELECT * FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS
  WHERE resource_key = 'cdc_lyme_x5j9_wybp'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY resource_key ORDER BY decided_at DESC) = 1
), unresolved_events AS (
  SELECT resource_key,
         COUNT_IF(compatibility_outcome <> 'COMPATIBLE') AS material_schema_change_count
  FROM GOVERNANCE.SCHEMA_CHANGE_EVENTS
  WHERE resource_key = 'cdc_lyme_x5j9_wybp'
  GROUP BY resource_key
), unresolved_documents AS (
  SELECT resource_key, COUNT_IF(is_material_change) AS material_document_change_count
  FROM GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS
  WHERE resource_key = 'cdc_lyme_x5j9_wybp'
  GROUP BY resource_key
)
SELECT r.resource_key, r.resource_type, r.canonical_source_url, r.api_dataset_id,
       r.catalog_name, r.dataset_key, r.catalog_record_id, r.discovered_at,
       a.assessment_status, a.relevance_score, a.joinability_score, a.accessibility_score,
       a.documentation_score, a.quality_score, a.overall_score, a.recommendation,
       a.limitations, a.assessed_at, d.decision AS latest_decision,
       d.decided_at AS latest_decision_at,
       COALESCE(e.material_schema_change_count, 0) > 0 AS has_material_schema_change,
       COALESCE(doc.material_document_change_count, 0) > 0 AS has_material_document_change,
       IFF(COALESCE(e.material_schema_change_count, 0) > 0
           OR COALESCE(doc.material_document_change_count, 0) > 0, TRUE, FALSE) AS has_blocking_issue
FROM latest_resource r
LEFT JOIN latest_assessment a ON a.resource_key = r.resource_key
LEFT JOIN latest_decision d ON d.resource_key = r.resource_key
LEFT JOIN unresolved_events e ON e.resource_key = r.resource_key
LEFT JOIN unresolved_documents doc ON doc.resource_key = r.resource_key
WHERE (d.manual_review_decision_id IS NULL
       AND a.assessment_status IN ('DRAFT', 'CONDITIONAL', 'PENDING_REVIEW'))
   OR COALESCE(e.material_schema_change_count, 0) > 0
   OR COALESCE(doc.material_document_change_count, 0) > 0;

CREATE OR REPLACE VIEW GOVERNANCE.V_SOURCE_APPROVAL_DETAIL AS
WITH resource AS (
  SELECT r.*, d.catalog_name, d.dataset_key, d.catalog_record_id, d.metadata_payload,
         d.metadata_sha256, d.discovered_at
  FROM GOVERNANCE.CATALOG_RESOURCES r
  JOIN GOVERNANCE.CATALOG_DATASETS d ON d.catalog_dataset_id = r.catalog_dataset_id
  WHERE r.is_active = TRUE AND r.resource_key = 'cdc_lyme_x5j9_wybp'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY r.resource_key ORDER BY r.registered_at DESC) = 1
), active_profile AS (
  SELECT * FROM GOVERNANCE.SOURCE_ACCESS_PROFILES
  WHERE resource_key = 'cdc_lyme_x5j9_wybp' AND effective_to IS NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY resource_key ORDER BY effective_from DESC) = 1
), latest_assessment AS (
  SELECT * FROM GOVERNANCE.DATASET_QUALITY_ASSESSMENTS
  WHERE resource_key = 'cdc_lyme_x5j9_wybp'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY resource_key ORDER BY assessed_at DESC) = 1
), latest_decision AS (
  SELECT * FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS
  WHERE resource_key = 'cdc_lyme_x5j9_wybp'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY resource_key ORDER BY decided_at DESC) = 1
), document_evidence AS (
  SELECT resource_key, COUNT(*) AS document_snapshot_count,
         ARRAY_AGG(OBJECT_CONSTRUCT('type', document_type, 'url', document_url,
           'sha256', content_sha256, 'retrieved_at', retrieved_at,
           'is_material_change', is_material_change)) AS document_evidence
  FROM GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS WHERE resource_key = 'cdc_lyme_x5j9_wybp'
  GROUP BY resource_key
), schema_evidence AS (
  SELECT resource_key, COUNT(*) AS schema_snapshot_count,
         ARRAY_AGG(OBJECT_CONSTRUCT('fingerprint', schema_fingerprint,
           'schema', schema_payload, 'retrieved_at', retrieved_at)) AS schema_evidence
  FROM GOVERNANCE.SCHEMA_SNAPSHOTS WHERE resource_key = 'cdc_lyme_x5j9_wybp'
  GROUP BY resource_key
), unresolved_events AS (
  SELECT resource_key, COUNT_IF(compatibility_outcome <> 'COMPATIBLE') AS material_schema_change_count
  FROM GOVERNANCE.SCHEMA_CHANGE_EVENTS WHERE resource_key = 'cdc_lyme_x5j9_wybp'
  GROUP BY resource_key
)
SELECT r.resource_key, r.resource_type, r.canonical_source_url, r.api_dataset_id, r.catalog_name,
       r.dataset_key, r.catalog_record_id, r.discovered_at, a.assessment_status,
       a.relevance_score, a.joinability_score, a.accessibility_score, a.documentation_score,
       a.quality_score, a.overall_score, a.recommendation, a.limitations, a.assessed_at,
       d.decision AS latest_decision, d.decided_at AS latest_decision_at,
       COALESCE(e.material_schema_change_count, 0) > 0 AS has_material_schema_change,
       EXISTS (SELECT 1 FROM GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS changed_doc
               WHERE changed_doc.resource_key = r.resource_key AND changed_doc.is_material_change)
         AS has_material_document_change,
       IFF(COALESCE(e.material_schema_change_count, 0) > 0 OR EXISTS (
             SELECT 1 FROM GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS changed_doc
             WHERE changed_doc.resource_key = r.resource_key AND changed_doc.is_material_change), TRUE, FALSE)
         AS has_blocking_issue,
       r.metadata_payload, r.metadata_sha256, r.resource_url, r.registered_at,
       p.profile_version, p.connector_name, p.deterministic_order_clause,
       p.incremental_strategy, p.configuration_sha256,
       COALESCE(doc.document_snapshot_count, 0) AS document_snapshot_count,
       doc.document_evidence, COALESCE(s.schema_snapshot_count, 0) AS schema_snapshot_count,
       s.schema_evidence,
       'County-of-residence surveillance for the 2022-current reporting era. Do not compare across reporting eras without explicit reviewed methodology. Non-geographic line-list data cannot join county contextual facts.' AS cdc_guardrail
FROM resource r
LEFT JOIN active_profile p ON p.resource_key = r.resource_key
LEFT JOIN latest_assessment a ON a.resource_key = r.resource_key
LEFT JOIN latest_decision d ON d.resource_key = r.resource_key
LEFT JOIN unresolved_events e ON e.resource_key = r.resource_key
LEFT JOIN document_evidence doc ON doc.resource_key = r.resource_key
LEFT JOIN schema_evidence s ON s.resource_key = r.resource_key;

CREATE OR REPLACE VIEW GOVERNANCE.V_SOURCE_REVIEW_HISTORY AS
SELECT manual_review_decision_id, resource_key, decision, rationale, conditions,
       reviewer_username, supersedes_decision_id, data_source_version_id,
       app_version, correlation_id, decided_at,
       IFF(supersedes_decision_id IS NULL, FALSE, TRUE) AS supersedes_prior_decision
FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS
WHERE resource_key = 'cdc_lyme_x5j9_wybp';

CREATE OR REPLACE VIEW GOVERNANCE.V_SOURCE_PIPELINE_STATUS AS
WITH latest_version AS (
  SELECT * FROM GOVERNANCE.DATA_SOURCE_VERSIONS WHERE resource_key = 'cdc_lyme_x5j9_wybp'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY resource_key ORDER BY created_at DESC) = 1
), latest_run AS (
  SELECT * FROM GOVERNANCE.INGESTION_RUNS WHERE resource_key = 'cdc_lyme_x5j9_wybp'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY resource_key ORDER BY started_at DESC) = 1
)
SELECT 'cdc_lyme_x5j9_wybp' AS resource_key, v.data_source_version_id,
       v.status AS source_version_status, v.approved_decision_id, v.created_at,
       v.retired_at, r.status AS latest_ingestion_status, r.completed_at AS latest_ingestion_at,
       IFF(v.status IN ('APPROVED', 'CONDITIONAL') AND v.retired_at IS NULL,
           TRUE, FALSE) AS eligible_for_full_ingestion
FROM (SELECT 1) seed
LEFT JOIN latest_version v ON TRUE
LEFT JOIN latest_run r ON TRUE;

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_RECORD_SOURCE_REVIEW_DECISION(
  RESOURCE_KEY VARCHAR, DECISION VARCHAR, RATIONALE VARCHAR, CONDITIONS VARIANT,
  REVIEWER_USERNAME VARCHAR, APP_VERSION VARCHAR, CORRELATION_ID VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  invalid_resource EXCEPTION (-20000, 'This DEV console supports only CDC/Socrata x5j9-wybp');
  invalid_decision EXCEPTION (-20001, 'Unsupported review decision');
  invalid_rationale EXCEPTION (-20002, 'A 10-10,000 character rationale is required');
  missing_conditions EXCEPTION (-20003, 'Conditions or a deferral reason are required');
  invalid_request EXCEPTION (-20004, 'Reviewer, app version, and correlation ID are required');
  unauthorized_steward EXCEPTION (-20005, 'Viewer is not an active steward for this CDC resource');
  incomplete_evidence EXCEPTION (-20006, 'Approval is blocked: remediate missing evidence or unresolved material changes');
  steward_count NUMBER;
  evidence_count NUMBER;
  blocking_count NUMBER;
  prior_decision_id VARCHAR;
  active_source_version_id VARCHAR;
  decision_id VARCHAR DEFAULT UUID_STRING();
  source_version_id VARCHAR;
BEGIN
  BEGIN TRANSACTION;
  IF (RESOURCE_KEY <> 'cdc_lyme_x5j9_wybp') THEN RAISE invalid_resource; END IF;
  IF (DECISION NOT IN ('APPROVED', 'APPROVED_WITH_CONDITIONS', 'REJECTED', 'RETIRED', 'DEFERRED')) THEN RAISE invalid_decision; END IF;
  IF (RATIONALE IS NULL OR LENGTH(TRIM(RATIONALE)) < 10 OR LENGTH(RATIONALE) > 10000) THEN RAISE invalid_rationale; END IF;
  IF (DECISION IN ('APPROVED_WITH_CONDITIONS', 'REJECTED', 'RETIRED', 'DEFERRED')
      AND (CONDITIONS IS NULL OR NOT IS_ARRAY(CONDITIONS) OR ARRAY_SIZE(CONDITIONS) = 0)) THEN RAISE missing_conditions; END IF;
  IF (NULLIF(TRIM(REVIEWER_USERNAME), '') IS NULL OR NULLIF(TRIM(APP_VERSION), '') IS NULL
      OR NULLIF(TRIM(CORRELATION_ID), '') IS NULL) THEN RAISE invalid_request; END IF;

  SELECT COUNT(*) INTO :steward_count FROM GOVERNANCE.APPROVAL_STEWARDS s
  JOIN GOVERNANCE.CATALOG_RESOURCES r ON r.resource_key = :RESOURCE_KEY AND r.is_active = TRUE
  JOIN GOVERNANCE.CATALOG_DATASETS d ON d.catalog_dataset_id = r.catalog_dataset_id
  WHERE s.username = :REVIEWER_USERNAME AND s.is_active = TRUE
    AND s.authorization_scope IN ('GLOBAL', :RESOURCE_KEY, 'RESOURCE:' || :RESOURCE_KEY,
      'CATALOG:' || d.catalog_name, 'DOMAIN:cdc.gov');
  IF (steward_count < 1) THEN RAISE unauthorized_steward; END IF;

  SELECT manual_review_decision_id INTO :prior_decision_id
  FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS WHERE resource_key = :RESOURCE_KEY
  ORDER BY decided_at DESC LIMIT 1;
  SELECT data_source_version_id INTO :active_source_version_id
  FROM GOVERNANCE.DATA_SOURCE_VERSIONS WHERE resource_key = :RESOURCE_KEY
    AND retired_at IS NULL AND status IN ('APPROVED', 'CONDITIONAL')
  ORDER BY created_at DESC LIMIT 1;

  IF (DECISION IN ('APPROVED', 'APPROVED_WITH_CONDITIONS')) THEN
    SELECT COUNT(*) INTO :evidence_count FROM GOVERNANCE.CATALOG_RESOURCES r
    JOIN GOVERNANCE.CATALOG_DATASETS d ON d.catalog_dataset_id = r.catalog_dataset_id
    WHERE r.resource_key = :RESOURCE_KEY AND r.is_active = TRUE AND r.api_dataset_id = 'x5j9-wybp'
      AND d.metadata_payload IS NOT NULL
      AND EXISTS (SELECT 1 FROM GOVERNANCE.SOURCE_ACCESS_PROFILES p WHERE p.resource_key = r.resource_key
        AND p.effective_to IS NULL AND p.connector_name = 'SOCRATA_SODA2')
      AND EXISTS (SELECT 1 FROM GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS doc WHERE doc.resource_key = r.resource_key)
      AND EXISTS (SELECT 1 FROM GOVERNANCE.SCHEMA_SNAPSHOTS schema WHERE schema.resource_key = r.resource_key)
      AND EXISTS (SELECT 1 FROM GOVERNANCE.DATASET_QUALITY_ASSESSMENTS a WHERE a.resource_key = r.resource_key
        AND a.assessment_status = 'PENDING_REVIEW');
    SELECT COUNT(*) INTO :blocking_count FROM GOVERNANCE.SCHEMA_CHANGE_EVENTS e
      WHERE e.resource_key = :RESOURCE_KEY AND e.compatibility_outcome <> 'COMPATIBLE';
    SELECT :blocking_count + COUNT(*) INTO :blocking_count FROM GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS doc
      WHERE doc.resource_key = :RESOURCE_KEY AND doc.is_material_change = TRUE;
    IF (evidence_count < 1 OR blocking_count <> 0) THEN RAISE incomplete_evidence; END IF;
    source_version_id := UUID_STRING();
    INSERT INTO GOVERNANCE.DATA_SOURCE_VERSIONS
      (data_source_version_id, resource_key, status, approved_decision_id, created_at)
    SELECT :source_version_id, :RESOURCE_KEY, IFF(:DECISION = 'APPROVED', 'APPROVED', 'CONDITIONAL'),
           :decision_id, CURRENT_TIMESTAMP();
  END IF;

  -- Retiring/rejecting/defering a prior approved source prevents another full run;
  -- the historical version and decision are retained unchanged.
  IF (active_source_version_id IS NOT NULL) THEN
    UPDATE GOVERNANCE.DATA_SOURCE_VERSIONS SET status = 'RETIRED', retired_at = CURRENT_TIMESTAMP()
    WHERE data_source_version_id = :active_source_version_id AND retired_at IS NULL;
  END IF;
  INSERT INTO GOVERNANCE.MANUAL_REVIEW_DECISIONS
    (manual_review_decision_id, resource_key, decision, rationale, conditions, reviewer_username,
     supersedes_decision_id, data_source_version_id, app_version, correlation_id, decided_at)
  SELECT :decision_id, :RESOURCE_KEY, :DECISION, :RATIONALE, :CONDITIONS, :REVIEWER_USERNAME,
         :prior_decision_id, :source_version_id, :APP_VERSION, :CORRELATION_ID, CURRENT_TIMESTAMP();
  COMMIT;
  RETURN OBJECT_CONSTRUCT('decision_id', :decision_id, 'source_version_id', :source_version_id,
    'supersedes_decision_id', :prior_decision_id);
EXCEPTION WHEN OTHER THEN ROLLBACK; RAISE;
END;
$$;

GRANT SELECT ON VIEW GOVERNANCE.V_SOURCE_APPROVAL_QUEUE TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_SOURCE_APPROVAL_DETAIL TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_SOURCE_REVIEW_HISTORY TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_SOURCE_PIPELINE_STATUS TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT USAGE ON PROCEDURE GOVERNANCE.SP_RECORD_SOURCE_REVIEW_DECISION(VARCHAR, VARCHAR, VARCHAR, VARIANT, VARCHAR, VARCHAR, VARCHAR)
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
