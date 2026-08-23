USE DATABASE {{ DATABASE }};

-- V016's pipeline-status view reports the latest governed ingestion run.
-- Keep the owner-rights console read-only and grant only this dependency.
GRANT SELECT ON TABLE GOVERNANCE.INGESTION_RUNS
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
