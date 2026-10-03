-- DATA199 bounded consumer audit. SELECT only; no source run or publication.
-- Run identity first and verify the named connection's intended role/database.
-- ATLAS_DEV_READ -> OH_LYME_DEV_READ / ONE_HEALTH_LYME_GAP_ATLAS_DEV
-- ATLAS_PROD_RUNTIME_AUDIT -> OH_LYME_PROD_RUNTIME / ONE_HEALTH_LYME_GAP_ATLAS_PROD
-- Execute statements separately: an access denial must not hide prior evidence.
SELECT CURRENT_USER() AS audit_user, CURRENT_ROLE() AS audit_role,
       CURRENT_DATABASE() AS audit_database, CURRENT_WAREHOUSE() AS audit_warehouse,
       CURRENT_TIMESTAMP() AS audit_at;

SELECT release_id, bundle_sha256 FROM PRESENTATION.CURRENT_RELEASE_V;

SELECT release_id, COUNT(*) AS county_rows, COUNT(DISTINCT fips) AS unique_fips,
       COUNT_IF(NOT REGEXP_LIKE(fips, '[0-9]{5}')) AS invalid_fips,
       COUNT_IF(population < 0) AS invalid_population,
       COUNT_IF(svi_percentile < 0 OR svi_percentile > 1) AS invalid_svi,
       COUNT_IF(uninsured_percentile < 0 OR uninsured_percentile > 1) AS invalid_uninsured_rank,
       COUNT_IF(uninsured_percent < 0 OR uninsured_percent > 100) AS invalid_uninsured_percent,
       COUNT_IF(population IS NULL) AS missing_population,
       COUNT_IF(svi_percentile IS NULL) AS missing_svi,
       COUNT_IF(uninsured_percentile IS NULL) AS missing_uninsured_rank,
       COUNT_IF(uninsured_percent IS NULL) AS missing_uninsured_percent,
       COUNT_IF(svi_percentile = -999 OR uninsured_percentile = -999
                OR uninsured_percent = -999 OR population = -999) AS sentinel_rows,
       COUNT_IF(geometry_json:type::VARCHAR NOT IN ('Polygon', 'MultiPolygon')) AS invalid_geometry_type
FROM PRESENTATION.CURRENT_COUNTY_ATLAS_V GROUP BY release_id;

SELECT source_key, label, vintage, note
FROM PRESENTATION.CURRENT_SOURCE_METADATA_V WHERE source_key = 'context_svi';

-- PROD runtime can read this status view. ID presence is not an exact lineage join.
SELECT release_id, county_count, observation_count, missing_observation_lineage, bundle_sha256
FROM PRESENTATION.SEMANTIC_RELEASE_STATUS_V WHERE release_id = current_release_id;

-- DEV readable; PROD runtime returned 002003 on 2026-10-03. Do not change roles/grants.
SELECT measure_id, unit, denominator, temporal_grain, missingness_semantics, release_version
FROM PRESENTATION.CURRENT_MEASURE_METADATA_V
WHERE measure_id IN ('population_2022', 'svi_percentile_2022',
                     'uninsured_percent_2022', 'uninsured_percentile_2022');

-- Both named audit roles returned 002003. This is a visibility probe, not full proof.
SELECT COUNT(*) AS source_rows, COUNT(DISTINCT source_version_id) AS versions,
       COUNT(DISTINCT ingestion_run_id) AS runs, COUNT(DISTINCT artifact_id) AS artifacts
FROM PRESENTATION.SEMANTIC_DATA_SOURCES
WHERE source_key = 'context_svi'
  AND release_id = (SELECT release_id FROM PRESENTATION.CURRENT_RELEASE_V);
