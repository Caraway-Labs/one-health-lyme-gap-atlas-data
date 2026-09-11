-- DEV-only forward repair: DECISION is ambiguous in this Snowflake SQL
-- procedure. Use prefixed parameter names to preserve the atomic review gate.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_RECORD_PAPER_REVIEW_BATCH(
  P_PMIDS ARRAY, P_DECISION VARCHAR, P_RATIONALE VARCHAR, P_REVIEWER_USERNAME VARCHAR,
  P_APP_VERSION VARCHAR, P_CORRELATION_ID VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  unauthorized EXCEPTION (-20101, 'Reviewer is not an active data steward');
  invalid_decision EXCEPTION (-20102, 'Unsupported paper review decision');
  invalid_rationale EXCEPTION (-20103, 'A 10-10000 character rationale is required');
  invalid_selection EXCEPTION (-20104, 'Selection is not eligible for this decision');
  steward_count NUMBER;
  eligible_count NUMBER;
  batch_id VARCHAR DEFAULT UUID_STRING();
BEGIN
  IF (P_DECISION NOT IN ('approved','rejected','deferred')) THEN RAISE invalid_decision; END IF;
  IF (P_RATIONALE IS NULL OR LENGTH(TRIM(P_RATIONALE)) < 10 OR LENGTH(P_RATIONALE) > 10000)
    THEN RAISE invalid_rationale; END IF;
  SELECT COUNT(*) INTO :steward_count FROM GOVERNANCE.APPROVAL_STEWARDS
    WHERE username = :P_REVIEWER_USERNAME AND is_active = TRUE;
  IF (steward_count <> 1) THEN RAISE unauthorized; END IF;
  SELECT COUNT(*) INTO :eligible_count FROM KNOWLEDGE_GRAPH.PAPERS p,
    LATERAL FLATTEN(INPUT => :P_PMIDS) selected
    WHERE p.pmid = selected.value::VARCHAR
      AND (p.state IN ('awaiting_review','deferred')
        OR (:P_DECISION = 'rejected' AND p.state IN ('retry_pending','retry_exhausted')));
  IF (eligible_count <> ARRAY_SIZE(P_PMIDS) OR eligible_count = 0) THEN RAISE invalid_selection; END IF;

  INSERT INTO KNOWLEDGE_GRAPH.PAPER_REVIEW_DECISIONS
    SELECT UUID_STRING(), :batch_id, selected.value::VARCHAR, :P_DECISION, :P_RATIONALE,
           :P_REVIEWER_USERNAME, :P_APP_VERSION, :P_CORRELATION_ID, CURRENT_TIMESTAMP()
    FROM TABLE(FLATTEN(INPUT => :P_PMIDS)) selected;
  INSERT INTO KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS
    SELECT UUID_STRING(), p.pmid, p.state, :P_DECISION, 'paper_review', :P_CORRELATION_ID,
           :P_REVIEWER_USERNAME, CURRENT_TIMESTAMP()
    FROM KNOWLEDGE_GRAPH.PAPERS p, TABLE(FLATTEN(INPUT => :P_PMIDS)) selected
    WHERE p.pmid = selected.value::VARCHAR;
  UPDATE KNOWLEDGE_GRAPH.PAPERS p SET state = :P_DECISION,
      final_review_decision_id = d.paper_review_decision_id, updated_at = CURRENT_TIMESTAMP()
    FROM KNOWLEDGE_GRAPH.PAPER_REVIEW_DECISIONS d
    WHERE d.batch_id = :batch_id AND d.pmid = p.pmid;
  RETURN OBJECT_CONSTRUCT('batch_id', :batch_id, 'paper_count', :eligible_count);
END;
$$;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_RECORD_PAPER_REVIEW_BATCH(
  ARRAY, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR
) TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
