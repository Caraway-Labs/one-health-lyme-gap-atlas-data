-- DATA429: expose the existing CDC authority through its intended-reader secure view.
-- No source, review, release pointer or grant changes. V148 remains immutable.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE SECURE VIEW LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V COPY GRANTS AS
WITH active_stewards AS (
  SELECT username, COUNT(*) AS steward_count FROM GOVERNANCE.APPROVAL_STEWARDS
  WHERE is_active=TRUE AND authorization_scope='GLOBAL' GROUP BY username
), cdc_reviews AS (
  SELECT d.resource_key, d.data_source_version_id,
         ARRAY_AGG(OBJECT_CONSTRUCT_KEEP_NULL(
           'decision_id', d.manual_review_decision_id, 'decision', d.decision,
           'reviewer', d.reviewer_username, 'decided_at', TO_VARCHAR(d.decided_at, 'YYYY-MM-DD'),
           'rationale', d.rationale, 'conditions', d.conditions,
           'active_steward', COALESCE(st.steward_count, 0)=1)) AS decisions
  FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS d
  LEFT JOIN active_stewards st ON st.username=d.reviewer_username
  WHERE d.resource_key IN ('cdc_tick_ixodes_county_status', 'cdc_tick_ixodes_pathogen_status')
    AND NOT EXISTS (SELECT 1 FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS newer
                    WHERE newer.supersedes_decision_id=d.manual_review_decision_id)
  GROUP BY d.resource_key, d.data_source_version_id
), cdc_attestations AS (
  SELECT semantic_release_id, resource_key, data_source_version_id,
         ARRAY_AGG(OBJECT_CONSTRUCT_KEEP_NULL(
           'attestation_id', attestation_id, 'semantic_release_id', semantic_release_id,
           'resource_key', resource_key, 'data_source_version_id', data_source_version_id,
           'delivery_reference', delivery_reference, 'delivered_at', TO_VARCHAR(delivered_at),
           'attested_by', attested_by)) AS attestations
  FROM GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS
  WHERE semantic_release_id='governed-2026-10-06-nlcd-demo-cohort'
  GROUP BY semantic_release_id, resource_key, data_source_version_id
)
SELECT o.observation_id,
       o.release_id,
       o.measure_id,
       o.fips AS county_fips,
       o.temporal_window,
       o.source_key,
       o.source_version_id,
       dsv.data_source_version_id AS governed_source_version_id,
       o.ingestion_run_id,
       run.ingestion_run_id AS governed_ingestion_run_id,
       o.artifact_id,
       a.sha256 AS artifact_sha256,
       o.source_record_id AS semantic_source_record_id,
       o.source_row_hash AS semantic_source_row_hash,
       s.source_id,
       s.dataset_id,
       s.resource_key,
       r.bundle_sha256 AS release_bundle_sha256,
       v.record_id AS revision_record_id,
       v.capture_record_id,
       v.record_revision,
       v.artifact_sha256 AS revision_artifact_sha256,
       COALESCE(c.record_id, t.conformed_record_id, p.conformed_record_id) AS conformed_record_id,
       COALESCE(v.source_record_id, c.source_record_id, t.source_record_id,
                p.source_record_id) AS governed_source_record_id,
       COALESCE(v.source_row_hash, c.source_row_hash, t.source_row_hash,
                p.source_row_hash) AS governed_source_row_hash,
       CASE WHEN v.capture_record_id IS NOT NULL THEN 'IMMUTABLE_REVISION'
            WHEN c.record_id IS NOT NULL THEN 'LEGACY_CONFORMED'
            WHEN t.conformed_record_id IS NOT NULL OR p.conformed_record_id IS NOT NULL
              THEN 'RESTRICTED_CDC_CONFORMED'
            ELSE 'UNMATCHED' END AS record_match_kind,
       CASE WHEN t.conformed_record_id IS NOT NULL OR p.conformed_record_id IS NOT NULL
         THEN OBJECT_CONSTRUCT_KEEP_NULL(
           'source_vintage', s.vintage, 'source_status', dsv.status,
           'source_retired_at', TO_VARCHAR(dsv.retired_at),
           'source_decision', source_review.decision,
           'source_decision_id', source_review.manual_review_decision_id,
           'source_conditions', source_review.conditions,
           'source_review_version', source_review.data_source_version_id,
           'source_review_resource', source_review.resource_key,
           'release_status', r.status, 'value', o.value, 'value_state', o.value_state,
           'geography_semantics', o.geography_semantics,
           'transformation_version', o.transformation_version,
           'derivation_status', run.status, 'derivation_mode', run.run_mode,
           'evidence_run_id', COALESCE(t.evidence_run_id, p.evidence_run_id),
           'evidence_status', evidence.status, 'evidence_mode', evidence.run_mode,
           'evidence_resource', evidence.resource_key,
           'artifact_run_id', a.ingestion_run_id, 'artifact_type', a.artifact_type,
           'source_definition_version', COALESCE(t.source_definition_version,
                                                  p.source_definition_version),
           'record_resource', COALESCE(t.resource_key, p.resource_key),
           'record_county', COALESCE(t.county_fips, p.county_fips),
           'publisher_value', COALESCE(t.scapularis_status, p.burgdorferi_status),
           'coverage_state', COALESCE(t.coverage_state, p.coverage_state),
           'workbook_sha256', COALESCE(t.workbook_sha256, p.workbook_sha256),
           'retrieved_at', TO_VARCHAR(COALESCE(t.retrieved_at, p.retrieved_at),
                                      'YYYY-MM-DD\"T\"HH24:MI:SS.FF3TZH:TZM'),
           'review_decisions', reviews.decisions, 'attestations', attest.attestations)
         ELSE NULL END AS cdc_runtime_authority
