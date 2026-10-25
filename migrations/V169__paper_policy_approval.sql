-- DATA #794 / ADR 0023: bounded query-policy approval of discovered PubMed papers.
--
-- Approves only the PMCID-bearing, still-awaiting papers of one COMPLETED discovery
-- run, under policy pubmed-query-policy-v1, and records the same immutable decision
-- and state-event rows a steward decision records so every consumer of
-- PAPERS.final_review_decision_id is unchanged. It never rejects or defers a paper
-- and never consults APPROVAL_STEWARDS.
--
-- SP_RECORD_PAPER_REVIEW_BATCH and its grants are not touched. The pipeline runtime
-- role receives USAGE on this procedure only; it still has no access to the steward
-- procedure or to PAPER_REVIEW_DECISIONS. The procedure executes as its creator, the
-- migration identity that owns the knowledge-graph tables, so no table grant or
-- ownership transfer (which would need account-level MANAGE GRANTS) is required.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE PROCEDURE GOVERNANCE.SP_RECORD_PAPER_POLICY_APPROVAL(
  P_DISCOVERY_RUN_ID VARCHAR, P_POLICY_VERSION VARCHAR, P_CORRELATION_ID VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  unsupported_policy EXCEPTION (-20201, 'Unsupported paper approval policy version');
  unknown_run EXCEPTION (-20202, 'Discovery run was not found');
  incomplete_run EXCEPTION (-20203, 'Discovery run is not COMPLETED');
  invalid_correlation EXCEPTION (-20204, 'A correlation id is required');
  run_count NUMBER;
  run_status VARCHAR;
  query_prefix VARCHAR;
  rationale VARCHAR;
  approved_count NUMBER;
  skipped_no_pmcid NUMBER;
  skipped_not_awaiting_review NUMBER;
  batch_id VARCHAR DEFAULT UUID_STRING();
  policy_actor VARCHAR DEFAULT 'policy:pubmed-query-v1';
BEGIN
  IF (P_POLICY_VERSION IS NULL OR P_POLICY_VERSION <> 'pubmed-query-policy-v1')
    THEN RAISE unsupported_policy; END IF;
  IF (P_CORRELATION_ID IS NULL OR LENGTH(TRIM(P_CORRELATION_ID)) = 0)
    THEN RAISE invalid_correlation; END IF;
  SELECT COUNT(*) INTO :run_count FROM KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS
    WHERE discovery_run_id = :P_DISCOVERY_RUN_ID;
  IF (run_count <> 1) THEN RAISE unknown_run; END IF;
  SELECT status, LEFT(query_sha256, 12) INTO :run_status, :query_prefix
    FROM KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS
    WHERE discovery_run_id = :P_DISCOVERY_RUN_ID;
  IF (run_status <> 'COMPLETED') THEN RAISE incomplete_run; END IF;

  rationale := 'Automated query-policy approval ' || :P_POLICY_VERSION
    || ': paper matched governed discovery run ' || :P_DISCOVERY_RUN_ID
    || ' (query ' || COALESCE(:query_prefix, 'unknown') || ') and has a PMCID';

  SELECT COALESCE(COUNT_IF(p.state = 'awaiting_review' AND p.pmcid IS NOT NULL), 0),
         COALESCE(COUNT_IF(p.state = 'awaiting_review' AND p.pmcid IS NULL), 0),
         COALESCE(COUNT_IF(p.state <> 'awaiting_review'), 0)
    INTO :approved_count, :skipped_no_pmcid, :skipped_not_awaiting_review
    FROM KNOWLEDGE_GRAPH.PAPERS p
    JOIN KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS d
      ON d.discovery_run_id = :P_DISCOVERY_RUN_ID
     AND ARRAY_CONTAINS(TO_VARIANT(p.pmid), d.request_evidence:pmids);

  IF (approved_count > 0) THEN
    INSERT INTO KNOWLEDGE_GRAPH.PAPER_REVIEW_DECISIONS
      SELECT UUID_STRING(), :batch_id, p.pmid, 'approved', :rationale,
             :policy_actor, :P_POLICY_VERSION, :P_CORRELATION_ID, CURRENT_TIMESTAMP()
      FROM KNOWLEDGE_GRAPH.PAPERS p
      JOIN KNOWLEDGE_GRAPH.PUBMED_DISCOVERY_RUNS d
        ON d.discovery_run_id = :P_DISCOVERY_RUN_ID
       AND ARRAY_CONTAINS(TO_VARIANT(p.pmid), d.request_evidence:pmids)
      WHERE p.state = 'awaiting_review' AND p.pmcid IS NOT NULL;
    INSERT INTO KNOWLEDGE_GRAPH.PAPER_STATE_EVENTS
      SELECT UUID_STRING(), p.pmid, p.state, 'approved', 'paper_policy_approval',
             :P_CORRELATION_ID, :policy_actor, CURRENT_TIMESTAMP()
      FROM KNOWLEDGE_GRAPH.PAPERS p
      JOIN KNOWLEDGE_GRAPH.PAPER_REVIEW_DECISIONS d
        ON d.batch_id = :batch_id AND d.pmid = p.pmid;
    UPDATE KNOWLEDGE_GRAPH.PAPERS p SET state = 'approved',
        final_review_decision_id = d.paper_review_decision_id, updated_at = CURRENT_TIMESTAMP()
      FROM KNOWLEDGE_GRAPH.PAPER_REVIEW_DECISIONS d
      WHERE d.batch_id = :batch_id AND d.pmid = p.pmid;
  END IF;
  RETURN OBJECT_CONSTRUCT(
    'batch_id', :batch_id, 'discovery_run_id', :P_DISCOVERY_RUN_ID,
    'policy_version', :P_POLICY_VERSION, 'approved_count', :approved_count,
    'skipped_no_pmcid', :skipped_no_pmcid,
    'skipped_not_awaiting_review', :skipped_not_awaiting_review
  );
END;
$$;

-- The runtime role invokes this bounded procedure and nothing else here. Do not grant
-- it to the API, read, or owner roles.
GRANT USAGE ON PROCEDURE GOVERNANCE.SP_RECORD_PAPER_POLICY_APPROVAL(VARCHAR, VARCHAR, VARCHAR)
  TO ROLE OH_LYME_{{ ENV }}_RUNTIME;
