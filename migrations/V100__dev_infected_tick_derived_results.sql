-- Story #169: narrow DEV-only derived-result store, separate from the county
-- semantic release and from RAW/STAGING/CONFORMED source observations.
-- Rows are immutable. The runtime may SELECT/INSERT only; application writes
-- use a deterministic result ID, payload digest, MERGE, and post-write check.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS PRESENTATION.INFECTED_TICK_DERIVED_RESULTS (
    result_id VARCHAR NOT NULL,
    contract_version VARCHAR NOT NULL,
    metric_identity VARCHAR NOT NULL,
    metric_id VARCHAR NOT NULL,
    methodology_version VARCHAR NOT NULL,
    calculation_version VARCHAR NOT NULL,
    result_revision VARCHAR(64) NOT NULL,
    result_state VARCHAR NOT NULL,
    native_grain VARCHAR NOT NULL,
    source_site_id VARCHAR,
    source_event_id VARCHAR,
    collection_or_tested_date DATE,
    payload_sha256 VARCHAR(64) NOT NULL,
    safe_payload VARIANT NOT NULL,
    staged_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (result_id)
);

GRANT USAGE ON SCHEMA PRESENTATION TO ROLE OH_LYME_DEV_RUNTIME;
GRANT SELECT, INSERT ON TABLE PRESENTATION.INFECTED_TICK_DERIVED_RESULTS
    TO ROLE OH_LYME_DEV_RUNTIME;
GRANT USAGE ON SCHEMA PRESENTATION TO ROLE OH_LYME_DEV_READ;
GRANT SELECT ON TABLE PRESENTATION.INFECTED_TICK_DERIVED_RESULTS
    TO ROLE OH_LYME_DEV_READ;
