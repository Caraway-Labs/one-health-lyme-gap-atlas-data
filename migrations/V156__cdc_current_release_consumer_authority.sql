-- API246: retain V149 source proof internally; preserve existing reader grants.
-- No receipt, source, decision, historical metadata or release pointer is rewritten.
-- No GRANT is introduced; no private table receives an added read privilege.
-- DATA429: expose the existing CDC authority through its intended-reader secure view.
-- No source, review, release pointer or grant changes. V148 remains immutable.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE SECURE VIEW LINEAGE_AUDIT.CDC_SOURCE_AUTHORITY_BASE_V AS
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


CREATE OR REPLACE SECURE VIEW LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V COPY GRANTS AS
WITH observation_content AS (
 SELECT observation_id,release_id,measure_id,fips,source_key,
   OBJECT_DELETE(OBJECT_CONSTRUCT_KEEP_NULL(o.*),'OBSERVATION_ID','RELEASE_ID','CREATED_AT') AS content
 FROM PRESENTATION.SEMANTIC_OBSERVATIONS o
 WHERE release_id IN ('governed-2026-10-15-january-climate-prod','governed-2026-10-06-nlcd-demo-cohort')
   AND measure_id IN ('scapularis_status','burgdorferi_status')
), source_content AS (
 SELECT release_id,source_key,resource_key,
   OBJECT_DELETE(OBJECT_CONSTRUCT_KEEP_NULL(s.*),'RELEASE_ID','CREATED_AT') AS content
 FROM PRESENTATION.SEMANTIC_DATA_SOURCES s
), dataset_content AS (
 SELECT release_id,dataset_id,
   OBJECT_DELETE(OBJECT_CONSTRUCT_KEEP_NULL(d.*),'RELEASE_ID','CREATED_AT') AS content
 FROM PRESENTATION.SEMANTIC_DATASETS d
), measure_content AS (
 SELECT release_id,measure_id,
   OBJECT_DELETE(OBJECT_CONSTRUCT_KEEP_NULL(m.*),'RELEASE_ID','CREATED_AT') AS content
 FROM PRESENTATION.SEMANTIC_MEASURES m
), equivalent_pairs AS (
 SELECT a.observation_id AS current_observation_id,b.observation_id AS donor_observation_id
 FROM observation_content a
 JOIN observation_content b ON a.measure_id=b.measure_id AND a.fips=b.fips AND a.content=b.content
 JOIN source_content sa ON sa.release_id=a.release_id AND sa.source_key=a.source_key
 JOIN source_content sb ON sb.release_id=b.release_id AND sb.source_key=b.source_key
   AND sa.content=sb.content
 JOIN dataset_content da ON da.release_id=a.release_id
   AND da.dataset_id=sa.content:DATASET_ID::VARCHAR
 JOIN dataset_content db ON db.release_id=b.release_id AND db.dataset_id=da.dataset_id
   AND da.content=db.content
 JOIN measure_content ma ON ma.release_id=a.release_id AND ma.measure_id=a.measure_id
 JOIN measure_content mb ON mb.release_id=b.release_id AND mb.measure_id=b.measure_id
   AND ma.content=mb.content
 JOIN PRESENTATION.SEMANTIC_RELEASES ra ON ra.release_id=a.release_id
 JOIN PRESENTATION.SEMANTIC_RELEASES rb ON rb.release_id=b.release_id
 -- Existing DATA443 January exact-pair version exception, unchanged CDC meaning.
 WHERE a.release_id='governed-2026-10-15-january-climate-prod'
   AND b.release_id='governed-2026-10-06-nlcd-demo-cohort'
   AND ra.schema_version='2.0.0' AND ra.methodology_version='semantic-2.0.0'
   AND rb.schema_version='1.0.0' AND rb.methodology_version='semantic-1.0.0'
   AND ra.limitations=rb.limitations
)
SELECT current_row.* REPLACE (
  CASE WHEN current_row.release_id='governed-2026-10-15-january-climate-prod'
    THEN OBJECT_INSERT(OBJECT_INSERT(OBJECT_INSERT(current_row.cdc_runtime_authority,
      'attestations', COALESCE(donor.cdc_runtime_authority:attestations, ARRAY_CONSTRUCT()), TRUE),
      'donor_record_equivalent', donor.observation_id IS NOT NULL, TRUE),
      'donor_observation_id', donor.observation_id, TRUE)
    ELSE current_row.cdc_runtime_authority END AS cdc_runtime_authority)