FROM PRESENTATION.SEMANTIC_OBSERVATIONS o
JOIN PRESENTATION.SEMANTIC_RELEASES r ON r.release_id = o.release_id
JOIN PRESENTATION.SEMANTIC_DATA_SOURCES s
  ON s.release_id = o.release_id AND s.source_key = o.source_key
 AND s.source_version_id = o.source_version_id
 AND s.ingestion_run_id = o.ingestion_run_id
 AND s.artifact_id = o.artifact_id
LEFT JOIN GOVERNANCE.DATA_SOURCE_VERSIONS dsv
  ON dsv.data_source_version_id = o.source_version_id
 AND dsv.resource_key = s.resource_key
 AND (dsv.ingestion_run_id IS NULL OR dsv.ingestion_run_id = o.ingestion_run_id)
 AND (dsv.artifact_id IS NULL OR dsv.artifact_id = o.artifact_id)
LEFT JOIN GOVERNANCE.INGESTION_RUNS run
  ON run.ingestion_run_id = o.ingestion_run_id
 AND run.resource_key = s.resource_key
LEFT JOIN GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS v
  ON v.source_id = s.source_id AND v.dataset_id = s.dataset_id
 AND v.resource_key = s.resource_key AND v.ingestion_run_id = o.ingestion_run_id
 AND v.artifact_id = o.artifact_id AND v.source_row_hash = o.source_row_hash
 AND (o.source_record_id IS NULL OR v.source_record_id = o.source_record_id
      OR v.record_id = o.source_record_id)
LEFT JOIN CONFORMED.GOVERNED_SOURCE_RECORDS c
  ON v.capture_record_id IS NULL
 AND c.source_id = s.source_id AND c.dataset_id = s.dataset_id
 AND c.resource_key = s.resource_key AND c.ingestion_run_id = o.ingestion_run_id
 AND c.source_row_hash = o.source_row_hash
 AND (o.source_record_id IS NULL OR c.source_record_id = o.source_record_id
      OR c.record_id = o.source_record_id)
