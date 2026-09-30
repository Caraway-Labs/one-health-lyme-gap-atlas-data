-- DATA #495: append-only PROD finalization evidence. Historical V061 is DEV-only.
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
  TO ROLE OH_LYME_PROD_KG_LLM_BUDGET_OWNER;

