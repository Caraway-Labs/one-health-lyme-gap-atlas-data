-- Story #171: DEV-only immutable categorical profiles. These are derived
-- evidence states, not source observations or county semantic-release rows.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS PRESENTATION.SURVEILLANCE_COVERAGE_DERIVED_RESULTS (
    result_id VARCHAR NOT NULL,
    contract_version VARCHAR NOT NULL,
    coverage_identity VARCHAR NOT NULL,
    construct_id VARCHAR NOT NULL,
    methodology_version VARCHAR NOT NULL,
    calculation_version VARCHAR NOT NULL,
    result_revision VARCHAR(64) NOT NULL,
    result_state VARCHAR NOT NULL,
    native_grain VARCHAR NOT NULL,
    source_dataset_id VARCHAR NOT NULL,
    source_version_id VARCHAR NOT NULL,
    county_fips VARCHAR,
    source_site_id VARCHAR,
    source_event_id VARCHAR,
    collection_or_tested_date DATE,
    payload_sha256 VARCHAR(64) NOT NULL,
    safe_payload VARIANT NOT NULL,
    staged_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (result_id)
);

GRANT USAGE ON SCHEMA PRESENTATION TO ROLE OH_LYME_DEV_RUNTIME;
GRANT SELECT, INSERT ON TABLE PRESENTATION.SURVEILLANCE_COVERAGE_DERIVED_RESULTS
    TO ROLE OH_LYME_DEV_RUNTIME;
GRANT USAGE ON SCHEMA PRESENTATION TO ROLE OH_LYME_DEV_READ;
GRANT SELECT ON TABLE PRESENTATION.SURVEILLANCE_COVERAGE_DERIVED_RESULTS
    TO ROLE OH_LYME_DEV_READ;
