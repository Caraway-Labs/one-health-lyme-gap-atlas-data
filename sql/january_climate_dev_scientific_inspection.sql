-- Prepared read-only scientific sample, NOT executed or authorized by this file.
-- Existing protected DEV migration identity; unchanged account/warehouse guards.
-- 180s process +15s grace; 60s statement /10s queue /65s network; no retries.
SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE(), CURRENT_REGION(), CURRENT_ACCOUNT();
SHOW WAREHOUSES LIKE 'OH_LYME_DEV_INGEST_XS_WH';
SELECT release_id, measure_id, county_fips, period_start, period_end, value,
       value_state, unit, coverage_status, source_time_present, day_convention,
       expected_area_m2, intersected_area_m2, source_supported_area_m2, valid_area_m2,
       source_coverage_fraction, valid_fraction_of_supported_area,
       publisher, dataset_id, source_vintage, methodology_version, weight_version,
       geometry_version, metadata_revision_id, atlas_acquired_at, source_published_at
FROM ONE_HEALTH_LYME_GAP_ATLAS_DEV.PRESENTATION.CURRENT_CLIMATE_COUNTY_DAY_OBSERVATIONS_V
WHERE release_id='governed-2026-10-09-january-climate-dev'
  AND period_start='2025-01-17' AND county_fips IN ('48277','02013')
  AND measure_id IN ('nclimgrid_prcp_county_day','nclimgrid_tmin_county_day',
                     'nclimgrid_tmax_county_day','nclimgrid_tavg_county_day')
ORDER BY county_fips, measure_id LIMIT 9;
SELECT release_id, measure_id, metadata_revision_id, unit, allowed_value_states, methodology_version, limitations
FROM ONE_HEALTH_LYME_GAP_ATLAS_DEV.PRESENTATION.CURRENT_CLIMATE_MEASURE_METADATA_V
WHERE release_id='governed-2026-10-09-january-climate-dev'
ORDER BY measure_id LIMIT 5;
SELECT release_id, status, bundle_sha256,
       source_manifest:climate_extension:ingestion_run_id::VARCHAR AS climate_run,
       source_manifest:climate_extension:sources AS retained_source_bindings
FROM ONE_HEALTH_LYME_GAP_ATLAS_DEV.PRESENTATION.SEMANTIC_RELEASES
WHERE release_id='governed-2026-10-09-january-climate-dev' LIMIT 2;
