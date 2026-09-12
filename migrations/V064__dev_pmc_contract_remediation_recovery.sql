-- DEV-only append-only recovery for steward-reviewed contract remediations.
-- Extends EXTRACTION_ATTEMPT_CLASSIFICATIONS beyond provider-rejection and
-- grants auditor read on redacted extraction diagnostics.
USE DATABASE {{ DATABASE }};

ALTER TABLE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS
  DROP CONSTRAINT ck_pmc_attempt_classification;
ALTER TABLE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS
  ADD CONSTRAINT ck_pmc_attempt_classification CHECK (
    classification IN (
      'provider_rejected_pre_inference',
      'contract_remediation_reopen'
    )
  );

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_REOPEN_PMC_CONTRACT_REMEDIATION(
  P_PMID VARCHAR, P_ATTEMPT_IDS ARRAY, P_RATIONALE VARCHAR, P_CORRELATION_ID VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  invalid_input EXCEPTION (-20611, 'A bounded contract-remediation recovery rationale is required');
  invalid_attempt EXCEPTION (-20612, 'Only failed attempts for the named exhausted paper may be classified');
  expected NUMBER;
  matched NUMBER;
BEGIN
  IF (P_PMID IS NULL OR ARRAY_SIZE(P_ATTEMPT_IDS) = 0 OR P_RATIONALE IS NULL
      OR LENGTH(TRIM(P_RATIONALE)) < 10 OR LENGTH(P_RATIONALE) > 10000) THEN RAISE invalid_input; END IF;
  SELECT COUNT(*) INTO :expected FROM TABLE(FLATTEN(INPUT => :P_ATTEMPT_IDS));
  SELECT COUNT(*) INTO :matched FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS a,
    TABLE(FLATTEN(INPUT => :P_ATTEMPT_IDS)) selected
    WHERE a.extraction_attempt_id = selected.value::VARCHAR
      AND a.pmid = :P_PMID AND a.status = 'failed';
  IF (matched <> expected) THEN RAISE invalid_attempt; END IF;
  INSERT INTO KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS
    SELECT UUID_STRING(), a.extraction_attempt_id, a.pmid, 'contract_remediation_reopen',
      :P_RATIONALE, :P_CORRELATION_ID, CURRENT_TIMESTAMP()
    FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS a, TABLE(FLATTEN(INPUT => :P_ATTEMPT_IDS)) selected
    WHERE a.extraction_attempt_id = selected.value::VARCHAR AND a.pmid = :P_PMID
      AND NOT EXISTS (
        SELECT 1 FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS c
        WHERE c.extraction_attempt_id = a.extraction_attempt_id
          AND c.classification = 'contract_remediation_reopen'
      );
  UPDATE KNOWLEDGE_GRAPH.PAPERS SET state = 'retry_pending', updated_at = CURRENT_TIMESTAMP()
    WHERE pmid = :P_PMID AND state = 'retry_exhausted';
  INSERT INTO KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS
    SELECT UUID_STRING(), :P_PMID, 'retry_exhausted', 'retry_pending',
      'contract_remediation_recovery', :P_CORRELATION_ID, CURRENT_USER(), CURRENT_TIMESTAMP();
  RETURN OBJECT_CONSTRUCT(
    'pmid', :P_PMID,
    'classified_attempt_count', :expected,
    'state', 'retry_pending'
  );
END;
$$;

GRANT USAGE ON PROCEDURE GOVERNANCE.SP_REOPEN_PMC_CONTRACT_REMEDIATION(
  VARCHAR, ARRAY, VARCHAR, VARCHAR
) TO ROLE OH_LYME_DEV_KG_PAPER_REVIEW_OWNER;

GRANT SELECT ON TABLE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS
  TO ROLE OH_LYME_DEV_PMC_AUDITOR;
GRANT SELECT ON TABLE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS
  TO ROLE OH_LYME_DEV_PMC_AUDITOR;

ALTER TABLE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS
  DROP CONSTRAINT ck_extraction_attempt_diagnostic_type;
ALTER TABLE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS
  ADD CONSTRAINT ck_extraction_attempt_diagnostic_type CHECK (
    diagnostic_type IN (
      'dropped_illegal_edge',
      'contribution_validation_failure',
      'partial_accept_summary',
      'identity_mismatch'
    )
  );