FROM LINEAGE_AUDIT.CDC_SOURCE_AUTHORITY_BASE_V current_row
LEFT JOIN equivalent_pairs proof ON proof.current_observation_id=current_row.observation_id
LEFT JOIN LINEAGE_AUDIT.CDC_SOURCE_AUTHORITY_BASE_V donor
 ON current_row.release_id='governed-2026-10-15-january-climate-prod'
 AND donor.observation_id=proof.donor_observation_id
 AND current_row.release_bundle_sha256='53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d'
 AND donor.release_id='governed-2026-10-06-nlcd-demo-cohort'
 AND donor.release_bundle_sha256='603afb135a1a5c958d1d56d48d580d9942c67eb38986caf8b4b3acf69fcde2c9'
 AND current_row.measure_id=donor.measure_id AND current_row.county_fips=donor.county_fips
 AND current_row.source_version_id=donor.source_version_id
 AND current_row.governed_source_version_id=donor.governed_source_version_id
 AND current_row.source_id=donor.source_id AND current_row.dataset_id=donor.dataset_id
 AND current_row.resource_key=donor.resource_key
 AND current_row.ingestion_run_id=donor.ingestion_run_id
 AND current_row.governed_ingestion_run_id=donor.governed_ingestion_run_id
 AND current_row.artifact_id=donor.artifact_id
 AND current_row.artifact_sha256=donor.artifact_sha256
 AND current_row.conformed_record_id=donor.conformed_record_id
 AND current_row.governed_source_record_id=donor.governed_source_record_id
 AND current_row.governed_source_row_hash=donor.governed_source_row_hash
 AND current_row.semantic_source_record_id=donor.semantic_source_record_id
 AND current_row.semantic_source_row_hash=donor.semantic_source_row_hash
 AND current_row.record_match_kind='RESTRICTED_CDC_CONFORMED'
 AND donor.record_match_kind='RESTRICTED_CDC_CONFORMED'
 AND current_row.temporal_window=donor.temporal_window
 AND current_row.cdc_runtime_authority:value IS NOT DISTINCT FROM donor.cdc_runtime_authority:value
 AND current_row.cdc_runtime_authority:value_state IS NOT DISTINCT FROM donor.cdc_runtime_authority:value_state
 AND current_row.cdc_runtime_authority:publisher_value IS NOT DISTINCT FROM donor.cdc_runtime_authority:publisher_value
 AND current_row.cdc_runtime_authority:coverage_state IS NOT DISTINCT FROM donor.cdc_runtime_authority:coverage_state
 AND current_row.cdc_runtime_authority:retrieved_at IS NOT DISTINCT FROM donor.cdc_runtime_authority:retrieved_at
 AND current_row.cdc_runtime_authority:transformation_version IS NOT DISTINCT FROM donor.cdc_runtime_authority:transformation_version
 AND COALESCE(donor.cdc_runtime_authority:coverage_state::VARCHAR,'')<>'UNKNOWN_SOURCE_COVERAGE';

-- An authenticated active human steward, never a pipeline runtime, appends the
-- separately reviewed target packet after protected deployment. No source
-- decision is superseded and no receipt or release pointer is changed.
CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_REGISTER_CDC_TARGET_ADMISSION(
  MEASURE_ID VARCHAR, PACKET VARIANT, SIGNED_REFERENCE VARCHAR
)
RETURNS VARIANT LANGUAGE SQL EXECUTE AS OWNER AS
$$
DECLARE
  denied EXCEPTION (-20170, 'CDC admission requires exact reviewed owner scope');
  invalid_map EXCEPTION (-20171, 'CDC admission membership reconciliation failed');
  version_id VARCHAR;
  resource VARCHAR;
  dataset VARCHAR;
  metadata_id VARCHAR;
  prior_metadata_id VARCHAR;
  binding_count NUMBER;
  valid_count NUMBER;
  valid_observations NUMBER;
  valid_counties NUMBER;
  existing_count NUMBER;
  decision_id VARCHAR DEFAULT UUID_STRING();
