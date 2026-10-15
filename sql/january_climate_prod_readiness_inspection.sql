-- Prepared read-only inspection, NOT executed or authorized by this file.
-- PROD only; existing ATLAS_PROD_MIGRATOR / OH_LYME_PROD_MIGRATION_DEPLOYER.
-- Identity first. XS warehouse cost properties must pass before SELECT data reads.
-- 180s process +15s grace; 60s statement /10s queue /65s network; no retries.
-- No credential substitution, grants, DDL, DML, capture or publication.
SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE(), CURRENT_REGION(), CURRENT_ACCOUNT();
SHOW WAREHOUSES LIKE 'OH_LYME_PROD_APPROVAL_XS_WH';
SELECT version, filename, sha256, applied_at
FROM ONE_HEALTH_LYME_GAP_ATLAS_PROD.GOVERNANCE.SCHEMA_MIGRATIONS
ORDER BY version LIMIT 151;
SHOW VIEWS LIKE 'CURRENT_CLIMATE_%' IN SCHEMA ONE_HEALTH_LYME_GAP_ATLAS_PROD.PRESENTATION;
SELECT data_source_version_id, resource_key, ingestion_run_id, artifact_id, status, approved_decision_id
FROM ONE_HEALTH_LYME_GAP_ATLAS_PROD.GOVERNANCE.DATA_SOURCE_VERSIONS
WHERE resource_key IN ('noaa_nclimgrid_daily_202501', 'census_tiger_2025_us_county_analysis')
ORDER BY resource_key, data_source_version_id LIMIT 21;
SELECT ingestion_run_id, resource_key, run_mode, status, config_sha256, started_at, completed_at
FROM ONE_HEALTH_LYME_GAP_ATLAS_PROD.GOVERNANCE.INGESTION_RUNS
WHERE resource_key IN ('noaa_nclimgrid_daily_202501', 'census_tiger_2025_us_county_analysis')
ORDER BY started_at DESC LIMIT 21;
SELECT release_id, status, bundle_sha256,
       source_manifest:climate_extension:contract_version::VARCHAR AS climate_contract,
       source_manifest:climate_extension:ingestion_run_id::VARCHAR AS climate_run
FROM ONE_HEALTH_LYME_GAP_ATLAS_PROD.PRESENTATION.SEMANTIC_RELEASES
ORDER BY release_id DESC LIMIT 21;
SELECT pointer_key, current_release_id
FROM ONE_HEALTH_LYME_GAP_ATLAS_PROD.PRESENTATION.SEMANTIC_RELEASE_POINTER
WHERE pointer_key='ATLAS' LIMIT 2;
SHOW GRANTS TO ROLE OH_LYME_PROD_READ;
SHOW GRANTS ON SCHEMA ONE_HEALTH_LYME_GAP_ATLAS_PROD.PRESENTATION;
