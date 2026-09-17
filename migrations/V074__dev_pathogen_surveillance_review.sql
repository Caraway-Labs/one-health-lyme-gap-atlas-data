-- DEV-only review boundary for the requestor-restricted CDC ArboNET pathogen candidate.
-- This exposes provenance and review metadata only; it never exposes workbook bytes or rows.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE VIEW GOVERNANCE.V_SOURCE_APPROVAL_QUEUE AS
WITH allowed AS (
  SELECT column1 AS resource_key FROM VALUES
    ('cdc_lyme_x5j9_wybp'), ('cdc_lyme_qtbi_xd4i'),
    ('cdc_tick_ixodes_county_status'), ('cdc_tick_ixodes_pathogen_status')
), latest_resource AS (
  SELECT r.*, d.catalog_name, d.dataset_key, d.catalog_record_id, d.metadata_payload, d.discovered_at
  FROM GOVERNANCE.CATALOG_RESOURCES r
  JOIN GOVERNANCE.CATALOG_DATASETS d ON d.catalog_dataset_id = r.catalog_dataset_id
  JOIN allowed a ON a.resource_key = r.resource_key
  WHERE r.is_active = TRUE
  QUALIFY ROW_NUMBER() OVER (PARTITION BY r.resource_key ORDER BY r.registered_at DESC) = 1
), latest_assessment AS (
  SELECT a.* FROM GOVERNANCE.DATASET_QUALITY_ASSESSMENTS a JOIN allowed x ON x.resource_key = a.resource_key
  QUALIFY ROW_NUMBER() OVER (PARTITION BY a.resource_key ORDER BY a.assessed_at DESC) = 1
), latest_decision AS (
  SELECT d.* FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS d JOIN allowed x ON x.resource_key = d.resource_key
  QUALIFY ROW_NUMBER() OVER (PARTITION BY d.resource_key ORDER BY d.decided_at DESC) = 1
), unresolved_events AS (
  SELECT e.resource_key, COUNT_IF(e.compatibility_outcome <> 'COMPATIBLE') AS material_schema_change_count
  FROM GOVERNANCE.SCHEMA_CHANGE_EVENTS e JOIN allowed x ON x.resource_key = e.resource_key GROUP BY e.resource_key
), unresolved_documents AS (
  SELECT d.resource_key, COUNT_IF(d.is_material_change) AS material_document_change_count
  FROM GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS d JOIN allowed x ON x.resource_key = d.resource_key GROUP BY d.resource_key
)
SELECT r.resource_key, r.resource_type, r.canonical_source_url, r.api_dataset_id,
       r.catalog_name, r.dataset_key, r.catalog_record_id, r.discovered_at,
       a.assessment_status, a.relevance_score, a.joinability_score, a.accessibility_score,
       a.documentation_score, a.quality_score, a.overall_score, a.recommendation,
       a.limitations, a.assessed_at, d.decision AS latest_decision, d.decided_at AS latest_decision_at,
       COALESCE(e.material_schema_change_count, 0) > 0 AS has_material_schema_change,
       COALESCE(doc.material_document_change_count, 0) > 0 AS has_material_document_change,
       IFF(COALESCE(e.material_schema_change_count, 0) > 0 OR COALESCE(doc.material_document_change_count, 0) > 0, TRUE, FALSE) AS has_blocking_issue
FROM latest_resource r
LEFT JOIN latest_assessment a ON a.resource_key = r.resource_key
LEFT JOIN latest_decision d ON d.resource_key = r.resource_key
LEFT JOIN unresolved_events e ON e.resource_key = r.resource_key
LEFT JOIN unresolved_documents doc ON doc.resource_key = r.resource_key
WHERE (d.manual_review_decision_id IS NULL AND a.assessment_status IN ('DRAFT', 'CONDITIONAL', 'PENDING_REVIEW'))
   OR COALESCE(e.material_schema_change_count, 0) > 0 OR COALESCE(doc.material_document_change_count, 0) > 0;