LEFT JOIN CONFORMED.RESTRICTED_CDC_TICK_COUNTY_STATUS t
  ON v.capture_record_id IS NULL AND c.record_id IS NULL
 AND o.source_key = 'tick' AND s.resource_key = 'cdc_tick_ixodes_county_status'
 AND s.source_id = 'cdc_arbonet_tick_module' AND s.dataset_id = 'cdc-ixodes-county-status-2025'
 AND t.resource_key = s.resource_key AND t.ingestion_run_id = o.ingestion_run_id
 AND t.county_fips = o.fips AND t.source_row_hash = o.source_row_hash
 AND (o.source_record_id IS NULL OR t.source_record_id = o.source_record_id
      OR t.conformed_record_id = o.source_record_id)
LEFT JOIN CONFORMED.RESTRICTED_CDC_PATHOGEN_COUNTY_STATUS p
  ON v.capture_record_id IS NULL AND c.record_id IS NULL
 AND o.source_key = 'pathogen' AND s.resource_key = 'cdc_tick_ixodes_pathogen_status'
 AND s.source_id = 'cdc_arbonet_tick_module' AND s.dataset_id = 'cdc-ixodes-pathogen-status-2025'
 AND p.resource_key = s.resource_key AND p.ingestion_run_id = o.ingestion_run_id
 AND p.county_fips = o.fips AND p.source_row_hash = o.source_row_hash
 AND (o.source_record_id IS NULL OR p.source_record_id = o.source_record_id
      OR p.conformed_record_id = o.source_record_id)
LEFT JOIN GOVERNANCE.RAW_ARTIFACTS a
  ON a.artifact_id = o.artifact_id
 AND a.ingestion_run_id = COALESCE(t.evidence_run_id, p.evidence_run_id, o.ingestion_run_id)
 AND (t.conformed_record_id IS NULL OR a.sha256 = t.workbook_sha256)
 AND (p.conformed_record_id IS NULL OR a.sha256 = p.workbook_sha256)
LEFT JOIN GOVERNANCE.INGESTION_RUNS evidence
  ON evidence.ingestion_run_id=COALESCE(t.evidence_run_id, p.evidence_run_id)
 AND evidence.resource_key=s.resource_key
LEFT JOIN GOVERNANCE.MANUAL_REVIEW_DECISIONS source_review
  ON source_review.manual_review_decision_id=dsv.approved_decision_id
LEFT JOIN cdc_reviews reviews ON reviews.resource_key=s.resource_key
 AND reviews.data_source_version_id=o.source_version_id
LEFT JOIN cdc_attestations attest ON attest.semantic_release_id=o.release_id
 AND attest.resource_key=s.resource_key AND attest.data_source_version_id=o.source_version_id;

-- The supplied CDC admission approves an already published release. Preserve the
-- original candidate path; admit late final-copy evidence only for this exact
-- reviewed published slice, through the existing steward-owned action.
CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_RECORD_RESTRICTED_FINAL_COPY_PROD(
    SEMANTIC_RELEASE_ID VARCHAR, RESOURCE_KEY VARCHAR, DELIVERY_REFERENCE VARCHAR, ATTESTED_BY VARCHAR
)
COPY GRANTS RETURNS VARIANT LANGUAGE SQL EXECUTE AS OWNER AS
$$
DECLARE invalid_environment EXCEPTION (-20154, 'Restricted final-copy attestation is PROD-only');
  invalid_input EXCEPTION (-20155, 'Release, resource, delivery reference, and attestor are required');
  invalid_release EXCEPTION (-20156, 'Candidate or exact reviewed CDC admission is required');
  source_version_id VARCHAR; attestation_id VARCHAR DEFAULT UUID_STRING();
