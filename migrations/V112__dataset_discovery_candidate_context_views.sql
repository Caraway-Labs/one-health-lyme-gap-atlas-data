USE DATABASE {{ DATABASE }};

-- Prior governed assessments are context, not Dataset Discovery scores or
-- source approval. Cut off at the catalog observation time so a later review
-- cannot silently change what an earlier discovery run could have seen.
CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CANDIDATE_PRIOR_ASSESSMENT AS
SELECT evidence.discovery_run_id,
       evidence.resource_key,
       evidence.catalog_dataset_id,
       evidence.catalog_resource_id,
       assessment.dataset_quality_assessment_id,
       assessment.assessment_status,
       assessment.assessed_at
FROM DATASET_DISCOVERY.V_CANDIDATE_EVIDENCE evidence
JOIN GOVERNANCE.DATASET_QUALITY_ASSESSMENTS assessment
  ON assessment.resource_key = evidence.resource_key
 AND assessment.assessed_at <= evidence.observed_at
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY evidence.discovery_run_id, evidence.resource_key,
               evidence.catalog_dataset_id, evidence.catalog_resource_id
  ORDER BY assessment.assessed_at DESC,
           assessment.dataset_quality_assessment_id DESC
) = 1;

-- Exact discovery artifact metadata only. Exclude private object URI, raw
-- bytes, request endpoint and payload. The app may inspect provenance but
-- receives no artifact-fetch or governed-ingestion capability.
CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CANDIDATE_ARTIFACT_METADATA AS
SELECT evidence.discovery_run_id,
       evidence.resource_key,
       evidence.catalog_dataset_id,
       evidence.catalog_resource_id,
       evidence.observation_id,
       artifact.artifact_id,
       artifact.artifact_type,
       artifact.media_type,
       artifact.byte_count,
       artifact.sha256,
       artifact.retention_class,
       artifact.created_at
FROM DATASET_DISCOVERY.V_CANDIDATE_EVIDENCE evidence
JOIN GOVERNANCE.RAW_ARTIFACTS artifact
  ON artifact.artifact_id = evidence.artifact_id
 AND artifact.ingestion_run_id = evidence.discovery_run_id;

-- Runtime SELECT grants remain subject to owner/security approval of ADR 0041.
