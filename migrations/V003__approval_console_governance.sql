USE DATABASE {{ DATABASE }};

CREATE WAREHOUSE IF NOT EXISTS OH_LYME_{{ ENV }}_APPROVAL_XS_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE;

CREATE ROLE IF NOT EXISTS OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
CREATE ROLE IF NOT EXISTS OH_LYME_{{ ENV }}_DATA_STEWARD;
CREATE ROLE IF NOT EXISTS OH_LYME_{{ ENV }}_APPROVAL_VIEWER;
CREATE ROLE IF NOT EXISTS OH_LYME_{{ ENV }}_SECURITY_ADMIN;

CREATE TABLE IF NOT EXISTS GOVERNANCE.APPROVAL_STEWARDS (
  username VARCHAR PRIMARY KEY,
  authorization_scope VARCHAR NOT NULL DEFAULT 'GLOBAL',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  granted_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  granted_by VARCHAR NOT NULL DEFAULT CURRENT_USER()
);

ALTER TABLE GOVERNANCE.MANUAL_REVIEW_DECISIONS
  ADD COLUMN IF NOT EXISTS app_version VARCHAR;
ALTER TABLE GOVERNANCE.MANUAL_REVIEW_DECISIONS
  ADD COLUMN IF NOT EXISTS correlation_id VARCHAR;
ALTER TABLE GOVERNANCE.MANUAL_REVIEW_DECISIONS
  ADD COLUMN IF NOT EXISTS data_source_version_id VARCHAR;

ALTER TABLE RAW.CDC_LYME_X5J9_WYBP
  ADD COLUMN IF NOT EXISTS source_value_status VARIANT;
ALTER TABLE RAW.CDC_LYME_X5J9_WYBP
  ADD COLUMN IF NOT EXISTS raw_load_batch_id VARCHAR;

CREATE STAGE IF NOT EXISTS GOVERNANCE.STREAMLIT_SOURCE_STAGE
  ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE');
CREATE STAGE IF NOT EXISTS RAW.INGESTION_TRANSIENT_STAGE
  ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE');

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
LEFT JOIN latest_decision ld ON ld.resource_key = r.resource_key;

CREATE OR REPLACE VIEW GOVERNANCE.V_SOURCE_APPROVAL_DETAIL AS
SELECT q.*, r.resource_payload, p.profile_version, p.connector_name,
       p.endpoint_template, p.deterministic_order_clause, p.incremental_strategy,
       p.configuration_sha256,
       (SELECT COUNT(*) FROM GOVERNANCE.SOURCE_DOCUMENT_SNAPSHOTS ds
        WHERE ds.resource_key = q.resource_key) AS document_snapshot_count,
       (SELECT COUNT(*) FROM GOVERNANCE.SCHEMA_SNAPSHOTS ss
        WHERE ss.resource_key = q.resource_key) AS schema_snapshot_count
FROM GOVERNANCE.V_SOURCE_APPROVAL_QUEUE q
JOIN GOVERNANCE.CATALOG_RESOURCES r USING (resource_key)
LEFT JOIN GOVERNANCE.SOURCE_ACCESS_PROFILES p ON p.resource_key = q.resource_key
  AND p.effective_to IS NULL;

CREATE OR REPLACE VIEW GOVERNANCE.V_SOURCE_REVIEW_HISTORY AS
SELECT manual_review_decision_id, resource_key, decision, rationale, conditions,
       reviewer_username, supersedes_decision_id, data_source_version_id,
       app_version, correlation_id, decided_at
FROM GOVERNANCE.MANUAL_REVIEW_DECISIONS;

CREATE OR REPLACE VIEW GOVERNANCE.V_ACTIVE_APPROVAL_STEWARDS AS
SELECT username, authorization_scope
FROM GOVERNANCE.APPROVAL_STEWARDS
WHERE is_active = TRUE;

CREATE OR REPLACE VIEW GOVERNANCE.V_SOURCE_PIPELINE_STATUS AS
SELECT r.resource_key, v.data_source_version_id, v.status AS source_version_status,
       v.approved_decision_id, v.created_at, v.retired_at,
       q.latest_decision, q.latest_decision_at,
       IFF(v.status IN ('APPROVED', 'CONDITIONAL') AND v.retired_at IS NULL, TRUE, FALSE)
         AS eligible_for_full_ingestion
FROM GOVERNANCE.CATALOG_RESOURCES r
LEFT JOIN GOVERNANCE.DATA_SOURCE_VERSIONS v ON v.resource_key = r.resource_key
  AND v.retired_at IS NULL
LEFT JOIN GOVERNANCE.V_SOURCE_APPROVAL_QUEUE q ON q.resource_key = r.resource_key;

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
    VALUES (:source_version_id, :RESOURCE_KEY,
            IFF(:DECISION = 'APPROVED', 'APPROVED', 'CONDITIONAL'), :decision_id, CURRENT_TIMESTAMP());
  END IF;

  INSERT INTO GOVERNANCE.MANUAL_REVIEW_DECISIONS
    (manual_review_decision_id, resource_key, decision, rationale, conditions,
     reviewer_username, supersedes_decision_id, data_source_version_id,
     app_version, correlation_id, decided_at)
  VALUES (:decision_id, :RESOURCE_KEY, :DECISION, :RATIONALE, :CONDITIONS,
          :REVIEWER_USERNAME, :prior_decision_id, :source_version_id,
          :APP_VERSION, :CORRELATION_ID, CURRENT_TIMESTAMP());
  RETURN OBJECT_CONSTRUCT('decision_id', :decision_id, 'source_version_id', :source_version_id);
END;
$$;

GRANT USAGE ON WAREHOUSE OH_LYME_{{ ENV }}_APPROVAL_XS_WH TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT USAGE ON DATABASE {{ DATABASE }} TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT USAGE ON SCHEMA GOVERNANCE TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT SELECT ON ALL VIEWS IN SCHEMA GOVERNANCE TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT USAGE ON PROCEDURE GOVERNANCE.SP_RECORD_SOURCE_REVIEW_DECISION(VARCHAR, VARCHAR, VARCHAR, VARIANT, VARCHAR, VARCHAR, VARCHAR)
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT READ, WRITE ON STAGE GOVERNANCE.STREAMLIT_SOURCE_STAGE TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT CREATE STREAMLIT ON SCHEMA GOVERNANCE TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
GRANT ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER TO ROLE OH_LYME_{{ ENV }}_SECURITY_ADMIN;
GRANT ROLE OH_LYME_{{ ENV }}_DATA_STEWARD TO USER MATTHEWCARAWAY;

MERGE INTO GOVERNANCE.APPROVAL_STEWARDS target
USING (SELECT 'MATTHEWCARAWAY' AS username, 'GLOBAL' AS authorization_scope) source
ON target.username = source.username
WHEN MATCHED THEN UPDATE SET is_active = TRUE, authorization_scope = source.authorization_scope
WHEN NOT MATCHED THEN INSERT (username, authorization_scope, is_active)
  VALUES (source.username, source.authorization_scope, TRUE);

GRANT OWNERSHIP ON PROCEDURE GOVERNANCE.SP_RECORD_SOURCE_REVIEW_DECISION(VARCHAR, VARCHAR, VARCHAR, VARIANT, VARCHAR, VARCHAR, VARCHAR)
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER COPY CURRENT GRANTS;
