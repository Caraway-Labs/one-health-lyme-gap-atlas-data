-- DEV-only extension of the existing human-review boundary; no source approval or RAW writes.
USE DATABASE {{ DATABASE }};

-- Extend DEV review to the two allowlisted geographic CDC eras.
-- The ledger remains append-only;
-- later decisions supersede rather than mutate a prior decision.
CREATE OR REPLACE VIEW GOVERNANCE.V_SOURCE_APPROVAL_QUEUE AS
WITH latest_resource AS (
  SELECT r.*, d.catalog_name, d.dataset_key, d.catalog_record_id, d.metadata_payload,
         d.discovered_at
  FROM GOVERNANCE.CATALOG_RESOURCES r
  JOIN GOVERNANCE.CATALOG_DATASETS d ON d.catalog_dataset_id = r.catalog_dataset_id
  WHERE r.is_active = TRUE AND r.resource_key IN ('cdc_lyme_x5j9_wybp', 'cdc_lyme_qtbi_xd4i')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY r.resource_key ORDER BY r.registered_at DESC) = 1
), latest_assessment AS (
  SELECT * FROM GOVERNANCE.DATASET_QUALITY_ASSESSMENTS
  WHERE resource_key IN ('cdc_lyme_x5j9_wybp', 'cdc_lyme_qtbi_xd4i')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY resource_key ORDER BY assessed_at DESC) = 1
), latest_decision AS (
  SELECT * FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS
  WHERE resource_key IN ('cdc_lyme_x5j9_wybp', 'cdc_lyme_qtbi_xd4i')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY resource_key ORDER BY decided_at DESC) = 1
), unresolved_events AS (
  SELECT resource_key,
         COUNT_IF(compatibility_outcome <> 'COMPATIBLE') AS material_schema_change_count
  FROM GOVERNANCE.SCHEMA_CHANGE_EVENTS
  WHERE resource_key IN ('cdc_lyme_x5j9_wybp', 'cdc_lyme_qtbi_xd4i')
  GROUP BY resource_key
), unresolved_documents AS (
  SELECT resource_key, COUNT_IF(is_material_change) AS material_document_change_count
  FROM GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS
  WHERE resource_key IN ('cdc_lyme_x5j9_wybp', 'cdc_lyme_qtbi_xd4i')
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
  WHERE r.is_active = TRUE AND r.resource_key IN ('cdc_lyme_x5j9_wybp', 'cdc_lyme_qtbi_xd4i')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY r.resource_key ORDER BY r.registered_at DESC) = 1
), active_profile AS (
  SELECT * FROM GOVERNANCE.SOURCE_ACCESS_PROFILES
  WHERE resource_key IN ('cdc_lyme_x5j9_wybp', 'cdc_lyme_qtbi_xd4i') AND effective_to IS NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY resource_key ORDER BY effective_from DESC) = 1
), latest_assessment AS (
  SELECT * FROM GOVERNANCE.DATASET_QUALITY_ASSESSMENTS
  WHERE resource_key IN ('cdc_lyme_x5j9_wybp', 'cdc_lyme_qtbi_xd4i')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY resource_key ORDER BY assessed_at DESC) = 1
), latest_decision AS (
  SELECT * FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS
  WHERE resource_key IN ('cdc_lyme_x5j9_wybp', 'cdc_lyme_qtbi_xd4i')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY resource_key ORDER BY decided_at DESC) = 1
), document_evidence AS (
  SELECT resource_key, COUNT(*) AS document_snapshot_count,
         ARRAY_AGG(OBJECT_CONSTRUCT('type', document_type, 'url', document_url,
           'sha256', content_sha256, 'retrieved_at', retrieved_at,
           'is_material_change', is_material_change)) AS document_evidence
  FROM GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS WHERE resource_key IN ('cdc_lyme_x5j9_wybp', 'cdc_lyme_qtbi_xd4i')
  GROUP BY resource_key
), schema_evidence AS (
  SELECT resource_key, COUNT(*) AS schema_snapshot_count,
         ARRAY_AGG(OBJECT_CONSTRUCT('fingerprint', schema_fingerprint,
           'schema', schema_payload, 'retrieved_at', retrieved_at)) AS schema_evidence
  FROM GOVERNANCE.SCHEMA_SNAPSHOTS WHERE resource_key IN ('cdc_lyme_x5j9_wybp', 'cdc_lyme_qtbi_xd4i')
  GROUP BY resource_key
), unresolved_events AS (
  SELECT resource_key, COUNT_IF(compatibility_outcome <> 'COMPATIBLE') AS material_schema_change_count
  FROM GOVERNANCE.SCHEMA_CHANGE_EVENTS WHERE resource_key IN ('cdc_lyme_x5j9_wybp', 'cdc_lyme_qtbi_xd4i')
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
       'County-of-residence surveillance; use the source-specific era (x5j9: 2022-current; qtbi: 2008-2021). Do not compare across reporting eras without explicit reviewed methodology. Non-geographic line-list data cannot join county contextual facts.' AS cdc_guardrail
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
WHERE resource_key IN ('cdc_lyme_x5j9_wybp', 'cdc_lyme_qtbi_xd4i');

CREATE OR REPLACE VIEW GOVERNANCE.V_SOURCE_PIPELINE_STATUS AS
WITH latest_version AS (
  SELECT * FROM GOVERNANCE.DATA_SOURCE_VERSIONS WHERE resource_key IN ('cdc_lyme_x5j9_wybp', 'cdc_lyme_qtbi_xd4i')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY resource_key ORDER BY created_at DESC) = 1
), latest_run AS (
  SELECT * FROM GOVERNANCE.INGESTION_RUNS WHERE resource_key IN ('cdc_lyme_x5j9_wybp', 'cdc_lyme_qtbi_xd4i')
  QUALIFY ROW_NUMBER() OVER (PARTITION BY resource_key ORDER BY started_at DESC) = 1
)
SELECT seed.resource_key, v.data_source_version_id,
       v.status AS source_version_status, v.approved_decision_id, v.created_at,
       v.retired_at, r.status AS latest_ingestion_status, r.completed_at AS latest_ingestion_at,
       IFF(v.status IN ('APPROVED', 'CONDITIONAL') AND v.retired_at IS NULL,
           TRUE, FALSE) AS eligible_for_full_ingestion
FROM (SELECT 'cdc_lyme_x5j9_wybp' AS resource_key UNION ALL SELECT 'cdc_lyme_qtbi_xd4i') seed
LEFT JOIN latest_version v ON v.resource_key = seed.resource_key
LEFT JOIN latest_run r ON r.resource_key = seed.resource_key;




GRANT SELECT ON VIEW GOVERNANCE.V_SOURCE_APPROVAL_QUEUE TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_SOURCE_APPROVAL_DETAIL TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_SOURCE_REVIEW_HISTORY TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_SOURCE_PIPELINE_STATUS TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
