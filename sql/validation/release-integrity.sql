-- Read-only DATA698/702 audit. Named least-privilege PAT context first.
-- This file does not publish, approve, infer, change grants or retag outputs.
ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS=60, STATEMENT_QUEUED_TIMEOUT_IN_SECONDS=10,
 QUERY_TAG='DATA698_RELEASE_INTEGRITY_READ_ONLY';
SELECT CURRENT_USER(),CURRENT_ROLE(),CURRENT_DATABASE(),CURRENT_WAREHOUSE();
SELECT release_id,bundle_sha256,schema_version,methodology_version,scope
 FROM PRESENTATION.CURRENT_RELEASE_V;
SELECT release_id,county_count,observation_count,missing_observation_lineage
 FROM PRESENTATION.SEMANTIC_RELEASE_STATUS_V WHERE status='PUBLISHED';
SELECT release_id,model_version,prediction_batch_version,priority_tier,COUNT(*) AS stored_rows,
 COUNT_IF(county_fips NOT LIKE '02%' AND county_fips NOT LIKE '15%') AS conus_dc_rows
 FROM PRESENTATION.CURRENT_TIER1_COUNTY_REVIEW_V GROUP BY ALL;
SELECT COUNT(*) AS stored_rows,COUNT_IF(m.release_id=c.release_id) AS identical_release_rows
 FROM PRESENTATION.CURRENT_TIER1_COUNTY_REVIEW_V m
 JOIN PRESENTATION.CURRENT_COUNTY_ATLAS_V c ON c.fips=m.county_fips;
SELECT source_key,measure_id,COUNT(*) AS row_count,COUNT(DISTINCT county_fips) AS county_count,
 MIN(period_start) AS first_day,MAX(period_end) AS last_day
 FROM PRESENTATION.CURRENT_COUNTY_OBSERVATIONS_V GROUP BY ALL;
SELECT release_id,source_key,source_version_id,ingestion_run_id,artifact_id,artifact_sha256,
 COUNT(DISTINCT county_fips) AS county_count,COUNT(*) AS observation_rows
 FROM LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V GROUP BY ALL;
-- After V158 and approved publication only:
-- SELECT model_id,class_id,class_name,COUNT(*) FROM
-- PRESENTATION.CURRENT_COUNTY_SURVEILLANCE_SITUATIONS_V GROUP BY ALL;
-- No base-table reads or publisher calls belong in API acceptance probes.
