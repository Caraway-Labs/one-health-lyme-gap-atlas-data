USE DATABASE {{ DATABASE }};

-- Registration is metadata-only, but a large completed discovery chain can exceed
-- an App Platform post-deploy window. This ledger makes each artifact batch
-- independently committed and safely retryable without replaying discovery.
CREATE TABLE IF NOT EXISTS GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS (
  artifact_id VARCHAR PRIMARY KEY,
  config_sha256 VARCHAR(64) NOT NULL,
  status VARCHAR NOT NULL,
  registration_run_id VARCHAR,
  attempt_count NUMBER NOT NULL DEFAULT 0,
  started_at TIMESTAMP_LTZ,
  lease_expires_at TIMESTAMP_LTZ,
  completed_at TIMESTAMP_LTZ,
  redacted_error VARCHAR
);

GRANT SELECT, INSERT, UPDATE ON TABLE GOVERNANCE.CATALOG_DISCOVERY_REGISTRATIONS
  TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