CREATE OR REPLACE VIEW GOVERNANCE.V_SOURCE_APPROVAL_DETAIL AS
WITH allowed AS (
  SELECT column1 AS resource_key FROM VALUES
    ('cdc_lyme_x5j9_wybp'), ('cdc_lyme_qtbi_xd4i'),
    ('cdc_tick_ixodes_county_status'), ('cdc_tick_ixodes_pathogen_status')
), resource AS (
  SELECT r.*, d.catalog_name, d.dataset_key, d.catalog_record_id, d.metadata_payload, d.metadata_sha256, d.discovered_at
  FROM GOVERNANCE.CATALOG_RESOURCES r
  JOIN GOVERNANCE.CATALOG_DATASETS d ON d.catalog_dataset_id = r.catalog_dataset_id
  JOIN allowed a ON a.resource_key = r.resource_key WHERE r.is_active = TRUE
  QUALIFY ROW_NUMBER() OVER (PARTITION BY r.resource_key ORDER BY r.registered_at DESC) = 1
), active_profile AS (
  SELECT p.* FROM GOVERNANCE.SOURCE_ACCESS_PROFILES p JOIN allowed a ON a.resource_key = p.resource_key
  WHERE p.effective_to IS NULL QUALIFY ROW_NUMBER() OVER (PARTITION BY p.resource_key ORDER BY p.effective_from DESC) = 1
), latest_assessment AS (
  SELECT a.* FROM GOVERNANCE.DATASET_QUALITY_ASSESSMENTS a JOIN allowed x ON x.resource_key = a.resource_key
  QUALIFY ROW_NUMBER() OVER (PARTITION BY a.resource_key ORDER BY a.assessed_at DESC) = 1
), latest_decision AS (
  SELECT d.* FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS d JOIN allowed x ON x.resource_key = d.resource_key
  QUALIFY ROW_NUMBER() OVER (PARTITION BY d.resource_key ORDER BY d.decided_at DESC) = 1
), document_evidence AS (
  SELECT d.resource_key, COUNT(*) AS document_snapshot_count,
    ARRAY_AGG(OBJECT_CONSTRUCT('type', d.document_type, 'url', d.document_url, 'sha256', d.content_sha256, 'retrieved_at', d.retrieved_at, 'is_material_change', d.is_material_change)) AS document_evidence
  FROM GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS d JOIN allowed a ON a.resource_key = d.resource_key GROUP BY d.resource_key
), schema_evidence AS (
  SELECT s.resource_key, COUNT(*) AS schema_snapshot_count,
    ARRAY_AGG(OBJECT_CONSTRUCT('fingerprint', s.schema_fingerprint, 'schema', s.schema_payload, 'retrieved_at', s.retrieved_at)) AS schema_evidence
  FROM GOVERNANCE.SCHEMA_SNAPSHOTS s JOIN allowed a ON a.resource_key = s.resource_key GROUP BY s.resource_key
), unresolved_events AS (
  SELECT e.resource_key, COUNT_IF(e.compatibility_outcome <> 'COMPATIBLE') AS material_schema_change_count
  FROM GOVERNANCE.SCHEMA_CHANGE_EVENTS e JOIN allowed a ON a.resource_key = e.resource_key GROUP BY e.resource_key
)
SELECT r.resource_key, r.resource_type, r.canonical_source_url, r.api_dataset_id,
       r.catalog_name, r.dataset_key, r.catalog_record_id, r.discovered_at,
       a.assessment_status, a.relevance_score, a.joinability_score, a.accessibility_score,
       a.documentation_score, a.quality_score, a.overall_score, a.recommendation,
       a.limitations, a.assessed_at, d.decision AS latest_decision, d.decided_at AS latest_decision_at,
       COALESCE(e.material_schema_change_count, 0) > 0 AS has_material_schema_change,
       EXISTS (SELECT 1 FROM GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS changed_doc WHERE changed_doc.resource_key = r.resource_key AND changed_doc.is_material_change) AS has_material_document_change,
       IFF(COALESCE(e.material_schema_change_count, 0) > 0 OR EXISTS (SELECT 1 FROM GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS changed_doc WHERE changed_doc.resource_key = r.resource_key AND changed_doc.is_material_change), TRUE, FALSE) AS has_blocking_issue,
       r.metadata_payload, r.metadata_sha256, r.resource_url, r.registered_at,
       p.profile_version, p.connector_name, p.deterministic_order_clause, p.incremental_strategy, p.configuration_sha256,
       COALESCE(doc.document_snapshot_count, 0) AS document_snapshot_count, doc.document_evidence,
       COALESCE(s.schema_snapshot_count, 0) AS schema_snapshot_count, s.schema_evidence,
       CASE
         WHEN r.resource_key = 'cdc_tick_ixodes_county_status' THEN 'Cumulative county tick-surveillance status through 2025-12-31. No records is not evidence of absence. Reported or established status is not abundance, pathogen prevalence, human infection incidence, or individual risk.'
         WHEN r.resource_key = 'cdc_tick_ixodes_pathogen_status' THEN 'Requestor-restricted CDC ArboNET cumulative county pathogen status through 2025-12-31. No records is not pathogen absence, a negative test, prevalence, human infection incidence, individual risk, or diagnosis. The source has no tested-tick counts, positive-tick counts, sampling effort, or laboratory-method detail; use PATHOGEN_PRESENCE_STATUS only. The workbook remains private.'
         ELSE 'County-of-residence human surveillance; use the source-specific reporting era. Do not compare eras without reviewed methodology. Non-geographic line-list data cannot join county contextual facts.'
       END AS cdc_guardrail
