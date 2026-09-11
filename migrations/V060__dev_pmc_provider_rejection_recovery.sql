-- DEV-only, append-only recovery for requests rejected before model inference.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS (
  classification_id VARCHAR PRIMARY KEY,
  extraction_attempt_id VARCHAR NOT NULL,
  pmid VARCHAR NOT NULL,
  classification VARCHAR NOT NULL,
  rationale VARCHAR NOT NULL,
  correlation_id VARCHAR NOT NULL,
  recorded_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  CONSTRAINT ck_pmc_attempt_classification CHECK (classification = 'provider_rejected_pre_inference'),
  UNIQUE (extraction_attempt_id, classification)
);

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_REOPEN_PMC_PROVIDER_REJECTION(
  P_PMID VARCHAR, P_ATTEMPT_IDS ARRAY, P_RATIONALE VARCHAR, P_CORRELATION_ID VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE invalid_input EXCEPTION (-20601, 'A bounded provider-rejection recovery rationale is required');
DECLARE invalid_attempt EXCEPTION (-20602, 'Only failed attempts for the named exhausted paper may be classified');
DECLARE expected NUMBER;
DECLARE matched NUMBER;
BEGIN
  IF (P_PMID IS NULL OR ARRAY_SIZE(P_ATTEMPT_IDS) = 0 OR P_RATIONALE IS NULL
      OR LENGTH(TRIM(P_RATIONALE)) < 10 OR LENGTH(P_RATIONALE) > 10000) THEN RAISE invalid_input; END IF;
  SELECT COUNT(*) INTO :expected FROM TABLE(FLATTEN(INPUT => :P_ATTEMPT_IDS));
  SELECT COUNT(*) INTO :matched FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS a,
    TABLE(FLATTEN(INPUT => :P_ATTEMPT_IDS)) selected
    WHERE a.extraction_attempt_id = selected.value::VARCHAR AND a.pmid = :P_PMID AND a.status = 'failed';
  IF (matched <> expected) THEN RAISE invalid_attempt; END IF;
  INSERT INTO KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS
    SELECT UUID_STRING(), a.extraction_attempt_id, a.pmid, 'provider_rejected_pre_inference',
      :P_RATIONALE, :P_CORRELATION_ID, CURRENT_TIMESTAMP()
    FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS a, TABLE(FLATTEN(INPUT => :P_ATTEMPT_IDS)) selected
    WHERE a.extraction_attempt_id = selected.value::VARCHAR AND a.pmid = :P_PMID
      AND NOT EXISTS (SELECT 1 FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS c
                      WHERE c.extraction_attempt_id = a.extraction_attempt_id
                        AND c.classification = 'provider_rejected_pre_inference');
  UPDATE KNOWLEDGE_GRAPH.PAPERS SET state = 'retry_pending', updated_at = CURRENT_TIMESTAMP()
    WHERE pmid = :P_PMID AND state = 'retry_exhausted';
  INSERT INTO KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS
    SELECT UUID_STRING(), :P_PMID, 'retry_exhausted', 'retry_pending',
      'provider_rejection_recovery', :P_CORRELATION_ID, CURRENT_USER(), CURRENT_TIMESTAMP();
  RETURN OBJECT_CONSTRUCT('pmid', :P_PMID, 'classified_attempt_count', :expected, 'state', 'retry_pending');
END;
$$;

GRANT SELECT, INSERT ON TABLE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS
  TO ROLE OH_LYME_DEV_PIPELINE_RUNTIME;
GRANT USAGE ON PROCEDURE GOVERNANCE.SP_REOPEN_PMC_PROVIDER_REJECTION(VARCHAR, ARRAY, VARCHAR, VARCHAR)
  TO ROLE OH_LYME_DEV_KG_PAPER_REVIEW_OWNER;