BEGIN
  IF (CURRENT_DATABASE() <> 'ONE_HEALTH_LYME_GAP_ATLAS_PROD') THEN RAISE invalid_environment; END IF;
  IF (NULLIF(TRIM(SEMANTIC_RELEASE_ID),'') IS NULL OR RESOURCE_KEY NOT IN ('cdc_tick_ixodes_county_status','cdc_tick_ixodes_pathogen_status') OR LENGTH(TRIM(DELIVERY_REFERENCE)) < 6 OR NULLIF(TRIM(ATTESTED_BY),'') IS NULL) THEN RAISE invalid_input; END IF;
  SELECT s.source_version_id INTO :source_version_id
  FROM PRESENTATION.SEMANTIC_DATA_SOURCES s
  JOIN PRESENTATION.SEMANTIC_RELEASES r ON r.release_id=s.release_id
  WHERE s.release_id=:SEMANTIC_RELEASE_ID AND s.resource_key=:RESOURCE_KEY
    AND (r.status='CANDIDATE' OR (
      r.status='PUBLISHED' AND r.release_id='governed-2026-10-06-nlcd-demo-cohort'
      AND r.bundle_sha256='603afb135a1a5c958d1d56d48d580d9942c67eb38986caf8b4b3acf69fcde2c9'
      AND :ATTESTED_BY=CURRENT_USER()
      AND ((s.resource_key='cdc_tick_ixodes_county_status' AND s.source_version_id='b81c116f-d93d-4c6b-9d11-ac2477e0e242')
        OR (s.resource_key='cdc_tick_ixodes_pathogen_status' AND s.source_version_id='92b22f19-0d5d-4576-a7c6-6c9af9343edf'))
      AND (SELECT COUNT(*) FROM GOVERNANCE.APPROVAL_STEWARDS st
           WHERE st.username=:ATTESTED_BY AND st.is_active=TRUE AND st.authorization_scope='GLOBAL')=1
      AND EXISTS (
        SELECT 1 FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS d,
          LATERAL FLATTEN(INPUT=>d.conditions) condition
        WHERE d.resource_key=s.resource_key AND d.data_source_version_id=s.source_version_id
          AND d.reviewer_username=:ATTESTED_BY AND d.decision IN ('APPROVED','APPROVED_WITH_CONDITIONS')
          AND NOT EXISTS (SELECT 1 FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS newer
                          WHERE newer.supersedes_decision_id=d.manual_review_decision_id)
          AND condition.value:cdc_consumer_admission:release_id::VARCHAR=r.release_id
          AND condition.value:cdc_consumer_admission:bundle_sha256::VARCHAR=r.bundle_sha256
          AND condition.value:cdc_consumer_admission:scope:resource_key::VARCHAR=s.resource_key
          AND condition.value:cdc_consumer_admission:scope:source_version_id::VARCHAR=s.source_version_id
          AND condition.value:cdc_consumer_admission:metadata_revision_id::VARCHAR=IFF(
            s.resource_key='cdc_tick_ixodes_county_status',
            'metadata-revision:v1:c60fb91162b5ed33d34a01d3fef24e0a4a2ef8976bbd07ac1082fd783adfb509',
            'metadata-revision:v1:01b6eaf0d3f6e96ebf8ac9020e31584f55175c95d676e40d3da7d430b9b08522')
          AND LENGTH(TRIM(condition.value:cdc_consumer_admission:decision_reference::VARCHAR))>=6
          AND IS_OBJECT(condition.value:cdc_consumer_admission:observation_bindings)
      )
    ))
  QUALIFY ROW_NUMBER() OVER (ORDER BY s.created_at DESC)=1;
  IF (source_version_id IS NULL) THEN RAISE invalid_release; END IF;
  INSERT INTO GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS(attestation_id, semantic_release_id, resource_key, data_source_version_id, delivery_reference, delivered_at, attested_by)
  VALUES (:attestation_id, :SEMANTIC_RELEASE_ID, :RESOURCE_KEY, :source_version_id, :DELIVERY_REFERENCE, CURRENT_TIMESTAMP(), :ATTESTED_BY);
  RETURN OBJECT_CONSTRUCT('attestation_id', :attestation_id, 'semantic_release_id', :SEMANTIC_RELEASE_ID, 'resource_key', :RESOURCE_KEY);
END;
$$;
