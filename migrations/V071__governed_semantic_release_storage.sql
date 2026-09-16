-- Epic #252 / Story #273: immutable semantic-release storage.
--
-- These tables are the canonical DATA SOURCE -> DATASET -> INDICATOR ->
-- MEASURE -> OBSERVATION boundary.  They deliberately do not reference the
-- retained Alpha POC database or expose physical ingestion tables as an API
-- contract.  Release content is inserted once by the protected release
-- builder; the pointer and event log are the only mutable release controls.
USE DATABASE {{ DATABASE }};

CREATE SCHEMA IF NOT EXISTS PRESENTATION;

CREATE TABLE IF NOT EXISTS PRESENTATION.SEMANTIC_RELEASES (
    release_id VARCHAR PRIMARY KEY,
    schema_version VARCHAR NOT NULL,
    generated_at TIMESTAMP_LTZ NOT NULL,
    loaded_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    scope VARCHAR NOT NULL,
    bundle_sha256 VARCHAR(64) NOT NULL,
    score_defaults VARIANT NOT NULL,
    methodology_version VARCHAR NOT NULL,
    limitations VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    source_manifest VARIANT NOT NULL,
    created_by VARCHAR NOT NULL,
    approved_by VARCHAR,
    approved_at TIMESTAMP_LTZ
);

CREATE TABLE IF NOT EXISTS PRESENTATION.SEMANTIC_DATA_SOURCES (
    release_id VARCHAR NOT NULL,
    source_key VARCHAR NOT NULL,
    resource_key VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    dataset_id VARCHAR NOT NULL,
    label VARCHAR NOT NULL,
    vintage VARCHAR NOT NULL,
    source_url VARCHAR NOT NULL,
    note VARCHAR NOT NULL,
    source_version_id VARCHAR NOT NULL,
    ingestion_run_id VARCHAR NOT NULL,
    artifact_id VARCHAR NOT NULL,
    created_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (release_id, source_key)
);

CREATE TABLE IF NOT EXISTS PRESENTATION.SEMANTIC_DATASETS (
    release_id VARCHAR NOT NULL,
    dataset_id VARCHAR NOT NULL,
    source_key VARCHAR NOT NULL,
    dataset_name VARCHAR NOT NULL,
    geography_semantics VARCHAR NOT NULL,
    temporal_semantics VARCHAR NOT NULL,
    limitations VARCHAR NOT NULL,
    created_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (release_id, dataset_id)
);

CREATE TABLE IF NOT EXISTS PRESENTATION.SEMANTIC_INDICATORS (
    release_id VARCHAR NOT NULL,
    indicator_id VARCHAR NOT NULL,
    label VARCHAR NOT NULL,
    description VARCHAR NOT NULL,
    limitation VARCHAR NOT NULL,
    created_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (release_id, indicator_id)
);

CREATE TABLE IF NOT EXISTS PRESENTATION.SEMANTIC_MEASURES (
    release_id VARCHAR NOT NULL,
    measure_id VARCHAR NOT NULL,
    indicator_id VARCHAR NOT NULL,
    label VARCHAR NOT NULL,
    data_type VARCHAR NOT NULL,
    unit VARCHAR NOT NULL,
    geography_semantics VARCHAR NOT NULL,
    temporal_resolution VARCHAR NOT NULL,
    missingness_semantics VARCHAR NOT NULL,
    methodology VARCHAR NOT NULL,
    limitation VARCHAR NOT NULL,
    created_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (release_id, measure_id)
);

CREATE TABLE IF NOT EXISTS PRESENTATION.SEMANTIC_OBSERVATIONS (
    observation_id VARCHAR PRIMARY KEY,
    release_id VARCHAR NOT NULL,
    measure_id VARCHAR NOT NULL,
    fips VARCHAR(5),
    source_key VARCHAR NOT NULL,
    source_version_id VARCHAR NOT NULL,
    ingestion_run_id VARCHAR NOT NULL,
    artifact_id VARCHAR NOT NULL,
    source_record_id VARCHAR,
    source_row_hash VARCHAR(64),
    value VARIANT,
    value_state VARCHAR NOT NULL,
    retrieved_at TIMESTAMP_LTZ NOT NULL,
    geography_semantics VARCHAR NOT NULL,
    temporal_window VARCHAR NOT NULL,
    transformation_version VARCHAR NOT NULL,
    quality_state VARCHAR NOT NULL,
    limitations VARCHAR NOT NULL,
    created_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS PRESENTATION.SEMANTIC_COUNTY_ATLAS (
    release_id VARCHAR NOT NULL,
    fips VARCHAR(5) NOT NULL,
    county VARCHAR NOT NULL,
    state VARCHAR NOT NULL,
    state_name VARCHAR NOT NULL,
    population NUMBER,
    in_contiguous_tick_scope BOOLEAN NOT NULL,
    human_status VARCHAR NOT NULL,
    case_count_floor_2023 NUMBER,
    incidence_floor_2023 FLOAT,
    state_unallocated_records_2023 NUMBER,
    tick_status VARCHAR NOT NULL,
    scapularis_status VARCHAR,
    pacificus_status VARCHAR,
    burgdorferi_status VARCHAR NOT NULL,
    svi_percentile FLOAT,
    uninsured_percentile FLOAT,
    uninsured_percent FLOAT,
    rucc_2023 NUMBER,
    evidence_completeness NUMBER NOT NULL,
    geometry_json VARIANT NOT NULL,
    lineage VARIANT NOT NULL,
    created_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (release_id, fips)
);

CREATE TABLE IF NOT EXISTS PRESENTATION.SEMANTIC_RELEASE_EVENTS (
    event_id VARCHAR PRIMARY KEY,
    release_id VARCHAR NOT NULL,
    event_type VARCHAR NOT NULL,
    previous_release_id VARCHAR,
    actor VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    created_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS PRESENTATION.SEMANTIC_RELEASE_POINTER (
    pointer_key VARCHAR PRIMARY KEY,
    current_release_id VARCHAR NOT NULL,
    updated_by VARCHAR NOT NULL,
    updated_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

-- The migration/deployment identity owns release assembly.  Pipeline workers
-- never receive semantic-table writes; API access is through the view layer
-- created by V072.
GRANT USAGE ON SCHEMA PRESENTATION TO ROLE OH_LYME_{{ ENV }}_GOVERNED_VIEW_OWNER;
GRANT CREATE VIEW ON SCHEMA PRESENTATION TO ROLE OH_LYME_{{ ENV }}_GOVERNED_VIEW_OWNER;
GRANT USAGE ON SCHEMA PRESENTATION TO ROLE OH_LYME_{{ ENV }}_API_RUNTIME;
GRANT SELECT ON ALL TABLES IN SCHEMA PRESENTATION
    TO ROLE OH_LYME_{{ ENV }}_GOVERNED_VIEW_OWNER;
