-- Epic #63 / Data #130: Owner-only feedback triage, reveal, and redaction.
--
-- Depends on V104 tables and events. Does not alter V104 objects in place
-- beyond adding the triage view and OWNER procedures.
-- Env-neutral: required in both DEV and PROD.
-- No grants to READ or RUNTIME.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE VIEW GOVERNANCE.V_USER_FEEDBACK_TRIAGE AS
SELECT
  feedback_id,
  message,
  category,
  triage_state,
  received_at,
  route_id,
  app_version,
  schema_version,
  duplicate_of_feedback_id,
  context:state::VARCHAR AS state,
  context:county_fips::VARCHAR AS county_fips
FROM GOVERNANCE.USER_FEEDBACK;

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_TRANSITION_USER_FEEDBACK(
  FEEDBACK_ID VARCHAR,
  TO_STATE VARCHAR,
  RATIONALE VARCHAR,
  CANONICAL_FEEDBACK_ID VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  current_state VARCHAR;
  canonical_state VARCHAR;
  canonical_trim VARCHAR;
  rationale_trim VARCHAR;
  to_state_trim VARCHAR;
  feedback_trim VARCHAR;
  found_count NUMBER;
  prior_rationale VARCHAR;
BEGIN
  IF (FEEDBACK_ID IS NULL OR LENGTH(TRIM(FEEDBACK_ID)) = 0) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_feedback_id');
  END IF;
  feedback_trim := TRIM(FEEDBACK_ID);

  IF (TO_STATE IS NULL OR LENGTH(TRIM(TO_STATE)) = 0) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_to_state');
  END IF;
  to_state_trim := TRIM(TO_STATE);
  IF (to_state_trim NOT IN (
      'new', 'reviewed', 'needs_follow_up', 'duplicate', 'resolved', 'dismissed')) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_to_state');
  END IF;

  IF (RATIONALE IS NULL OR LENGTH(TRIM(RATIONALE)) = 0 OR LENGTH(TRIM(RATIONALE)) > 500) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_rationale');
  END IF;
  rationale_trim := TRIM(RATIONALE);

  IF (CANONICAL_FEEDBACK_ID IS NOT NULL AND LENGTH(TRIM(CANONICAL_FEEDBACK_ID)) > 0) THEN
    canonical_trim := TRIM(CANONICAL_FEEDBACK_ID);
  ELSE
    canonical_trim := NULL;
  END IF;

  SELECT COUNT(*), MAX(triage_state) INTO :found_count, :current_state
    FROM GOVERNANCE.USER_FEEDBACK
    WHERE feedback_id = :feedback_trim;
  IF (found_count = 0) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'not_found');
  END IF;

  -- Terminal states cannot leave. Repeating the same terminal state is a
  -- no-op success. A different rationale appends a transition event only.
  IF (current_state IN ('duplicate', 'resolved', 'dismissed')) THEN
    IF (to_state_trim <> current_state) THEN
      RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'terminal_state');
    END IF;
    SELECT MAX_BY(rationale, created_at) INTO :prior_rationale
      FROM GOVERNANCE.USER_FEEDBACK_EVENTS
      WHERE feedback_id = :feedback_trim
        AND event_type = 'transition';
    IF (prior_rationale IS NOT NULL AND prior_rationale = rationale_trim) THEN
      RETURN OBJECT_CONSTRUCT(
        'status', 'unchanged',
        'feedback_id', :feedback_trim,
        'triage_state', :current_state
      );
    END IF;
    BEGIN
      BEGIN TRANSACTION;
      INSERT INTO GOVERNANCE.USER_FEEDBACK_EVENTS (
        event_id, feedback_id, event_type, rationale, actor_user, actor_role, created_at
      ) SELECT UUID_STRING(), :feedback_trim, 'transition', :rationale_trim,
               CURRENT_USER(), CURRENT_ROLE(), CURRENT_TIMESTAMP();
      COMMIT;
    EXCEPTION
      WHEN OTHER THEN
        ROLLBACK;
        RETURN OBJECT_CONSTRUCT('status', 'failed', 'reason', 'persistence_failed');
    END;
    RETURN OBJECT_CONSTRUCT(
      'status', 'unchanged',
      'feedback_id', :feedback_trim,
      'triage_state', :current_state
    );
  END IF;

  -- Allowed non-terminal transitions.
  IF (current_state = 'new') THEN
    IF (to_state_trim NOT IN ('reviewed', 'needs_follow_up', 'duplicate', 'dismissed')) THEN
      RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_transition');
    END IF;
  ELSEIF (current_state IN ('reviewed', 'needs_follow_up')) THEN
    IF (to_state_trim NOT IN (
        'reviewed', 'needs_follow_up', 'duplicate', 'resolved', 'dismissed')) THEN
      RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_transition');
    END IF;
  ELSE
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_transition');
  END IF;

  IF (to_state_trim = 'duplicate') THEN
    IF (canonical_trim IS NULL) THEN
      RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'canonical_required');
    END IF;
    IF (canonical_trim = feedback_trim) THEN
      RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'canonical_self');
    END IF;
    SELECT COUNT(*), MAX(triage_state) INTO :found_count, :canonical_state
      FROM GOVERNANCE.USER_FEEDBACK
      WHERE feedback_id = :canonical_trim;
    IF (found_count = 0) THEN
      RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'canonical_not_found');
    END IF;
    IF (canonical_state = 'duplicate') THEN
      RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'canonical_is_duplicate');
    END IF;
  ELSE
    canonical_trim := NULL;
  END IF;

  BEGIN
    BEGIN TRANSACTION;
    UPDATE GOVERNANCE.USER_FEEDBACK
      SET triage_state = :to_state_trim,
          duplicate_of_feedback_id = :canonical_trim
      WHERE feedback_id = :feedback_trim;
    INSERT INTO GOVERNANCE.USER_FEEDBACK_EVENTS (
      event_id, feedback_id, event_type, rationale, actor_user, actor_role, created_at
    ) SELECT UUID_STRING(), :feedback_trim, 'transition', :rationale_trim,
             CURRENT_USER(), CURRENT_ROLE(), CURRENT_TIMESTAMP();
    COMMIT;
  EXCEPTION
    WHEN OTHER THEN
      ROLLBACK;
      RETURN OBJECT_CONSTRUCT('status', 'failed', 'reason', 'persistence_failed');
  END;

  RETURN OBJECT_CONSTRUCT(
    'status', 'transitioned',
    'feedback_id', :feedback_trim,
    'triage_state', :to_state_trim
  );
