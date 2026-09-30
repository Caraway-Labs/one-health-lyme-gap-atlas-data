-- DATA #495. Run with the existing table owner while extraction is stopped.
-- DDL commits independently: each statement is guarded and safe to resume.
-- Keep a verified four-value CHECK in place before dropping the V063 CHECK.
USE DATABASE ONE_HEALTH_LYME_GAP_ATLAS_PROD;

EXECUTE IMMEDIATE $$
DECLARE
  wrong_role EXCEPTION (-20931, 'Existing diagnostics table owner is required');
  unexpected_constraint EXCEPTION (-20932, 'Unexpected diagnostic CHECK state; stop for review');
  old_clause VARCHAR DEFAULT 'diagnostic_typein(''dropped_illegal_edge'',''contribution_validation_failure'',''partial_accept_summary'')';
  new_clause VARCHAR DEFAULT 'diagnostic_typein(''dropped_illegal_edge'',''contribution_validation_failure'',''partial_accept_summary'',''identity_mismatch'')';
  old_count NUMBER;
  new_count NUMBER;
  temp_count NUMBER;
  other_count NUMBER;
  nullability VARCHAR;
BEGIN
  IF (CURRENT_ROLE() <> 'ACCOUNTADMIN') THEN RAISE wrong_role; END IF;
  SELECT is_nullable INTO :nullability
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE table_schema = 'KNOWLEDGE_GRAPH'
      AND table_name = 'EXTRACTION_ATTEMPT_DIAGNOSTICS'
      AND column_name = 'DIAGNOSTIC_TYPE';
  IF (nullability <> 'NO') THEN RAISE unexpected_constraint; END IF;

  SELECT COALESCE(COUNT_IF(constraint_name = 'CK_EXTRACTION_ATTEMPT_DIAGNOSTIC_TYPE'
                  AND REGEXP_REPLACE(LOWER(check_clause), '[[:space:]]+', '') = :old_clause),
         0),
         COALESCE(COUNT_IF(constraint_name = 'CK_EXTRACTION_ATTEMPT_DIAGNOSTIC_TYPE'
                  AND REGEXP_REPLACE(LOWER(check_clause), '[[:space:]]+', '') = :new_clause), 0),
         COALESCE(COUNT_IF(constraint_name = 'CK_EXTRACTION_ATTEMPT_DIAGNOSTIC_TYPE_DATA495'
                  AND REGEXP_REPLACE(LOWER(check_clause), '[[:space:]]+', '') = :new_clause), 0),
         COALESCE(COUNT_IF(NOT ((constraint_name = 'CK_EXTRACTION_ATTEMPT_DIAGNOSTIC_TYPE'
                        AND REGEXP_REPLACE(LOWER(check_clause), '[[:space:]]+', '') IN (:old_clause, :new_clause))
                    OR (constraint_name = 'CK_EXTRACTION_ATTEMPT_DIAGNOSTIC_TYPE_DATA495'
                        AND REGEXP_REPLACE(LOWER(check_clause), '[[:space:]]+', '') = :new_clause))), 0)
    INTO :old_count, :new_count, :temp_count, :other_count
    FROM INFORMATION_SCHEMA.CHECK_CONSTRAINTS
    WHERE constraint_schema = 'KNOWLEDGE_GRAPH'
      AND constraint_table = 'EXTRACTION_ATTEMPT_DIAGNOSTICS'
      AND constraint_name IN ('CK_EXTRACTION_ATTEMPT_DIAGNOSTIC_TYPE',
                              'CK_EXTRACTION_ATTEMPT_DIAGNOSTIC_TYPE_DATA495');
  IF (other_count <> 0 OR old_count + new_count > 1) THEN RAISE unexpected_constraint; END IF;

  -- Already complete, including cleanup of an interrupted temporary CHECK.
  IF (new_count = 1 AND temp_count = 0) THEN
    RETURN OBJECT_CONSTRUCT('status', 'already_repaired');
  END IF;
  IF (new_count = 1 AND temp_count = 1) THEN
    ALTER TABLE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS
      DROP CONSTRAINT ck_extraction_attempt_diagnostic_type_data495;
    SELECT COUNT(*) INTO :temp_count FROM INFORMATION_SCHEMA.CHECK_CONSTRAINTS
      WHERE constraint_schema = 'KNOWLEDGE_GRAPH'
        AND constraint_table = 'EXTRACTION_ATTEMPT_DIAGNOSTICS'
        AND constraint_name = 'CK_EXTRACTION_ATTEMPT_DIAGNOSTIC_TYPE_DATA495';
    IF (temp_count <> 0) THEN RAISE unexpected_constraint; END IF;
    RETURN OBJECT_CONSTRUCT('status', 'repaired');
  END IF;
  IF (old_count <> 1 AND temp_count <> 1) THEN RAISE unexpected_constraint; END IF;

  IF (temp_count = 0) THEN
    ALTER TABLE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS
      ADD CONSTRAINT ck_extraction_attempt_diagnostic_type_data495 CHECK (
        diagnostic_type IN ('dropped_illegal_edge', 'contribution_validation_failure',
                            'partial_accept_summary', 'identity_mismatch')
      ) ENABLE NOVALIDATE;
  END IF;
  SELECT COUNT(*) INTO :temp_count FROM INFORMATION_SCHEMA.CHECK_CONSTRAINTS
    WHERE constraint_schema = 'KNOWLEDGE_GRAPH'
      AND constraint_table = 'EXTRACTION_ATTEMPT_DIAGNOSTICS'
      AND constraint_name = 'CK_EXTRACTION_ATTEMPT_DIAGNOSTIC_TYPE_DATA495'
      AND REGEXP_REPLACE(LOWER(check_clause), '[[:space:]]+', '') = :new_clause;
  IF (temp_count <> 1) THEN RAISE unexpected_constraint; END IF;

  IF (old_count = 1) THEN
    ALTER TABLE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS
      DROP CONSTRAINT ck_extraction_attempt_diagnostic_type;
  END IF;
  -- The temporary CHECK remains active if the next DDL fails.
  SELECT COUNT(*) INTO :old_count FROM INFORMATION_SCHEMA.CHECK_CONSTRAINTS
    WHERE constraint_schema = 'KNOWLEDGE_GRAPH'
      AND constraint_table = 'EXTRACTION_ATTEMPT_DIAGNOSTICS'
      AND constraint_name = 'CK_EXTRACTION_ATTEMPT_DIAGNOSTIC_TYPE';
  IF (old_count <> 0) THEN RAISE unexpected_constraint; END IF;
  ALTER TABLE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS
    ADD CONSTRAINT ck_extraction_attempt_diagnostic_type CHECK (
      diagnostic_type IN ('dropped_illegal_edge', 'contribution_validation_failure',
                          'partial_accept_summary', 'identity_mismatch')
    ) ENABLE NOVALIDATE;
  SELECT COUNT(*) INTO :old_count FROM INFORMATION_SCHEMA.CHECK_CONSTRAINTS
    WHERE constraint_schema = 'KNOWLEDGE_GRAPH'
      AND constraint_table = 'EXTRACTION_ATTEMPT_DIAGNOSTICS'
      AND constraint_name = 'CK_EXTRACTION_ATTEMPT_DIAGNOSTIC_TYPE'
      AND REGEXP_REPLACE(LOWER(check_clause), '[[:space:]]+', '') = :new_clause;
  IF (old_count <> 1) THEN RAISE unexpected_constraint; END IF;
  ALTER TABLE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS
    DROP CONSTRAINT ck_extraction_attempt_diagnostic_type_data495;
  SELECT COUNT(*) INTO :temp_count FROM INFORMATION_SCHEMA.CHECK_CONSTRAINTS
    WHERE constraint_schema = 'KNOWLEDGE_GRAPH'
      AND constraint_table = 'EXTRACTION_ATTEMPT_DIAGNOSTICS'
      AND constraint_name = 'CK_EXTRACTION_ATTEMPT_DIAGNOSTIC_TYPE_DATA495';
  IF (temp_count <> 0) THEN RAISE unexpected_constraint; END IF;
  RETURN OBJECT_CONSTRUCT('status', 'repaired');
END;
$$;
