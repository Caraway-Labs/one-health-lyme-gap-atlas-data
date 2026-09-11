USE DATABASE {{ DATABASE }};

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
  invalid_resource EXCEPTION (-20007, 'This DEV console supports only the two allowlisted geographic CDC eras');
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
  IF (RESOURCE_KEY IS NULL OR RESOURCE_KEY NOT IN ('cdc_lyme_x5j9_wybp', 'cdc_lyme_qtbi_xd4i')) THEN RAISE invalid_resource; END IF;
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
    WHERE r.resource_key = :RESOURCE_KEY AND r.is_active = TRUE AND ((r.resource_key = 'cdc_lyme_x5j9_wybp' AND r.api_dataset_id = 'x5j9-wybp') OR (r.resource_key = 'cdc_lyme_qtbi_xd4i' AND r.api_dataset_id = 'qtbi-xd4i'))
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

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_RECORD_SOURCE_REVIEW_DECISION(VARCHAR, VARCHAR, VARCHAR, VARIANT, VARCHAR, VARCHAR, VARCHAR)
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