END;
$$;

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_REVEAL_FEEDBACK_CONTACT(
  FEEDBACK_ID VARCHAR,
  PURPOSE VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  feedback_trim VARCHAR;
  purpose_trim VARCHAR;
  email_value VARCHAR;
  found_count NUMBER;
BEGIN
  IF (FEEDBACK_ID IS NULL OR LENGTH(TRIM(FEEDBACK_ID)) = 0) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_feedback_id');
  END IF;
  feedback_trim := TRIM(FEEDBACK_ID);

  IF (PURPOSE IS NULL OR LENGTH(TRIM(PURPOSE)) = 0 OR LENGTH(TRIM(PURPOSE)) > 200) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_purpose');
  END IF;
  purpose_trim := TRIM(PURPOSE);

  SELECT COUNT(*), MAX(email) INTO :found_count, :email_value
    FROM GOVERNANCE.USER_FEEDBACK_CONTACT
    WHERE feedback_id = :feedback_trim;
  IF (found_count = 0) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'not_found');
  END IF;

  -- Purpose only in the event rationale. Do not store the email on the event.
  BEGIN
    BEGIN TRANSACTION;
    INSERT INTO GOVERNANCE.USER_FEEDBACK_EVENTS (
      event_id, feedback_id, event_type, rationale, actor_user, actor_role, created_at
    ) SELECT UUID_STRING(), :feedback_trim, 'contact_revealed', :purpose_trim,
             CURRENT_USER(), CURRENT_ROLE(), CURRENT_TIMESTAMP();
    COMMIT;
  EXCEPTION
    WHEN OTHER THEN
      ROLLBACK;
      RETURN OBJECT_CONSTRUCT('status', 'failed', 'reason', 'persistence_failed');
  END;

  RETURN OBJECT_CONSTRUCT('email', :email_value);
