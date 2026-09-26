-- Epic #63 / Data #129: Atlas user-feedback persistence.
--
-- GOVERNANCE-only. No RAW/STAGING/CONFORMED/PRESENTATION objects.
-- Env-neutral: required in both DEV and PROD.
--
-- Standard Snowflake does not enforce UNIQUE / PRIMARY KEY constraints, so
-- cross-process races on submission_token are prevented by the API
-- single-process lock, not by a primary key. UUID_STRING() is used only in
-- INSERT...SELECT (or DECLARE DEFAULT), never inside VALUES.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS GOVERNANCE.USER_FEEDBACK (
    feedback_id VARCHAR PRIMARY KEY,
    received_at TIMESTAMP_LTZ NOT NULL,
    stored_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    schema_version VARCHAR NOT NULL,
    category VARCHAR NOT NULL,
    message VARCHAR NOT NULL,
    route_id VARCHAR NOT NULL,
    context VARIANT,
    app_version VARCHAR NOT NULL,
    submission_token VARCHAR NOT NULL,
    payload_fingerprint VARCHAR NOT NULL,
    triage_state VARCHAR NOT NULL DEFAULT 'new',
    duplicate_of_feedback_id VARCHAR
);

CREATE TABLE IF NOT EXISTS GOVERNANCE.USER_FEEDBACK_CONTACT (
    feedback_id VARCHAR PRIMARY KEY,
    email VARCHAR NOT NULL,
    supplied_at TIMESTAMP_LTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS GOVERNANCE.USER_FEEDBACK_ACCOUNT (
    feedback_id VARCHAR PRIMARY KEY,
    account_id VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS GOVERNANCE.USER_FEEDBACK_EVENTS (
    event_id VARCHAR PRIMARY KEY,
    feedback_id VARCHAR NOT NULL,
    event_type VARCHAR NOT NULL,
    rationale VARCHAR,
    actor_user VARCHAR NOT NULL,
    actor_role VARCHAR NOT NULL,
    created_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

-- Event types used now or by later triage (#130): submitted, replayed,
-- transition, contact_revealed, account_revealed, linkage_removed, redacted.
-- Event rows never store message body or contact email.

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_SUBMIT_USER_FEEDBACK(
  SUBMISSION_TOKEN VARCHAR,
  PAYLOAD_FINGERPRINT VARCHAR,
  CATEGORY VARCHAR,
  MESSAGE VARCHAR,
  ROUTE_ID VARCHAR,
  CONTEXT_JSON VARCHAR,
  APP_VERSION VARCHAR,
  SCHEMA_VERSION VARCHAR,
  CONTACT_EMAIL VARCHAR,
  ACCOUNT_ID VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  existing_count NUMBER;
  existing_id VARCHAR;
  existing_received TIMESTAMP_LTZ;
  existing_fp VARCHAR;
  new_feedback_id VARCHAR;
  received_ts TIMESTAMP_LTZ;
  msg_len NUMBER;
  email_trim VARCHAR;
  context_variant VARIANT;
BEGIN
  -- Re-validate; return safe reason codes (never echo MESSAGE or SQLERRM text).
  IF (SUBMISSION_TOKEN IS NULL OR LENGTH(TRIM(SUBMISSION_TOKEN)) = 0
      OR LENGTH(TRIM(SUBMISSION_TOKEN)) > 64) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_submission_token');
  END IF;
  IF (PAYLOAD_FINGERPRINT IS NULL OR NOT REGEXP_LIKE(PAYLOAD_FINGERPRINT, '^[A-Fa-f0-9]{64}$')) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_fingerprint');
  END IF;
  IF (CATEGORY IS NULL OR CATEGORY NOT IN (
      'data_issue', 'usability', 'bug', 'feature_idea', 'general')) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_category');
  END IF;
  IF (ROUTE_ID IS NULL OR ROUTE_ID NOT IN (
      'overview', 'geographic_explorer', 'evidence_library', 'assistant',
      'account', 'privacy', 'ai_ethics')) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_route');
  END IF;
  IF (MESSAGE IS NULL) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_message');
  END IF;
  msg_len := LENGTH(TRIM(MESSAGE));
  IF (msg_len < 10 OR msg_len > 2000) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_message');
  END IF;
  IF (SCHEMA_VERSION IS NULL OR SCHEMA_VERSION <> 'feedback/v1') THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_schema_version');
  END IF;
  IF (APP_VERSION IS NULL
      OR NOT REGEXP_LIKE(APP_VERSION, '^atlas-web/[A-Za-z0-9._-]{1,32}$')) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_app_version');
  END IF;

  IF (CONTACT_EMAIL IS NOT NULL AND LENGTH(TRIM(CONTACT_EMAIL)) > 0) THEN
    email_trim := TRIM(CONTACT_EMAIL);
    IF (LENGTH(email_trim) > 254
        OR POSITION(' ' IN email_trim) > 0
        OR LENGTH(email_trim) - LENGTH(REPLACE(email_trim, '@', '')) <> 1
        OR POSITION('@' IN email_trim) < 2
        OR POSITION('@' IN email_trim) >= LENGTH(email_trim)) THEN
      RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_email');
    END IF;
  ELSE
    email_trim := NULL;
  END IF;

  IF (ACCOUNT_ID IS NOT NULL AND LENGTH(TRIM(ACCOUNT_ID)) > 0) THEN
    IF (LENGTH(TRIM(ACCOUNT_ID)) > 128) THEN
      RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_account_id');
    END IF;
  END IF;

  SELECT COUNT(*), MAX(feedback_id), MAX(received_at), MAX(payload_fingerprint)
    INTO :existing_count, :existing_id, :existing_received, :existing_fp
    FROM GOVERNANCE.USER_FEEDBACK
    WHERE submission_token = :SUBMISSION_TOKEN;

  IF (existing_count > 0) THEN
    IF (existing_fp = PAYLOAD_FINGERPRINT) THEN
      INSERT INTO GOVERNANCE.USER_FEEDBACK_EVENTS (
        event_id, feedback_id, event_type, rationale, actor_user, actor_role, created_at
      ) SELECT UUID_STRING(), :existing_id, 'replayed', NULL,
               CURRENT_USER(), CURRENT_ROLE(), CURRENT_TIMESTAMP();
      RETURN OBJECT_CONSTRUCT(
        'status', 'replayed',
        'feedback_id', :existing_id,
        'received_at', :existing_received
      );
    END IF;
    RETURN OBJECT_CONSTRUCT('status', 'mismatch');
  END IF;

  new_feedback_id := UUID_STRING();
  received_ts := CURRENT_TIMESTAMP();
  IF (CONTEXT_JSON IS NULL OR LENGTH(TRIM(CONTEXT_JSON)) = 0) THEN
    context_variant := NULL;
  ELSE
    context_variant := PARSE_JSON(CONTEXT_JSON);
  END IF;

  INSERT INTO GOVERNANCE.USER_FEEDBACK (
    feedback_id, received_at, stored_at, schema_version, category, message,
    route_id, context, app_version, submission_token, payload_fingerprint,
    triage_state, duplicate_of_feedback_id
  ) SELECT :new_feedback_id, :received_ts, :received_ts, :SCHEMA_VERSION, :CATEGORY,
           TRIM(:MESSAGE), :ROUTE_ID, :context_variant, :APP_VERSION,
           TRIM(:SUBMISSION_TOKEN), :PAYLOAD_FINGERPRINT, 'new', NULL;

  IF (email_trim IS NOT NULL) THEN
    INSERT INTO GOVERNANCE.USER_FEEDBACK_CONTACT (feedback_id, email, supplied_at)
      SELECT :new_feedback_id, :email_trim, :received_ts;
  END IF;

  IF (ACCOUNT_ID IS NOT NULL AND LENGTH(TRIM(ACCOUNT_ID)) > 0) THEN
    INSERT INTO GOVERNANCE.USER_FEEDBACK_ACCOUNT (feedback_id, account_id)
      SELECT :new_feedback_id, TRIM(:ACCOUNT_ID);
  END IF;

  INSERT INTO GOVERNANCE.USER_FEEDBACK_EVENTS (
    event_id, feedback_id, event_type, rationale, actor_user, actor_role, created_at
  ) SELECT UUID_STRING(), :new_feedback_id, 'submitted', NULL,
           CURRENT_USER(), CURRENT_ROLE(), :received_ts;

  RETURN OBJECT_CONSTRUCT(
    'status', 'created',
    'feedback_id', :new_feedback_id,
    'received_at', :received_ts
  );
END;
$$;

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_REDACT_FEEDBACK_FOR_ACCOUNT(
  ACCOUNT_ID VARCHAR,
  REASON VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  removed_count NUMBER;
BEGIN
  IF (ACCOUNT_ID IS NULL OR LENGTH(TRIM(ACCOUNT_ID)) = 0 OR LENGTH(TRIM(ACCOUNT_ID)) > 128) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_account_id');
  END IF;
  IF (REASON IS NULL OR LENGTH(TRIM(REASON)) = 0 OR LENGTH(TRIM(REASON)) > 500) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_reason');
  END IF;

  SELECT COUNT(*) INTO :removed_count
    FROM GOVERNANCE.USER_FEEDBACK_ACCOUNT
    WHERE account_id = TRIM(:ACCOUNT_ID);

  -- Append linkage_removed before deleting links. Does not update USER_FEEDBACK.message.
  -- Does not store message body or email on the event row.
  INSERT INTO GOVERNANCE.USER_FEEDBACK_EVENTS (
    event_id, feedback_id, event_type, rationale, actor_user, actor_role, created_at
  ) SELECT UUID_STRING(), a.feedback_id, 'linkage_removed', TRIM(:REASON),
           CURRENT_USER(), CURRENT_ROLE(), CURRENT_TIMESTAMP()
    FROM GOVERNANCE.USER_FEEDBACK_ACCOUNT a
    WHERE a.account_id = TRIM(:ACCOUNT_ID);

  DELETE FROM GOVERNANCE.USER_FEEDBACK_CONTACT
    WHERE feedback_id IN (
      SELECT feedback_id FROM GOVERNANCE.USER_FEEDBACK_ACCOUNT
      WHERE account_id = TRIM(:ACCOUNT_ID)
    );

  DELETE FROM GOVERNANCE.USER_FEEDBACK_ACCOUNT
    WHERE account_id = TRIM(:ACCOUNT_ID);

  RETURN OBJECT_CONSTRUCT(
    'status', 'linkage_removed',
    'removed_links', :removed_count
  );
END;
$$;

CREATE OR REPLACE VIEW GOVERNANCE.V_USER_FEEDBACK_ANALYST AS
SELECT
  feedback_id,
  category,
  triage_state,
  received_at,
  route_id,
  app_version,
  schema_version,
  context:state::VARCHAR AS state,
  context:county_fips::VARCHAR AS county_fips
FROM GOVERNANCE.USER_FEEDBACK;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_SUBMIT_USER_FEEDBACK(
  VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR
) TO ROLE OH_LYME_{{ ENV }}_READ;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_REDACT_FEEDBACK_FOR_ACCOUNT(
  VARCHAR, VARCHAR
) TO ROLE OH_LYME_{{ ENV }}_READ;

GRANT SELECT ON VIEW GOVERNANCE.V_USER_FEEDBACK_ANALYST
  TO ROLE OH_LYME_{{ ENV }}_READ;
