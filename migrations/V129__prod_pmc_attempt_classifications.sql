-- DATA #517: promote the append-only attempt-classification dependency used by
-- the unchanged one-paper PROD PMC worker. V060/V064 remain DEV-only.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS (
  classification_id VARCHAR PRIMARY KEY,
  extraction_attempt_id VARCHAR NOT NULL,
  pmid VARCHAR NOT NULL,
  classification VARCHAR NOT NULL,
  rationale VARCHAR NOT NULL,
  correlation_id VARCHAR NOT NULL,
  recorded_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  CONSTRAINT ck_pmc_attempt_classification CHECK (
    classification IN (
      'provider_rejected_pre_inference',
      'contract_remediation_reopen'
    )
  ),
  UNIQUE (extraction_attempt_id, classification)
);

-- claim_one and failure accounting read classifications; a provider rejection
-- appends one classification row. The runtime never edits classification history.
GRANT SELECT, INSERT ON TABLE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_CLASSIFICATIONS
  TO ROLE OH_LYME_PROD_RUNTIME;
