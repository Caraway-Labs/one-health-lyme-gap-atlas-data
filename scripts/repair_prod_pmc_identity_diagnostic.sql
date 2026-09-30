-- DATA #495 incident repair. Run once with the existing ACCOUNTADMIN table
-- owner after reviewing the live V063 constraint and stopping extraction.
-- V064 is DEV-only; this changes the PROD check to that same four-value set.
-- No role, grant, paper decision, or budget history is changed here.
USE DATABASE ONE_HEALTH_LYME_GAP_ATLAS_PROD;

EXECUTE IMMEDIATE $$
DECLARE
  wrong_role EXCEPTION (-20931, 'Existing diagnostics table owner is required');
  unexpected_constraint EXCEPTION (-20932, 'PROD diagnostic constraint differs from V063');
  table_ddl VARCHAR;
BEGIN
  IF (CURRENT_ROLE() <> 'ACCOUNTADMIN') THEN RAISE wrong_role; END IF;
  SELECT GET_DDL('TABLE', 'ONE_HEALTH_LYME_GAP_ATLAS_PROD.KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS')
    INTO :table_ddl;
  IF (CONTAINS(UPPER(table_ddl), 'IDENTITY_MISMATCH')) THEN
    RETURN OBJECT_CONSTRUCT('status', 'already_repaired');
  END IF;
  IF (NOT CONTAINS(UPPER(table_ddl), 'CK_EXTRACTION_ATTEMPT_DIAGNOSTIC_TYPE')
      OR NOT CONTAINS(table_ddl, 'dropped_illegal_edge')
      OR NOT CONTAINS(table_ddl, 'contribution_validation_failure')
      OR NOT CONTAINS(table_ddl, 'partial_accept_summary')) THEN
    RAISE unexpected_constraint;
  END IF;
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
    ) ENABLE NOVALIDATE;
  RETURN OBJECT_CONSTRUCT('status', 'repaired');
END;
$$;
