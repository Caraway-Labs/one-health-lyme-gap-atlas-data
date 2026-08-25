USE DATABASE {{ DATABASE }};

-- A continuation run is a new append-only attempt.  The prior rate-limited
-- run remains intact; these fields link the successor and retain only public
-- catalog-page state needed to retry the exact failed page.
ALTER TABLE GOVERNANCE.INGESTION_RUNS
  ADD COLUMN IF NOT EXISTS resumed_from_ingestion_run_id VARCHAR;
ALTER TABLE GOVERNANCE.INGESTION_RUNS
  ADD COLUMN IF NOT EXISTS resume_state VARIANT;

-- The runtime reads only its own governed run/request ledger and immutable
-- metadata artifacts to reconstruct a legacy Data.gov cursor checkpoint.
GRANT SELECT ON TABLE GOVERNANCE.INGESTION_REQUESTS
  TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT SELECT ON TABLE GOVERNANCE.RAW_ARTIFACTS
  TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
