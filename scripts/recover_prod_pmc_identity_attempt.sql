-- DATA #495 guarded cleanup for the single failed 2026-09-30 invocation.
-- Execute only after the diagnostic constraint repair and verify the result.
-- The model identity was rejected. Count this as a failed attempt; retain the
-- $0.20 budget reservation and all artifact/attempt history. Do not classify
-- it as a free provider rejection or fabricate unavailable mismatch fields.
USE DATABASE ONE_HEALTH_LYME_GAP_ATLAS_PROD;

EXECUTE IMMEDIATE $$
DECLARE
  wrong_role EXCEPTION (-20941, 'Existing table owner is required');
  changed_state EXCEPTION (-20942, 'Stranded attempt preconditions changed');
  match_count NUMBER;
  rows_changed NUMBER;
BEGIN
  IF (CURRENT_ROLE() <> 'ACCOUNTADMIN') THEN RAISE wrong_role; END IF;
  SELECT COUNT(*) INTO :match_count
  FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS a
  JOIN KNOWLEDGE_GRAPH.PAPERS p ON p.pmid = a.pmid
  WHERE a.extraction_attempt_id = '917b97aa-cb5c-43dc-9ff1-5d17e461b843'
    AND a.pmid = '39307534' AND a.attempt_number = 1
    AND a.status = 'reserved' AND a.lease_expires_at < CURRENT_TIMESTAMP()
    AND p.state = 'extracting'
    AND NOT EXISTS (
      SELECT 1 FROM KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS r
      WHERE r.pmid = a.pmid
    );
  IF (match_count <> 1) THEN RAISE changed_state; END IF;
  BEGIN TRANSACTION;
  UPDATE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS
    SET status = 'failed', error_class = 'ContributionIdentityError',
        finished_at = CURRENT_TIMESTAMP()
    WHERE extraction_attempt_id = '917b97aa-cb5c-43dc-9ff1-5d17e461b843'
      AND pmid = '39307534' AND attempt_number = 1 AND status = 'reserved';
  rows_changed := SQLROWCOUNT;
  IF (rows_changed <> 1) THEN RAISE changed_state; END IF;
  UPDATE KNOWLEDGE_GRAPH.PAPERS
    SET state = 'retry_pending', updated_at = CURRENT_TIMESTAMP()
    WHERE pmid = '39307534' AND state = 'extracting';
  rows_changed := SQLROWCOUNT;
  IF (rows_changed <> 1) THEN RAISE changed_state; END IF;
  INSERT INTO KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS
    (paper_state_event_id, pmid, from_state, to_state, reason, correlation_id, actor)
    VALUES (UUID_STRING(), '39307534', 'extracting', 'retry_pending',
      'ContributionIdentityError; diagnostic constraint rejected the original failure record',
      'DATA-495-RUN-36719469767', CURRENT_USER());
  COMMIT;
  RETURN OBJECT_CONSTRUCT('status', 'recovered', 'pmid', '39307534', 'failed_attempts', 1);
EXCEPTION
  WHEN OTHER THEN
    ROLLBACK;
    RAISE;
END;
$$;
