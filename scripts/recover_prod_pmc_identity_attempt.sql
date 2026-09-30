-- DATA #495 guarded cleanup for the single failed 2026-09-30 invocation.
-- Execute only after the diagnostic constraint repair and verify the result.
-- The model identity was rejected. Count this as a failed attempt; retain the
-- $0.20 budget reservation and all artifact/attempt history. Do not classify
-- it as a free provider rejection or fabricate unavailable mismatch fields.
-- Preflight operationally: no extraction workflow/deployment is active; retain
-- the six-job topology, and keep writers stopped until COMMIT plus readback.
-- Failed query history 01c76ad6-020b-c6b3-0064-2d07010940e2 records
-- mismatched_fields=query_match_ids; the model output itself was not retained.
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
    )
    AND NOT EXISTS (
      SELECT 1 FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS newer
      WHERE newer.pmid = a.pmid AND newer.attempt_number > a.attempt_number
    );
  IF (match_count <> 1) THEN RAISE changed_state; END IF;
  BEGIN TRANSACTION;
  UPDATE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS
    SET status = 'failed', error_class = 'ContributionIdentityError',
        finished_at = CURRENT_TIMESTAMP()
    WHERE extraction_attempt_id = '917b97aa-cb5c-43dc-9ff1-5d17e461b843'
      AND pmid = '39307534' AND attempt_number = 1
      AND status = 'reserved' AND lease_expires_at < CURRENT_TIMESTAMP()
      AND EXISTS (SELECT 1 FROM KNOWLEDGE_GRAPH.PAPERS p
                  WHERE p.pmid = '39307534' AND p.state = 'extracting')
      AND NOT EXISTS (SELECT 1 FROM KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS r
                      WHERE r.pmid = '39307534')
      AND NOT EXISTS (SELECT 1 FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS newer
                      WHERE newer.pmid = '39307534' AND newer.attempt_number > 1);
  rows_changed := SQLROWCOUNT;
  IF (rows_changed <> 1) THEN RAISE changed_state; END IF;
  UPDATE KNOWLEDGE_GRAPH.PAPERS
    SET state = 'retry_pending', updated_at = CURRENT_TIMESTAMP()
    WHERE pmid = '39307534' AND state = 'extracting'
      AND EXISTS (SELECT 1 FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS a
                  WHERE a.extraction_attempt_id = '917b97aa-cb5c-43dc-9ff1-5d17e461b843'
                    AND a.pmid = '39307534' AND a.attempt_number = 1
                    AND a.status = 'failed' AND a.error_class = 'ContributionIdentityError'
                    AND a.lease_expires_at < CURRENT_TIMESTAMP())
      AND NOT EXISTS (SELECT 1 FROM KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS r
                      WHERE r.pmid = '39307534')
      AND NOT EXISTS (SELECT 1 FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS newer
                      WHERE newer.pmid = '39307534' AND newer.attempt_number > 1);
  rows_changed := SQLROWCOUNT;
  IF (rows_changed <> 1) THEN RAISE changed_state; END IF;
  INSERT INTO KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS
    (paper_state_event_id, pmid, from_state, to_state, reason, correlation_id, actor)
    VALUES (UUID_STRING(), '39307534', 'extracting', 'retry_pending',
      'ContributionIdentityError; query_match_ids mismatch; diagnostic constraint rejected failure record',
      'DATA-495-RUN-36719469767', CURRENT_USER());
  SELECT COUNT(*) INTO :match_count
    FROM KNOWLEDGE_GRAPH.PAPERS p
    JOIN KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS a ON a.pmid = p.pmid
    WHERE p.pmid = '39307534' AND p.state = 'retry_pending'
      AND a.extraction_attempt_id = '917b97aa-cb5c-43dc-9ff1-5d17e461b843'
      AND a.attempt_number = 1 AND a.status = 'failed'
      AND a.error_class = 'ContributionIdentityError'
      AND NOT EXISTS (SELECT 1 FROM KNOWLEDGE_GRAPH.GRAPH_PUBLICATION_RECEIPTS r
                      WHERE r.pmid = p.pmid)
      AND NOT EXISTS (SELECT 1 FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS newer
                      WHERE newer.pmid = p.pmid AND newer.attempt_number > 1);
  IF (match_count <> 1) THEN RAISE changed_state; END IF;
  COMMIT;
  RETURN OBJECT_CONSTRUCT('status', 'recovered', 'pmid', '39307534', 'failed_attempts', 1);
EXCEPTION
  WHEN OTHER THEN
    ROLLBACK;
    RAISE;
END;
$$;
