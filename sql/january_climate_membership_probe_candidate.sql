-- Experimental SELECT only; NOT a migration. No deployment/performance acceptance.
-- Valid published v2 manifests contain unique string capture IDs.
-- Preserve exact set membership and every revision/metadata lineage guard.
-- SQL array membership may still run before selective filters; benchmark the plan.
WITH current_climate AS (
    SELECT r.release_id, r.source_manifest:climate_extension AS extension
    FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
    JOIN PRESENTATION.SEMANTIC_RELEASES r ON r.release_id=p.current_release_id
    WHERE p.pointer_key='ATLAS' AND r.status='PUBLISHED'
      AND r.source_manifest:climate_extension:contract_version::VARCHAR =
          'atlas-january-climate-release-extension-v2'
), records AS (
    SELECT c.release_id, v.payload:record AS record, v.retrieved_at,
           m.value AS metadata
    FROM current_climate c
    JOIN GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS v
      ON v.ingestion_run_id=c.extension:ingestion_run_id::VARCHAR
     AND v.artifact_id=c.extension:sources:noaa:artifact_id::VARCHAR
     AND v.artifact_sha256=c.extension:sources:noaa:sha256::VARCHAR,
    LATERAL FLATTEN(INPUT => c.extension:metadata) m
    WHERE v.resource_key='noaa_nclimgrid_daily_202501'
      AND v.source_definition_version=2
      AND ARRAY_CONTAINS(TO_VARIANT(v.capture_record_id), c.extension:capture_ids)
      AND m.value:measure:measure_id::VARCHAR=
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
       -- Preserve storage type; normalize JSON null to SQL NULL.
       IFF(IS_NULL_VALUE(record:value), NULL, record:value) AS value,
       CASE WHEN record:coverage_status::VARCHAR='OUT_OF_SOURCE_COVERAGE' THEN 'UNAVAILABLE'
            WHEN record:coverage_status::VARCHAR<>'COMPLETE' THEN 'MISSING'
            WHEN record:value=0 THEN 'ZERO' ELSE 'OBSERVED' END AS value_state,
       record:unit::VARCHAR AS unit, NULL::VARCHAR AS denominator,
       record:coverage_status::VARCHAR AS coverage_status,
       record:source_time_present::BOOLEAN AS source_time_present,
       -- Retain VARIANT numeric storage for support quantities, including DECIMAL.
       IFF(IS_NULL_VALUE(record:expected_area_m2), NULL, record:expected_area_m2) AS expected_area_m2,
       IFF(IS_NULL_VALUE(record:intersected_area_m2), NULL, record:intersected_area_m2) AS intersected_area_m2,
       IFF(IS_NULL_VALUE(record:source_supported_area_m2), NULL, record:source_supported_area_m2) AS source_supported_area_m2,
       IFF(IS_NULL_VALUE(record:valid_area_m2), NULL, record:valid_area_m2) AS valid_area_m2,
       IFF(IS_NULL_VALUE(record:source_coverage_fraction), NULL, record:source_coverage_fraction) AS source_coverage_fraction,
       IFF(IS_NULL_VALUE(record:valid_fraction_of_supported_area), NULL, record:valid_fraction_of_supported_area) AS valid_fraction_of_supported_area,
       TYPEOF(record:value) AS value_stored_type,
       IFF(TYPEOF(record:value)='DOUBLE', AS_DOUBLE(record:value), NULL) AS value_native_double,
       TYPEOF(record:expected_area_m2) AS expected_area_m2_stored_type,
       IFF(TYPEOF(record:expected_area_m2)='DOUBLE', AS_DOUBLE(record:expected_area_m2), NULL) AS expected_area_m2_native_double,
       TYPEOF(record:intersected_area_m2) AS intersected_area_m2_stored_type,
       IFF(TYPEOF(record:intersected_area_m2)='DOUBLE', AS_DOUBLE(record:intersected_area_m2), NULL) AS intersected_area_m2_native_double,
       TYPEOF(record:source_supported_area_m2) AS source_supported_area_m2_stored_type,
       IFF(TYPEOF(record:source_supported_area_m2)='DOUBLE', AS_DOUBLE(record:source_supported_area_m2), NULL) AS source_supported_area_m2_native_double,
       TYPEOF(record:valid_area_m2) AS valid_area_m2_stored_type,
       IFF(TYPEOF(record:valid_area_m2)='DOUBLE', AS_DOUBLE(record:valid_area_m2), NULL) AS valid_area_m2_native_double,
       TYPEOF(record:source_coverage_fraction) AS source_coverage_fraction_stored_type,
       IFF(TYPEOF(record:source_coverage_fraction)='DOUBLE', AS_DOUBLE(record:source_coverage_fraction), NULL) AS source_coverage_fraction_native_double,
       TYPEOF(record:valid_fraction_of_supported_area) AS valid_fraction_of_supported_area_stored_type,
       IFF(TYPEOF(record:valid_fraction_of_supported_area)='DOUBLE', AS_DOUBLE(record:valid_fraction_of_supported_area), NULL) AS valid_fraction_of_supported_area_native_double,
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
