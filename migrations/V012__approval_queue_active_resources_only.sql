USE DATABASE {{ DATABASE }};

-- Keep deactivated DEV fixtures and retired catalog resources out of the human
-- approval console while retaining their append-only lineage for audit.
CREATE OR REPLACE VIEW GOVERNANCE.V_SOURCE_APPROVAL_QUEUE AS
WITH latest_assessment AS (
  SELECT * FROM GOVERNANCE.DATASET_QUALITY_ASSESSMENTS
  QUALIFY ROW_NUMBER() OVER (PARTITION BY resource_key ORDER BY assessed_at DESC) = 1
), latest_decision AS (
  SELECT * FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS
  QUALIFY ROW_NUMBER() OVER (PARTITION BY resource_key ORDER BY decided_at DESC) = 1
)
SELECT r.resource_key, r.resource_type, r.canonical_source_url, r.api_dataset_id,
       d.catalog_name, d.dataset_key, a.assessment_status, a.overall_score,
       a.recommendation, a.limitations, a.assessed_at, ld.decision AS latest_decision,
       ld.decided_at AS latest_decision_at,
       EXISTS (
         SELECT 1 FROM GOVERNANCE.SCHEMA_CHANGE_EVENTS e
         WHERE e.resource_key = r.resource_key AND e.compatibility_outcome <> 'COMPATIBLE'
       ) AS has_material_schema_change
FROM GOVERNANCE.CATALOG_RESOURCES r
LEFT JOIN GOVERNANCE.CATALOG_DATASETS d ON d.catalog_dataset_id = r.catalog_dataset_id
LEFT JOIN latest_assessment a ON a.resource_key = r.resource_key
LEFT JOIN latest_decision ld ON ld.resource_key = r.resource_key
WHERE r.is_active = TRUE;
