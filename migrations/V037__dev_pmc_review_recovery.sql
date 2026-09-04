USE DATABASE {{ DATABASE }};

-- DEV-only recovery: retain the Streamlit caller boundary without transferring
-- ownership of an existing governed view from the least-privilege deploy role.
-- A paper that fails the external PMC OA admission check can be rejected by a
-- steward; it cannot be approved again from a retry state.
GRANT SELECT ON TABLE KNOWLEDGE_GRAPH.PAPER_QUERY_MATCHES
  TO ROLE OH_LYME_{{ ENV }}_KG_PAPER_REVIEW_OWNER;

CREATE OR REPLACE VIEW GOVERNANCE.V_KG_PAPER_REVIEW_QUEUE AS
SELECT p.pmid, p.pmcid, p.title, p.journal, p.publication_date,
       p.publication_types, p.language, p.abstract, p.access_status, p.state,
       p.discovered_at, p.configuration_version,
       'https://pubmed.ncbi.nlm.nih.gov/' || p.pmid || '/' AS pubmed_url,
       ARRAY_AGG(DISTINCT m.family) WITHIN GROUP (ORDER BY m.family) AS query_families
FROM KNOWLEDGE_GRAPH.PAPERS p
JOIN KNOWLEDGE_GRAPH.PAPER_QUERY_MATCHES m ON m.pmid = p.pmid
WHERE p.state IN ('awaiting_review', 'deferred', 'retry_pending', 'retry_exhausted')
GROUP BY ALL;

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_RECORD_PAPER_REVIEW_BATCH(
  PMIDS ARRAY, DECISION VARCHAR, RATIONALE VARCHAR, REVIEWER_USERNAME VARCHAR,
  APP_VERSION VARCHAR, CORRELATION_ID VARCHAR
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
  IF (DECISION NOT IN ('approved','rejected','deferred')) THEN RAISE invalid_decision; END IF;
  IF (RATIONALE IS NULL OR LENGTH(TRIM(RATIONALE)) < 10 OR LENGTH(RATIONALE) > 10000)
    THEN RAISE invalid_rationale; END IF;
  SELECT COUNT(*) INTO :steward_count FROM GOVERNANCE.APPROVAL_STEWARDS
    WHERE username = :REVIEWER_USERNAME AND is_active = TRUE;
  IF (steward_count <> 1) THEN RAISE unauthorized; END IF;
  SELECT COUNT(*) INTO :eligible_count FROM KNOWLEDGE_GRAPH.PAPERS p,
    LATERAL FLATTEN(INPUT => :PMIDS) selected
    WHERE p.pmid = selected.value::VARCHAR
      AND (
        p.state IN ('awaiting_review','deferred')
        OR (DECISION = 'rejected' AND p.state IN ('retry_pending','retry_exhausted'))
      );
  IF (eligible_count <> ARRAY_SIZE(PMIDS) OR eligible_count = 0) THEN RAISE invalid_selection; END IF;

  INSERT INTO KNOWLEDGE_GRAPH.PAPER_REVIEW_DECISIONS
    SELECT UUID_STRING(), :batch_id, selected.value::VARCHAR, :DECISION, :RATIONALE,
           :REVIEWER_USERNAME, :APP_VERSION, :CORRELATION_ID, CURRENT_TIMESTAMP()
    FROM TABLE(FLATTEN(INPUT => :PMIDS)) selected;
  INSERT INTO KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS
    SELECT UUID_STRING(), p.pmid, p.state, :DECISION, 'paper_review', :CORRELATION_ID,
           :REVIEWER_USERNAME, CURRENT_TIMESTAMP()
    FROM KNOWLEDGE_GRAPH.PAPERS p, TABLE(FLATTEN(INPUT => :PMIDS)) selected
    WHERE p.pmid = selected.value::VARCHAR;
  UPDATE KNOWLEDGE_GRAPH.PAPERS p SET state = :DECISION,
      final_review_decision_id = d.paper_review_decision_id, updated_at = CURRENT_TIMESTAMP()
    FROM KNOWLEDGE_GRAPH.PAPER_REVIEW_DECISIONS d
    WHERE d.batch_id = :batch_id AND d.pmid = p.pmid;
  RETURN OBJECT_CONSTRUCT('batch_id', :batch_id, 'paper_count', :eligible_count);
END;
$$;

-- The least-privilege migration role owns the freshly replaced procedure, but
-- cannot use COPY CURRENT GRANTS (which requires account-level MANAGE GRANTS).
-- Revoke and then explicitly restore the only caller grant required here.
GRANT OWNERSHIP ON PROCEDURE GOVERNANCE.SP_RECORD_PAPER_REVIEW_BATCH(
  ARRAY, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR
) TO ROLE OH_LYME_{{ ENV }}_KG_PAPER_REVIEW_OWNER REVOKE CURRENT GRANTS;
GRANT USAGE ON PROCEDURE GOVERNANCE.SP_RECORD_PAPER_REVIEW_BATCH(
  ARRAY, VARCHAR, VARCHAR, VARCHAR, VARCHAR, VARCHAR
) TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
