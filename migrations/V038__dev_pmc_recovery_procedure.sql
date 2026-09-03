USE DATABASE {{ DATABASE }};

-- DEV-only recovery for a paper that has failed the external PMC OA admission
-- check. The normal review procedure remains immutable and handles only its
-- original awaiting/deferred states. This procedure can only reject a failed
-- candidate and preserves a distinct, append-only recovery decision/event.
GRANT SELECT ON VIEW GOVERNANCE.V_KG_PAPER_REVIEW_QUEUE
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_REJECT_PMC_RECOVERY_BATCH(
  PMIDS ARRAY, RATIONALE VARCHAR, REVIEWER_USERNAME VARCHAR,
  APP_VERSION VARCHAR, CORRELATION_ID VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  unauthorized EXCEPTION (-20111, 'Reviewer is not an active data steward');
  invalid_rationale EXCEPTION (-20112, 'A 10-10000 character rationale is required');
  invalid_selection EXCEPTION (-20113, 'Selection is not a failed PMC recovery candidate');
  steward_count NUMBER;
  eligible_count NUMBER;
  batch_id VARCHAR DEFAULT UUID_STRING();
BEGIN
  IF (RATIONALE IS NULL OR LENGTH(TRIM(RATIONALE)) < 10 OR LENGTH(RATIONALE) > 10000)
    THEN RAISE invalid_rationale; END IF;
  SELECT COUNT(*) INTO :steward_count FROM GOVERNANCE.APPROVAL_STEWARDS
    WHERE username = :REVIEWER_USERNAME AND is_active = TRUE;
  IF (steward_count <> 1) THEN RAISE unauthorized; END IF;
  SELECT COUNT(*) INTO :eligible_count FROM KNOWLEDGE_GRAPH.PAPERS p,
    LATERAL FLATTEN(INPUT => :PMIDS) selected
    WHERE p.pmid = selected.value::VARCHAR
      AND p.state IN ('retry_pending','retry_exhausted');
  IF (eligible_count <> ARRAY_SIZE(PMIDS) OR eligible_count = 0) THEN RAISE invalid_selection; END IF;

  INSERT INTO KNOWLEDGE_GRAPH.PAPER_REVIEW_DECISIONS
    SELECT UUID_STRING(), :batch_id, selected.value::VARCHAR, 'rejected', :RATIONALE,
           :REVIEWER_USERNAME, :APP_VERSION, :CORRELATION_ID, CURRENT_TIMESTAMP()
    FROM TABLE(FLATTEN(INPUT => :PMIDS)) selected;
  INSERT INTO KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS
    SELECT UUID_STRING(), p.pmid, p.state, 'rejected', 'pmc_oa_recovery_rejection',
           :CORRELATION_ID, :REVIEWER_USERNAME, CURRENT_TIMESTAMP()
    FROM KNOWLEDGE_GRAPH.PAPERS p, TABLE(FLATTEN(INPUT => :PMIDS)) selected
    WHERE p.pmid = selected.value::VARCHAR;
  UPDATE KNOWLEDGE_GRAPH.PAPERS p SET state = 'rejected',
      final_review_decision_id = d.paper_review_decision_id, updated_at = CURRENT_TIMESTAMP()
    FROM KNOWLEDGE_GRAPH.PAPER_REVIEW_DECISIONS d
    WHERE d.batch_id = :batch_id AND d.pmid = p.pmid;
  RETURN OBJECT_CONSTRUCT('batch_id', :batch_id, 'paper_count', :eligible_count);
END;
$$;

GRANT OWNERSHIP ON PROCEDURE GOVERNANCE.SP_REJECT_PMC_RECOVERY_BATCH(
  ARRAY, VARCHAR, VARCHAR, VARCHAR, VARCHAR
) TO ROLE OH_LYME_{{ ENV }}_KG_PAPER_REVIEW_OWNER COPY CURRENT GRANTS;
GRANT USAGE ON PROCEDURE GOVERNANCE.SP_REJECT_PMC_RECOVERY_BATCH(
  ARRAY, VARCHAR, VARCHAR, VARCHAR, VARCHAR
) TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
