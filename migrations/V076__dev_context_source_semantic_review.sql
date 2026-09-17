-- DEV-only semantic-review gate for the two contextual sources in Epic #252.
-- It creates an immutable source-version decision only after a particular
-- Tier-B run has retained artifact, complete-stage, quality, and staged-publication evidence.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_RECORD_CONTEXT_SOURCE_SEMANTIC_DECISION(
  RESOURCE_KEY VARCHAR, INGESTION_RUN_ID VARCHAR, DECISION VARCHAR, RATIONALE VARCHAR,
  CONDITIONS VARIANT, REVIEWER_USERNAME VARCHAR, CORRELATION_ID VARCHAR
)
RETURNS VARIANT LANGUAGE SQL EXECUTE AS OWNER AS
$$
DECLARE
  invalid_resource EXCEPTION (-20101, 'Only the reviewed SVI and RUCC context sources are supported');
  invalid_decision EXCEPTION (-20102, 'Only approval decisions are supported');
  invalid_rationale EXCEPTION (-20103, 'A 10-10,000 character rationale is required');
  invalid_conditions EXCEPTION (-20104, 'Approved-with-conditions requires one or more conditions');
  invalid_request EXCEPTION (-20105, 'Run, reviewer, and correlation ID are required');
  unauthorized_steward EXCEPTION (-20106, 'Viewer is not an active global steward');
  incomplete_evidence EXCEPTION (-20107, 'Approval is blocked: the exact completed Tier-B run lacks required immutable evidence');
  steward_count NUMBER; run_count NUMBER; stage_count NUMBER; artifact_count NUMBER;
  publication_count NUMBER; failed_quality_count NUMBER; prior_decision_id VARCHAR;
  active_source_version_id VARCHAR; decision_id VARCHAR DEFAULT UUID_STRING(); source_version_id VARCHAR;
BEGIN
  BEGIN TRANSACTION;
  IF (RESOURCE_KEY IS NULL OR RESOURCE_KEY NOT IN ('cdc_atsdr_svi_2022_county', 'usda_ers_rucc_2023')) THEN RAISE invalid_resource; END IF;
  IF (DECISION NOT IN ('APPROVED', 'APPROVED_WITH_CONDITIONS')) THEN RAISE invalid_decision; END IF;
  IF (RATIONALE IS NULL OR LENGTH(TRIM(RATIONALE)) < 10 OR LENGTH(RATIONALE) > 10000) THEN RAISE invalid_rationale; END IF;
  IF (DECISION = 'APPROVED_WITH_CONDITIONS' AND (CONDITIONS IS NULL OR NOT IS_ARRAY(CONDITIONS) OR ARRAY_SIZE(CONDITIONS) = 0)) THEN RAISE invalid_conditions; END IF;
  IF (NULLIF(TRIM(INGESTION_RUN_ID), '') IS NULL OR NULLIF(TRIM(REVIEWER_USERNAME), '') IS NULL OR NULLIF(TRIM(CORRELATION_ID), '') IS NULL) THEN RAISE invalid_request; END IF;

  SELECT COUNT(*) INTO :steward_count
  FROM GOVERNANCE.APPROVAL_STEWARDS
  WHERE username = :REVIEWER_USERNAME AND is_active = TRUE AND authorization_scope = 'GLOBAL';
  IF (steward_count <> 1) THEN RAISE unauthorized_steward; END IF;

  SELECT COUNT(*) INTO :run_count
  FROM GOVERNANCE.INGESTION_RUNS
  WHERE ingestion_run_id = :INGESTION_RUN_ID AND resource_key = :RESOURCE_KEY
    AND trigger_type = 'B' AND status = 'COMPLETED';
  SELECT COUNT(*) INTO :stage_count
  FROM GOVERNANCE.INGESTION_RUN_CHECKPOINTS
  WHERE ingestion_run_id = :INGESTION_RUN_ID AND status = 'COMPLETED';
  SELECT COUNT(*) INTO :artifact_count
  FROM GOVERNANCE.INGESTION_RUN_CHECKPOINTS
  WHERE ingestion_run_id = :INGESTION_RUN_ID AND stage = 'ACQUIRE' AND status = 'COMPLETED'
    AND artifact_id IS NOT NULL AND REGEXP_LIKE(artifact_sha256, '^[0-9a-f]{64}$');
  SELECT COUNT(*) INTO :publication_count
  FROM GOVERNANCE.INGESTION_PUBLICATIONS
  WHERE ingestion_run_id = :INGESTION_RUN_ID AND resource_key = :RESOURCE_KEY
    AND status = 'STAGED' AND record_count > 0;
  SELECT COUNT(*) INTO :failed_quality_count
  FROM GOVERNANCE.DATA_QUALITY_RESULTS
  WHERE ingestion_run_id = :INGESTION_RUN_ID AND severity = 'BLOCKING' AND status <> 'PASSED';
  IF (run_count <> 1 OR stage_count <> 6 OR artifact_count <> 1 OR publication_count <> 1 OR failed_quality_count <> 0) THEN RAISE incomplete_evidence; END IF;

  SELECT manual_review_decision_id INTO :prior_decision_id
  FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS WHERE resource_key = :RESOURCE_KEY
  ORDER BY decided_at DESC LIMIT 1;
  SELECT data_source_version_id INTO :active_source_version_id
  FROM GOVERNANCE.DATA_SOURCE_VERSIONS WHERE resource_key = :RESOURCE_KEY
    AND retired_at IS NULL AND status IN ('APPROVED', 'CONDITIONAL')
  ORDER BY created_at DESC LIMIT 1;
  source_version_id := UUID_STRING();
  INSERT INTO GOVERNANCE.DATA_SOURCE_VERSIONS (data_source_version_id, resource_key, status, approved_decision_id, created_at)
  SELECT :source_version_id, :RESOURCE_KEY, IFF(:DECISION = 'APPROVED', 'APPROVED', 'CONDITIONAL'), :decision_id, CURRENT_TIMESTAMP();
  IF (active_source_version_id IS NOT NULL) THEN
    UPDATE GOVERNANCE.DATA_SOURCE_VERSIONS SET status = 'RETIRED', retired_at = CURRENT_TIMESTAMP()
    WHERE data_source_version_id = :active_source_version_id AND retired_at IS NULL;
  END IF;
  INSERT INTO GOVERNANCE.MANUAL_REVIEW_DECISIONS
    (manual_review_decision_id, resource_key, decision, rationale, conditions, reviewer_username,
     supersedes_decision_id, data_source_version_id, app_version, correlation_id, decided_at)
  SELECT :decision_id, :RESOURCE_KEY, :DECISION, :RATIONALE, :CONDITIONS, :REVIEWER_USERNAME,
         :prior_decision_id, :source_version_id, 'context-semantic-review-v1', :CORRELATION_ID, CURRENT_TIMESTAMP();
  COMMIT;
  RETURN OBJECT_CONSTRUCT('decision_id', :decision_id, 'source_version_id', :source_version_id,
                          'ingestion_run_id', :INGESTION_RUN_ID, 'supersedes_decision_id', :prior_decision_id);
EXCEPTION WHEN OTHER THEN ROLLBACK; RAISE;
END;
$$;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_RECORD_CONTEXT_SOURCE_SEMANTIC_DECISION(
  VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARIANT, VARCHAR, VARCHAR
) TO ROLE OH_LYME_DEV_STREAMLIT_OWNER;
