-- PROPOSAL ONLY: no execution until scoped owner approval and harness review.
-- Baseline: 581ea524f223c468422716d1cc368158aa59b45d; DEV only.
-- New session; create before BEGIN TRANSACTION. No OR REPLACE / IF NOT EXISTS.
CREATE TEMPORARY TABLE ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE._DATA376_20261002_A_COUNTIES (
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
CREATE TEMPORARY TABLE ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE._DATA376_20261002_A_OBSERVATIONS (
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
CREATE TEMPORARY TABLE ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE._DATA376_20261002_A_CONDITIONS (conditions VARIANT);