BEGIN
  IF (COALESCE((CURRENT_DATABASE()<>'ONE_HEALTH_LYME_GAP_ATLAS_PROD'
      OR CURRENT_DATE()<'2026-10-17'::DATE
      OR (SELECT COUNT(*) FROM GOVERNANCE.APPROVAL_STEWARDS
          WHERE username=CURRENT_USER() AND is_active=TRUE
            AND authorization_scope='GLOBAL')<>1
      OR :MEASURE_ID NOT IN ('scapularis_status','burgdorferi_status')
      OR LENGTH(TRIM(:SIGNED_REFERENCE))<6),TRUE)) THEN RAISE denied; END IF;
  version_id := IFF(:MEASURE_ID='scapularis_status',
    'b81c116f-d93d-4c6b-9d11-ac2477e0e242','92b22f19-0d5d-4576-a7c6-6c9af9343edf');
  resource := IFF(:MEASURE_ID='scapularis_status',
    'cdc_tick_ixodes_county_status','cdc_tick_ixodes_pathogen_status');
  dataset := IFF(:MEASURE_ID='scapularis_status',
    'cdc-ixodes-county-status-2025','cdc-ixodes-pathogen-status-2025');
  metadata_id := IFF(:MEASURE_ID='scapularis_status',
    'metadata-revision:v1:3300365cfd0af87dcc80afdd94aa4b35f8651b2ab5ba898edb8a282f562016fd',
    'metadata-revision:v1:f864fe95d98836fcc030e5b2a15d3a63c2bec50011cde1de59318b34219188f0');
  prior_metadata_id := IFF(:MEASURE_ID='scapularis_status',
    'metadata-revision:v1:c60fb91162b5ed33d34a01d3fef24e0a4a2ef8976bbd07ac1082fd783adfb509',
    'metadata-revision:v1:01b6eaf0d3f6e96ebf8ac9020e31584f55175c95d676e40d3da7d430b9b08522');
  IF (COALESCE((NOT IS_OBJECT(:PACKET) OR ARRAY_SIZE(OBJECT_KEYS(:PACKET))<>8
    OR :PACKET:release_id::VARCHAR<>'governed-2026-10-15-january-climate-prod'
    OR :PACKET:bundle_sha256::VARCHAR<>'53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d'
    OR :PACKET:scope:resource_key::VARCHAR<>:resource
    OR :PACKET:scope:dataset_id::VARCHAR<>:dataset
    OR :PACKET:scope:source_version_id::VARCHAR<>:version_id
    OR :PACKET:metadata_revision_id::VARCHAR<>:metadata_id
    OR :PACKET:reviewed_at::VARCHAR<>'2026-10-17'
    OR :PACKET:decision_reference::VARCHAR<>:SIGNED_REFERENCE
    OR :PACKET:restricted_copy_reuse:donor_release_id::VARCHAR<>'governed-2026-10-06-nlcd-demo-cohort'
    OR :PACKET:restricted_copy_reuse:donor_bundle_sha256::VARCHAR<>'603afb135a1a5c958d1d56d48d580d9942c67eb38986caf8b4b3acf69fcde2c9'
    OR ARRAY_SIZE(:PACKET:restricted_copy_reuse:attestation_ids)<>1
    OR NOT IS_OBJECT(:PACKET:observation_bindings)),TRUE)) THEN RAISE denied; END IF;
  SELECT COUNT(*) INTO :existing_count
  FROM PRESENTATION.SEMANTIC_RELEASES
  WHERE release_id='governed-2026-10-15-january-climate-prod' AND status='PUBLISHED'
    AND bundle_sha256='53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d';
  IF (existing_count<>1) THEN RAISE denied; END IF;
  SELECT COUNT(*) INTO :existing_count
  FROM GOVERNANCE.RESTRICTED_SOURCE_PUBLICATION_ATTESTATIONS
  WHERE semantic_release_id='governed-2026-10-06-nlcd-demo-cohort'
    AND resource_key=:resource AND data_source_version_id=:version_id
    AND attestation_id=:PACKET:restricted_copy_reuse:attestation_ids[0]::VARCHAR
    AND LENGTH(TRIM(delivery_reference))>=6 AND LENGTH(TRIM(attested_by))>0
    AND delivered_at IS NOT NULL;
  IF (existing_count<>1) THEN RAISE denied; END IF;
  SELECT COUNT(*) INTO :existing_count
  FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS d,
    LATERAL FLATTEN(input=>d.conditions) c
  WHERE d.resource_key=:resource AND d.data_source_version_id=:version_id
    AND c.value:cdc_consumer_admission:release_id::VARCHAR=:PACKET:release_id::VARCHAR
    AND NOT EXISTS (SELECT 1 FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS n
                    WHERE n.supersedes_decision_id=d.manual_review_decision_id);
  IF (existing_count<>0) THEN RAISE denied; END IF;
  binding_count := ARRAY_SIZE(OBJECT_KEYS(:PACKET:observation_bindings));
  -- Full exact membership, not a count-only assertion. Each revision must match
  -- retained scientific authority; Oct17 metadata preserves its meaning signature.
  WITH admitted AS (
    SELECT l.observation_id, l.county_fips, b.value AS binding,
      GET(c.value:cdc_consumer_admission:observation_bindings,
          l.cdc_runtime_authority:donor_observation_id::VARCHAR) AS donor_binding
    FROM LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V l,
      LATERAL FLATTEN(input=>:PACKET:observation_bindings) b,
      LATERAL FLATTEN(input=>l.cdc_runtime_authority:review_decisions) r,
      LATERAL FLATTEN(input=>r.value:conditions) c
    WHERE l.release_id=:PACKET:release_id::VARCHAR AND l.measure_id=:MEASURE_ID
      AND l.observation_id=b.key AND l.source_version_id=:version_id
      AND l.record_match_kind='RESTRICTED_CDC_CONFORMED'
      AND l.cdc_runtime_authority:donor_record_equivalent::BOOLEAN=TRUE
      AND l.cdc_runtime_authority:source_status::VARCHAR IN ('APPROVED','CONDITIONAL')
      AND IS_NULL_VALUE(l.cdc_runtime_authority:source_retired_at)
      AND l.cdc_runtime_authority:source_decision::VARCHAR IN ('APPROVED','APPROVED_WITH_CONDITIONS')
      AND l.cdc_runtime_authority:derivation_status::VARCHAR='COMPLETED'
      AND l.cdc_runtime_authority:evidence_status::VARCHAR='COMPLETED'
      AND b.value:record_id::VARCHAR=l.conformed_record_id
      AND b.value:donor_observation_id::VARCHAR=l.cdc_runtime_authority:donor_observation_id::VARCHAR
      AND r.value:active_steward::BOOLEAN=TRUE
      AND r.value:decision::VARCHAR IN ('APPROVED','APPROVED_WITH_CONDITIONS')
      AND r.value:decided_at::VARCHAR='2026-10-11'
      AND c.value:cdc_consumer_admission:release_id::VARCHAR='governed-2026-10-06-nlcd-demo-cohort'
      AND c.value:cdc_consumer_admission:bundle_sha256::VARCHAR='603afb135a1a5c958d1d56d48d580d9942c67eb38986caf8b4b3acf69fcde2c9'
      AND c.value:cdc_consumer_admission:metadata_revision_id::VARCHAR=:prior_metadata_id
  )
  SELECT COUNT(*), COUNT(DISTINCT observation_id), COUNT(DISTINCT county_fips)
    INTO :valid_count, :valid_observations, :valid_counties FROM admitted
  WHERE binding:record_id::VARCHAR=donor_binding:record_id::VARCHAR
    AND binding:semantic_revision_id::VARCHAR=donor_binding:semantic_revision_id::VARCHAR;
  IF (COALESCE(binding_count,-1)<>3109 OR valid_count<>3109
      OR valid_observations<>3109 OR valid_counties<>3109) THEN RAISE invalid_map; END IF;
  INSERT INTO GOVERNANCE.MANUAL_REVIEW_DECISIONS
    (manual_review_decision_id,resource_key,decision,rationale,conditions,
     reviewer_username,data_source_version_id,app_version,correlation_id,decided_at)
  SELECT :decision_id,:resource,'APPROVED_WITH_CONDITIONS',
    'API246 owner-approved unchanged CDC carry-forward; exact record and receipt reconciliation',
    ARRAY_CONSTRUCT(OBJECT_CONSTRUCT('cdc_consumer_admission',:PACKET)),
    CURRENT_USER(),:version_id,'api246-cdc-admission-v1',UUID_STRING(),CURRENT_TIMESTAMP();
  RETURN OBJECT_CONSTRUCT('decision_id',:decision_id,'measure_id',:MEASURE_ID,
    'admitted_records',:binding_count,'release_id',:PACKET:release_id::VARCHAR);
END;
$$;
