-- Epic #252 / Story #275: API-safe views over the governed semantic release.
-- This migration runs under the deployment-only governed-view owner.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE VIEW PRESENTATION.CURRENT_RELEASE_V AS
SELECT r.release_id, r.schema_version, r.generated_at, r.loaded_at, r.scope,
       r.bundle_sha256, r.score_defaults, r.methodology_version, r.limitations
FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
JOIN PRESENTATION.SEMANTIC_RELEASES r
  ON r.release_id = p.current_release_id
WHERE p.pointer_key = 'ATLAS'
  AND r.status = 'PUBLISHED';

CREATE OR REPLACE VIEW PRESENTATION.CURRENT_SOURCE_METADATA_V AS
SELECT s.source_key, s.label, s.vintage, s.source_url, s.note
FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
JOIN PRESENTATION.SEMANTIC_RELEASES r
  ON r.release_id = p.current_release_id
JOIN PRESENTATION.SEMANTIC_DATA_SOURCES s
  ON s.release_id = r.release_id
WHERE p.pointer_key = 'ATLAS'
  AND r.status = 'PUBLISHED';

CREATE OR REPLACE VIEW PRESENTATION.CURRENT_COUNTY_ATLAS_V AS
SELECT c.release_id, c.fips, c.county, c.state, c.state_name, c.population,
       c.in_contiguous_tick_scope, c.human_status, c.case_count_floor_2023,
       c.incidence_floor_2023, c.state_unallocated_records_2023, c.tick_status,
       c.scapularis_status, c.pacificus_status, c.burgdorferi_status,
       c.svi_percentile, c.uninsured_percentile, c.uninsured_percent,
       c.rucc_2023, c.evidence_completeness, c.geometry_json
FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
JOIN PRESENTATION.SEMANTIC_RELEASES r
  ON r.release_id = p.current_release_id
JOIN PRESENTATION.SEMANTIC_COUNTY_ATLAS c
  ON c.release_id = r.release_id
WHERE p.pointer_key = 'ATLAS'
  AND r.status = 'PUBLISHED';

CREATE OR REPLACE VIEW PRESENTATION.SEMANTIC_RELEASE_STATUS_V AS
WITH county_counts AS (
    SELECT release_id, COUNT(*) AS county_count
    FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS
    GROUP BY release_id
), observation_counts AS (
    SELECT release_id, COUNT(*) AS observation_count,
           COUNT_IF(value_state IS NULL OR source_version_id IS NULL
                    OR ingestion_run_id IS NULL OR artifact_id IS NULL)
             AS missing_observation_lineage
    FROM PRESENTATION.SEMANTIC_OBSERVATIONS
    GROUP BY release_id
)
SELECT r.release_id, r.status, r.schema_version, r.generated_at, r.loaded_at,
       r.methodology_version, r.bundle_sha256, r.created_by, r.approved_by,
       r.approved_at, p.current_release_id,
       COALESCE(c.county_count, 0) AS county_count,
       COALESCE(o.observation_count, 0) AS observation_count,
       COALESCE(o.missing_observation_lineage, 0) AS missing_observation_lineage
FROM PRESENTATION.SEMANTIC_RELEASES r
LEFT JOIN PRESENTATION.SEMANTIC_RELEASE_POINTER p
  ON p.pointer_key = 'ATLAS'
LEFT JOIN county_counts c
  ON c.release_id = r.release_id
LEFT JOIN observation_counts o
  ON o.release_id = r.release_id;

GRANT SELECT ON VIEW PRESENTATION.CURRENT_RELEASE_V
    TO ROLE OH_LYME_{{ ENV }}_API_RUNTIME;
GRANT SELECT ON VIEW PRESENTATION.CURRENT_SOURCE_METADATA_V
    TO ROLE OH_LYME_{{ ENV }}_API_RUNTIME;
GRANT SELECT ON VIEW PRESENTATION.CURRENT_COUNTY_ATLAS_V
    TO ROLE OH_LYME_{{ ENV }}_API_RUNTIME;
GRANT SELECT ON VIEW PRESENTATION.SEMANTIC_RELEASE_STATUS_V
    TO ROLE OH_LYME_{{ ENV }}_GOVERNED_VIEW_OWNER;
GRANT SELECT ON VIEW PRESENTATION.CURRENT_RELEASE_V
    TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT SELECT ON VIEW PRESENTATION.CURRENT_SOURCE_METADATA_V
    TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT SELECT ON VIEW PRESENTATION.CURRENT_COUNTY_ATLAS_V
    TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
GRANT SELECT ON VIEW PRESENTATION.SEMANTIC_RELEASE_STATUS_V
    TO ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME;
