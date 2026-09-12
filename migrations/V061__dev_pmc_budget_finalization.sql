-- DEV-only append-only budget finalization ledger. Table creation stays with
-- the default migration role because OH_LYME_DEV_KG_LLM_BUDGET_OWNER does not
-- have CREATE TABLE on GOVERNANCE. Procedure ownership remains in V062.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS GOVERNANCE.LLM_BUDGET_FINALIZATIONS (
  budget_finalization_id VARCHAR PRIMARY KEY,
  workload VARCHAR NOT NULL,
  request_id VARCHAR NOT NULL,
  status VARCHAR NOT NULL,
  actual_cost_usd NUMBER(12,6),
  recorded_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  CONSTRAINT ck_llm_budget_finalization_status CHECK (status IN ('used', 'failed')),
  UNIQUE (workload, request_id)
);

GRANT SELECT, INSERT ON TABLE GOVERNANCE.LLM_BUDGET_FINALIZATIONS
  TO ROLE OH_LYME_DEV_PIPELINE_RUNTIME;
GRANT SELECT, INSERT ON TABLE GOVERNANCE.LLM_BUDGET_FINALIZATIONS
  TO ROLE OH_LYME_DEV_KG_LLM_BUDGET_OWNER;

-- One-time DEV repair: append failed finalizations for reservations whose
-- matching extraction attempt already failed, or whose request_id never landed
-- in EXTRACTION_ATTEMPTS, so orphaned reserved rows stop consuming the
-- daily/monthly limit. Never updates or deletes usage rows.
INSERT INTO GOVERNANCE.LLM_BUDGET_FINALIZATIONS (
  budget_finalization_id, workload, request_id, status, actual_cost_usd, recorded_at
)
SELECT UUID_STRING(), u.workload, u.request_id, 'failed', NULL, CURRENT_TIMESTAMP()
FROM GOVERNANCE.LLM_BUDGET_USAGE u
WHERE u.workload = 'pmc_extraction'
  AND u.status = 'reserved'
  AND NOT EXISTS (
    SELECT 1 FROM GOVERNANCE.LLM_BUDGET_FINALIZATIONS f
    WHERE f.workload = u.workload AND f.request_id = u.request_id
  )
  AND (
    EXISTS (
      SELECT 1 FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS a
      WHERE a.extraction_attempt_id = u.request_id AND a.status = 'failed'
    )
    OR NOT EXISTS (
      SELECT 1 FROM KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPTS a
      WHERE a.extraction_attempt_id = u.request_id
    )
  );
