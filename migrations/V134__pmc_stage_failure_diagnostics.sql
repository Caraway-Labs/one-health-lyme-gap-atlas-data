-- DATA #528: extend the existing append-only diagnostic type contract.
-- This is a reviewed migration; the worker must not write stage_failure until
-- promotion has applied it in the target environment.
USE DATABASE {{ DATABASE }};

EXECUTE IMMEDIATE $$
BEGIN
  BEGIN
    ALTER TABLE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS
      DROP CONSTRAINT ck_extraction_attempt_diagnostic_type;
  EXCEPTION
    WHEN OTHER THEN NULL;
  END;
  ALTER TABLE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS
    ADD CONSTRAINT ck_extraction_attempt_diagnostic_type CHECK (
      diagnostic_type IN (
        'dropped_illegal_edge',
        'contribution_validation_failure',
        'partial_accept_summary',
        'identity_mismatch',
        'attempt_context',
        'stage_failure'
      )
    ) ENABLE NOVALIDATE;
END;
$$;