END;
$$;

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_REVEAL_FEEDBACK_ACCOUNT(
  FEEDBACK_ID VARCHAR,
  PURPOSE VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  feedback_trim VARCHAR;
  purpose_trim VARCHAR;
  account_value VARCHAR;
  found_count NUMBER;
BEGIN
  IF (FEEDBACK_ID IS NULL OR LENGTH(TRIM(FEEDBACK_ID)) = 0) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_feedback_id');
  END IF;
  feedback_trim := TRIM(FEEDBACK_ID);

  IF (PURPOSE IS NULL OR LENGTH(TRIM(PURPOSE)) = 0 OR LENGTH(TRIM(PURPOSE)) > 200) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_purpose');
  END IF;
  purpose_trim := TRIM(PURPOSE);

  SELECT COUNT(*), MAX(account_id) INTO :found_count, :account_value
    FROM GOVERNANCE.USER_FEEDBACK_ACCOUNT
    WHERE feedback_id = :feedback_trim;
  IF (found_count = 0) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'not_found');
  END IF;

  BEGIN
    BEGIN TRANSACTION;
    INSERT INTO GOVERNANCE.USER_FEEDBACK_EVENTS (
      event_id, feedback_id, event_type, rationale, actor_user, actor_role, created_at
    ) SELECT UUID_STRING(), :feedback_trim, 'account_revealed', :purpose_trim,
             CURRENT_USER(), CURRENT_ROLE(), CURRENT_TIMESTAMP();
    COMMIT;
  EXCEPTION
    WHEN OTHER THEN
      ROLLBACK;
      RETURN OBJECT_CONSTRUCT('status', 'failed', 'reason', 'persistence_failed');
  END;

  RETURN OBJECT_CONSTRUCT('account_id', :account_value);
END;
$$;

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_REDACT_USER_FEEDBACK(
  FEEDBACK_ID VARCHAR,
  REASON VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  feedback_trim VARCHAR;
  reason_trim VARCHAR;
  found_count NUMBER;
BEGIN
  IF (FEEDBACK_ID IS NULL OR LENGTH(TRIM(FEEDBACK_ID)) = 0) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_feedback_id');
  END IF;
  feedback_trim := TRIM(FEEDBACK_ID);

  IF (REASON IS NULL OR LENGTH(TRIM(REASON)) = 0 OR LENGTH(TRIM(REASON)) > 500) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'invalid_reason');
  END IF;
  reason_trim := TRIM(REASON);

  SELECT COUNT(*) INTO :found_count
    FROM GOVERNANCE.USER_FEEDBACK
    WHERE feedback_id = :feedback_trim;
  IF (found_count = 0) THEN
    RETURN OBJECT_CONSTRUCT('status', 'rejected', 'reason', 'not_found');
  END IF;

  -- Replaces this row's message only. Does not rewrite prior event rows.
  BEGIN
    BEGIN TRANSACTION;
    UPDATE GOVERNANCE.USER_FEEDBACK
      SET message = '[redacted]'
      WHERE feedback_id = :feedback_trim;
    DELETE FROM GOVERNANCE.USER_FEEDBACK_CONTACT
      WHERE feedback_id = :feedback_trim;
    DELETE FROM GOVERNANCE.USER_FEEDBACK_ACCOUNT
      WHERE feedback_id = :feedback_trim;
    INSERT INTO GOVERNANCE.USER_FEEDBACK_EVENTS (
      event_id, feedback_id, event_type, rationale, actor_user, actor_role, created_at
    ) SELECT UUID_STRING(), :feedback_trim, 'redacted', :reason_trim,
             CURRENT_USER(), CURRENT_ROLE(), CURRENT_TIMESTAMP();
    COMMIT;
  EXCEPTION
    WHEN OTHER THEN
      ROLLBACK;
      RETURN OBJECT_CONSTRUCT('status', 'failed', 'reason', 'persistence_failed');
  END;

  RETURN OBJECT_CONSTRUCT(
    'status', 'redacted',
    'feedback_id', :feedback_trim
  );
END;
$$;

GRANT SELECT ON VIEW GOVERNANCE.V_USER_FEEDBACK_TRIAGE
  TO ROLE OH_LYME_{{ ENV }}_OWNER;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_TRANSITION_USER_FEEDBACK(
  VARCHAR, VARCHAR, VARCHAR, VARCHAR
) TO ROLE OH_LYME_{{ ENV }}_OWNER;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_REVEAL_FEEDBACK_CONTACT(
  VARCHAR, VARCHAR
) TO ROLE OH_LYME_{{ ENV }}_OWNER;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_REVEAL_FEEDBACK_ACCOUNT(
  VARCHAR, VARCHAR
) TO ROLE OH_LYME_{{ ENV }}_OWNER;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_REDACT_USER_FEEDBACK(
  VARCHAR, VARCHAR
) TO ROLE OH_LYME_{{ ENV }}_OWNER;
