-- Phase 2: one idempotent generic storage boundary for SourceDefinition runs.
-- Source-faithful bytes remain in GOVERNANCE.RAW_ARTIFACTS/Spaces; these tables
-- retain only the governed row projection and its lineage anchors.

USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS RAW.GOVERNED_SOURCE_RECORDS (
    record_id VARCHAR PRIMARY KEY,
    source_id VARCHAR NOT NULL,
    dataset_id VARCHAR NOT NULL,
    resource_key VARCHAR NOT NULL,
    source_definition_version NUMBER NOT NULL,
    ingestion_run_id VARCHAR NOT NULL,
    source_record_id VARCHAR,
    source_row_hash VARCHAR(64) NOT NULL,
    payload VARIANT NOT NULL,
    retrieved_at TIMESTAMP_LTZ NOT NULL,
    loaded_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS STAGING.GOVERNED_SOURCE_RECORDS (
    record_id VARCHAR PRIMARY KEY,
    source_id VARCHAR NOT NULL,
    dataset_id VARCHAR NOT NULL,
    resource_key VARCHAR NOT NULL,
    source_definition_version NUMBER NOT NULL,
    ingestion_run_id VARCHAR NOT NULL,
    source_record_id VARCHAR,
    source_row_hash VARCHAR(64) NOT NULL,
    payload VARIANT NOT NULL,
    retrieved_at TIMESTAMP_LTZ NOT NULL,
    normalized_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS CONFORMED.GOVERNED_SOURCE_RECORDS (
    record_id VARCHAR PRIMARY KEY,
    source_id VARCHAR NOT NULL,
    dataset_id VARCHAR NOT NULL,
    resource_key VARCHAR NOT NULL,
    source_definition_version NUMBER NOT NULL,
    ingestion_run_id VARCHAR NOT NULL,
    source_record_id VARCHAR,
    source_row_hash VARCHAR(64) NOT NULL,
    payload VARIANT NOT NULL,
    retrieved_at TIMESTAMP_LTZ NOT NULL,
    conformed_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS GOVERNANCE.INGESTION_PUBLICATIONS (
    publication_id VARCHAR PRIMARY KEY,
    resource_key VARCHAR NOT NULL,
    ingestion_run_id VARCHAR NOT NULL,
    source_definition_version NUMBER NOT NULL,
    status VARCHAR NOT NULL,
    target_relation VARCHAR NOT NULL,
    record_count NUMBER NOT NULL,
    lineage VARIANT NOT NULL,
    published_at TIMESTAMP_LTZ NOT NULL
);

GRANT SELECT, INSERT, UPDATE ON TABLE RAW.GOVERNED_SOURCE_RECORDS
    TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT SELECT, INSERT, UPDATE ON TABLE STAGING.GOVERNED_SOURCE_RECORDS
    TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT SELECT, INSERT, UPDATE ON TABLE CONFORMED.GOVERNED_SOURCE_RECORDS
    TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT SELECT, INSERT, UPDATE ON TABLE GOVERNANCE.INGESTION_PUBLICATIONS
    TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
