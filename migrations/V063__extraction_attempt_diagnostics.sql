-- Append-only redacted extraction diagnostics for illegal-edge drops and
-- contribution admission failures. Payload is ontology metadata only (no
-- claim_text, excerpts, or full-text).
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS (
  diagnostic_id VARCHAR PRIMARY KEY,
  extraction_attempt_id VARCHAR NOT NULL,
  pmid VARCHAR NOT NULL,
  diagnostic_type VARCHAR NOT NULL,
  details VARIANT NOT NULL,
  recorded_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
  CONSTRAINT ck_extraction_attempt_diagnostic_type CHECK (
    diagnostic_type IN (
      'dropped_illegal_edge',
      'contribution_validation_failure',
      'partial_accept_summary'
    )
  )
);

GRANT SELECT, INSERT ON TABLE KNOWLEDGE_GRAPH.EXTRACTION_ATTEMPT_DIAGNOSTICS
  TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
