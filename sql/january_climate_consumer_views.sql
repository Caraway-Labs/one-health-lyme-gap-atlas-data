-- Reviewed SQL proposal; not in the migration runner. No grants or execution.
-- Reserve a numbered migration with the deployment owner after exact review.
-- Existing migration identity needs SELECT on V103 revisions and release tables.
CREATE OR REPLACE VIEW PRESENTATION.CURRENT_CLIMATE_COUNTY_DAY_OBSERVATIONS_V AS
WITH current_climate AS (
    SELECT r.release_id, r.source_manifest:climate_extension AS extension
    FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
    JOIN PRESENTATION.SEMANTIC_RELEASES r ON r.release_id=p.current_release_id
    WHERE p.pointer_key='ATLAS' AND r.status='PUBLISHED'
      AND r.source_manifest:climate_extension:contract_version::VARCHAR =
          'atlas-january-climate-release-extension-v1'
), records AS (
    SELECT c.release_id, c.extension, v.payload:record AS record, v.retrieved_at,
           m.value AS metadata
    FROM current_climate c
    JOIN GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS v
      ON v.ingestion_run_id=c.extension:ingestion_run_id::VARCHAR
     AND v.resource_key='noaa_nclimgrid_daily_202501'
     AND v.source_definition_version=2
     AND v.artifact_id=c.extension:sources:noaa:artifact_id::VARCHAR
     AND v.artifact_sha256=c.extension:sources:noaa:sha256::VARCHAR,
    LATERAL FLATTEN(INPUT => c.extension:metadata) m
    WHERE m.value:measure:measure_id::VARCHAR =
          'nclimgrid_' || LOWER(v.payload:record:measure::VARCHAR) || '_county_day'
)
SELECT release_id,
       metadata:measure:measure_id::VARCHAR AS measure_id,
       metadata:measure:semantic_version::VARCHAR AS semantic_version,
       metadata:revision_id::VARCHAR AS metadata_revision_id,
       record:county_fips::VARCHAR AS county_fips,
       record:observation_date::DATE AS period_start,
       record:observation_date::DATE AS period_end,
       'DAY' AS temporal_resolution,
       'Labeled 24-hour period ending in the early morning; not a midnight calendar day'
           AS day_convention,
       -- AS_DOUBLE reads native DOUBLE, avoiding lossy TO_JSON reconstruction.
       AS_DOUBLE(record:value) AS value,
       CASE WHEN record:coverage_status::VARCHAR='OUT_OF_SOURCE_COVERAGE' THEN 'UNAVAILABLE'
            WHEN record:coverage_status::VARCHAR<>'COMPLETE' THEN 'MISSING'
            WHEN AS_DOUBLE(record:value)=0 THEN 'ZERO' ELSE 'OBSERVED' END AS value_state,
       record:unit::VARCHAR AS unit, NULL::VARCHAR AS denominator,
       record:coverage_status::VARCHAR AS coverage_status,
       record:source_time_present::BOOLEAN AS source_time_present,
       -- Retain VARIANT numeric storage for support quantities, including DECIMAL.
       record:expected_area_m2 AS expected_area_m2,
       record:intersected_area_m2 AS intersected_area_m2,
       record:source_supported_area_m2 AS source_supported_area_m2,
       record:valid_area_m2 AS valid_area_m2,
       record:source_coverage_fraction AS source_coverage_fraction,
       record:valid_fraction_of_supported_area AS valid_fraction_of_supported_area,
       retrieved_at AS atlas_acquired_at,
       NULL::TIMESTAMP_TZ AS source_published_at,
       record:upstream_date_modified::VARCHAR AS upstream_date_modified,
       metadata:provenance:publisher:value::VARCHAR AS publisher,
       metadata:provenance:dataset_id:value::VARCHAR AS dataset_id,
       metadata:provenance:source_vintage:value::VARCHAR AS source_vintage,
       record:transformation_version::VARCHAR AS methodology_version,
       record:weight_version::VARCHAR AS weight_version,
       record:geometry_version::VARCHAR AS geometry_version,
       metadata:limitations AS limitations
FROM records;

CREATE OR REPLACE VIEW PRESENTATION.CURRENT_CLIMATE_MEASURE_METADATA_V AS
SELECT r.release_id,
       m.value:measure:measure_id::VARCHAR AS measure_id,
       m.value:measure:indicator_id::VARCHAR AS indicator_id,
       m.value:measure:semantic_version::VARCHAR AS semantic_version,
       m.value:revision_id::VARCHAR AS metadata_revision_id,
       m.value:label::VARCHAR AS label,
       m.value:definition::VARCHAR AS definition,
       m.value:unit::VARCHAR AS unit,
       NULL::VARCHAR AS denominator,
       'COUNTY' AS geography_grain, 'DAY' AS temporal_resolution,
       m.value:allowed_value_states AS allowed_value_states,
       m.value:provenance:method_version:value::VARCHAR AS methodology_version,
       m.value:limitations AS limitations
FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
JOIN PRESENTATION.SEMANTIC_RELEASES r ON r.release_id=p.current_release_id,
LATERAL FLATTEN(INPUT => r.source_manifest:climate_extension:metadata) m
WHERE p.pointer_key='ATLAS' AND r.status='PUBLISHED'
  AND r.source_manifest:climate_extension:contract_version::VARCHAR =
      'atlas-january-climate-release-extension-v1';
