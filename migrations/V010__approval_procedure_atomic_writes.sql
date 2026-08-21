USE DATABASE {{ DATABASE }};

-- Execute this migration using OH_LYME_<ENV>_STREAMLIT_OWNER, which owns the
-- procedure. Snowflake requires current procedure ownership for replacement.
-- Bound VARIANT values are inserted through SELECT rather than VALUES because
-- this account rejects PARSE_JSON(:CONDITIONS) in a VALUES clause. The source
-- version and immutable review decision are one atomic operation.
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
  invalid_decision EXCEPTION (-20001, 'Unsupported review decision');
  invalid_rationale EXCEPTION (-20002, 'A 10-10,000 character rationale is required');
  missing_conditions EXCEPTION (-20003, 'Conditions or a deferral reason are required');
  unauthorized_steward EXCEPTION (-20004, 'Viewer is not an active steward for this resource');
  incomplete_evidence EXCEPTION (-20005, 'Approval prerequisites are incomplete or a material change is unresolved');
  steward_count NUMBER;
  evidence_count NUMBER;
  profile_count NUMBER;
  blocking_count NUMBER;
  prior_decision_id VARCHAR;
  decision_id VARCHAR DEFAULT UUID_STRING();
  source_version_id VARCHAR;
BEGIN
  BEGIN TRANSACTION;
  IF (DECISION NOT IN ('APPROVED', 'APPROVED_WITH_CONDITIONS', 'REJECTED', 'RETIRED', 'DEFERRED')) THEN
    RAISE invalid_decision;
  END IF;
  IF (RATIONALE IS NULL OR LENGTH(TRIM(RATIONALE)) < 10 OR LENGTH(RATIONALE) > 10000) THEN
    RAISE invalid_rationale;
  END IF;
  IF (DECISION IN ('APPROVED_WITH_CONDITIONS', 'REJECTED', 'RETIRED', 'DEFERRED')
      AND (CONDITIONS IS NULL OR ARRAY_SIZE(CONDITIONS) = 0)) THEN
    RAISE missing_conditions;
  END IF;

  SELECT COUNT(*) INTO :steward_count FROM GOVERNANCE.APPROVAL_STEWARDS
    WHERE username = :REVIEWER_USERNAME AND is_active = TRUE
      AND authorization_scope IN ('GLOBAL', :RESOURCE_KEY);
  IF (steward_count <> 1) THEN
    RAISE unauthorized_steward;
  END IF;

  SELECT manual_review_decision_id INTO :prior_decision_id
    FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS
    WHERE resource_key = :RESOURCE_KEY ORDER BY decided_at DESC LIMIT 1;

  IF (DECISION IN ('APPROVED', 'APPROVED_WITH_CONDITIONS')) THEN
    SELECT COUNT(*) INTO :evidence_count FROM GOVERNANCE.CATALOG_RESOURCES r
      WHERE r.resource_key = :RESOURCE_KEY
        AND EXISTS (SELECT 1 FROM GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS d WHERE d.resource_key = r.resource_key)
        AND EXISTS (SELECT 1 FROM GOVERNANCE.SCHEMA_SNAPSHOTS s WHERE s.resource_key = r.resource_key)
        AND EXISTS (SELECT 1 FROM GOVERNANCE.DATASET_QUALITY_ASSESSMENTS a
                    WHERE a.resource_key = r.resource_key AND a.assessment_status = 'PENDING_REVIEW');
    SELECT COUNT(*) INTO :profile_count FROM GOVERNANCE.SOURCE_ACCESS_PROFILES
      WHERE resource_key = :RESOURCE_KEY AND effective_to IS NULL;
    SELECT COUNT(*) INTO :blocking_count FROM GOVERNANCE.SCHEMA_CHANGE_EVENTS
      WHERE resource_key = :RESOURCE_KEY AND compatibility_outcome <> 'COMPATIBLE';
    IF (evidence_count <> 1 OR profile_count <> 1 OR blocking_count <> 0) THEN
      RAISE incomplete_evidence;
    END IF;
    source_version_id := UUID_STRING();
    INSERT INTO GOVERNANCE.DATA_SOURCE_VERSIONS
      (data_source_version_id, resource_key, status, approved_decision_id, created_at)
    SELECT :source_version_id, :RESOURCE_KEY,
           IFF(:DECISION = 'APPROVED', 'APPROVED', 'CONDITIONAL'), :decision_id, CURRENT_TIMESTAMP();
  END IF;

  INSERT INTO GOVERNANCE.MANUAL_REVIEW_DECISIONS
    (manual_review_decision_id, resource_key, decision, rationale, conditions,
     reviewer_username, supersedes_decision_id, data_source_version_id,
     app_version, correlation_id, decided_at)
  SELECT :decision_id, :RESOURCE_KEY, :DECISION, :RATIONALE, :CONDITIONS,
         :REVIEWER_USERNAME, :prior_decision_id, :source_version_id,
         :APP_VERSION, :CORRELATION_ID, CURRENT_TIMESTAMP();
  COMMIT;
  RETURN OBJECT_CONSTRUCT('decision_id', :decision_id, 'source_version_id', :source_version_id);
EXCEPTION
  WHEN OTHER THEN
    ROLLBACK;
    RAISE;
END;
$$;
