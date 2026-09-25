-- Additive Story #426 storage. No historical V069/V070 row is rewritten.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS GOVERNANCE.INGESTION_RUN_NORMALIZED_PARTITIONS (
    ingestion_run_id VARCHAR NOT NULL,
    partition_ordinal NUMBER NOT NULL,
    partition_id VARCHAR NOT NULL,
    value_sha256 VARCHAR(64) NOT NULL,
    row_count NUMBER NOT NULL,
    byte_count NUMBER NOT NULL,
    records VARIANT NOT NULL,
    created_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (ingestion_run_id, partition_ordinal)
);

CREATE TABLE IF NOT EXISTS GOVERNANCE.INGESTION_RUN_PARTITION_COMPLETIONS (
    ingestion_run_id VARCHAR PRIMARY KEY,
    partition_count NUMBER NOT NULL,
    completed_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

-- A physical revision stores a distinct artifact-content/record result.
-- Repeat acquisition remains visible in INGESTION_REQUESTS/RAW_ARTIFACTS
-- without changing the first V069 projection row or creating a false revision.
CREATE TABLE IF NOT EXISTS GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS (
    record_revision VARCHAR PRIMARY KEY,
    record_id VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    dataset_id VARCHAR NOT NULL,
    resource_key VARCHAR NOT NULL,
    source_definition_version NUMBER NOT NULL,
    ingestion_run_id VARCHAR NOT NULL,
    artifact_id VARCHAR NOT NULL,
    artifact_sha256 VARCHAR(64) NOT NULL,
    source_row_hash VARCHAR(64) NOT NULL,
    normalized_sha256 VARCHAR(64) NOT NULL,
    transformation_version VARCHAR NOT NULL,
    payload VARIANT NOT NULL,
    retrieved_at TIMESTAMP_LTZ NOT NULL,
    observed_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

GRANT SELECT, INSERT ON TABLE GOVERNANCE.INGESTION_RUN_NORMALIZED_PARTITIONS
    TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT SELECT, INSERT ON TABLE GOVERNANCE.INGESTION_RUN_PARTITION_COMPLETIONS
    TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT SELECT, INSERT ON TABLE GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS
    TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
