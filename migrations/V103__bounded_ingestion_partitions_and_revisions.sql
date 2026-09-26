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

-- One immutable capture per run/logical record. record_revision identifies
-- content; an identical recapture retains that identity with new run lineage.
CREATE TABLE IF NOT EXISTS GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS (
    capture_record_id VARCHAR PRIMARY KEY,
    record_revision VARCHAR NOT NULL,
    record_id VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    dataset_id VARCHAR NOT NULL,
    resource_key VARCHAR NOT NULL,
    source_definition_version NUMBER NOT NULL,
    ingestion_run_id VARCHAR NOT NULL,
    source_record_id VARCHAR,
    artifact_id VARCHAR NOT NULL,
    artifact_sha256 VARCHAR(64) NOT NULL,
    source_row_hash VARCHAR(64) NOT NULL,
    normalized_sha256 VARCHAR(64) NOT NULL,
    transformation_version VARCHAR NOT NULL,
    payload VARIANT NOT NULL,
    retrieved_at TIMESTAMP_LTZ NOT NULL,
    observed_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

-- The runtime uses insert-only MERGEs and SELECT verification/replay on these tables.
-- No V103 statement updates or deletes a matched row.
GRANT SELECT, INSERT ON TABLE GOVERNANCE.INGESTION_RUN_NORMALIZED_PARTITIONS
    TO ROLE OH_LYME_{{ ENV }}_RUNTIME;
GRANT SELECT, INSERT ON TABLE GOVERNANCE.INGESTION_RUN_PARTITION_COMPLETIONS
    TO ROLE OH_LYME_{{ ENV }}_RUNTIME;
GRANT SELECT, INSERT ON TABLE GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS
    TO ROLE OH_LYME_{{ ENV }}_RUNTIME;
GRANT USAGE ON SCHEMA GOVERNANCE
    TO ROLE OH_LYME_{{ ENV }}_MIGRATION_DEPLOYER;
GRANT SELECT ON TABLE GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS
    TO ROLE OH_LYME_{{ ENV }}_MIGRATION_DEPLOYER;