FROM resource r
LEFT JOIN active_profile p ON p.resource_key = r.resource_key
LEFT JOIN latest_assessment a ON a.resource_key = r.resource_key
LEFT JOIN latest_decision d ON d.resource_key = r.resource_key
LEFT JOIN unresolved_events e ON e.resource_key = r.resource_key
LEFT JOIN document_evidence doc ON doc.resource_key = r.resource_key
LEFT JOIN schema_evidence s ON s.resource_key = r.resource_key;

CREATE OR REPLACE VIEW GOVERNANCE.V_SOURCE_REVIEW_HISTORY AS
SELECT d.manual_review_decision_id, d.resource_key, d.decision, d.rationale, d.conditions,
       d.reviewer_username, d.supersedes_decision_id, d.data_source_version_id,
       d.app_version, d.correlation_id, d.decided_at, IFF(d.supersedes_decision_id IS NULL, FALSE, TRUE) AS supersedes_prior_decision
FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS d
WHERE d.resource_key IN ('cdc_lyme_x5j9_wybp', 'cdc_lyme_qtbi_xd4i', 'cdc_tick_ixodes_county_status', 'cdc_tick_ixodes_pathogen_status');

CREATE OR REPLACE VIEW GOVERNANCE.V_SOURCE_PIPELINE_STATUS AS
WITH allowed AS (
  SELECT column1 AS resource_key FROM VALUES
    ('cdc_lyme_x5j9_wybp'), ('cdc_lyme_qtbi_xd4i'),
    ('cdc_tick_ixodes_county_status'), ('cdc_tick_ixodes_pathogen_status')
), latest_version AS (
  SELECT v.* FROM GOVERNANCE.DATA_SOURCE_VERSIONS v JOIN allowed a ON a.resource_key = v.resource_key
  QUALIFY ROW_NUMBER() OVER (PARTITION BY v.resource_key ORDER BY v.created_at DESC) = 1
), latest_run AS (
  SELECT r.* FROM GOVERNANCE.INGESTION_RUNS r JOIN allowed a ON a.resource_key = r.resource_key
  QUALIFY ROW_NUMBER() OVER (PARTITION BY r.resource_key ORDER BY r.started_at DESC) = 1
)
SELECT seed.resource_key, v.data_source_version_id, v.status AS source_version_status,
       v.approved_decision_id, v.created_at, v.retired_at, r.status AS latest_ingestion_status,
       r.completed_at AS latest_ingestion_at,
       IFF(v.status IN ('APPROVED', 'CONDITIONAL') AND v.retired_at IS NULL, TRUE, FALSE) AS eligible_for_full_ingestion
FROM allowed seed LEFT JOIN latest_version v ON v.resource_key = seed.resource_key
LEFT JOIN latest_run r ON r.resource_key = seed.resource_key;

GRANT SELECT ON VIEW GOVERNANCE.V_SOURCE_APPROVAL_QUEUE TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_SOURCE_APPROVAL_DETAIL TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_SOURCE_REVIEW_HISTORY TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON VIEW GOVERNANCE.V_SOURCE_PIPELINE_STATUS TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
