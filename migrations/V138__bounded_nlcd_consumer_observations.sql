-- DATA594: extend the existing consumer view; preserve existing grants and human rows.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE VIEW PRESENTATION.CURRENT_COUNTY_OBSERVATIONS_V
COPY GRANTS AS
SELECT o.observation_id,
       m.measure_id,
       o.fips AS geography_id,
       'COUNTY' AS geography_type,
       o.fips AS county_fips,
       DATE '2023-01-01' AS period_start,
       DATE '2023-12-31' AS period_end,
       'YEAR' AS temporal_grain,
       o.value,
       o.value_state,
       m.unit,
       m.denominator,
       m.supported_stratifications,
       r.schema_version AS semantic_contract_version,
       r.release_id AS release_version,
       o.source_key,
       s.label AS source_label,
       s.vintage AS source_vintage,
       s.source_url,
       o.retrieved_at,
       o.transformation_version,
       m.methodology,
       r.methodology_version AS release_methodology_version,
       o.limitations AS observation_limitations,
       m.limitation AS measure_limitation,
       r.limitations AS release_limitations,
       s.source_id,
       s.dataset_id,
       mm.methodology_id
FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
JOIN PRESENTATION.SEMANTIC_RELEASES r
  ON r.release_id = p.current_release_id AND r.status = 'PUBLISHED'
JOIN PRESENTATION.SEMANTIC_OBSERVATIONS o ON o.release_id = r.release_id
JOIN PRESENTATION.CURRENT_MEASURE_METADATA_V m
  ON m.release_version = r.release_id AND m.measure_id = o.measure_id
JOIN PRESENTATION.SEMANTIC_DATA_SOURCES s
  ON s.release_id = r.release_id AND s.source_key = o.source_key
LEFT JOIN PRESENTATION.CURRENT_METHODOLOGY_METADATA_V mm
  ON mm.release_version = r.release_id AND mm.measure_id = m.measure_id
JOIN PRESENTATION.SEMANTIC_COUNTY_ATLAS c
  ON c.release_id = r.release_id AND c.fips = o.fips
WHERE p.pointer_key = 'ATLAS'
  AND o.measure_id IN ('human_status', 'case_count_floor_2023', 'incidence_floor_2023')
  AND o.source_key = 'human'
  AND o.geography_semantics = 'COUNTY_FIPS_5'
  AND REGEXP_LIKE(o.fips, '[0-9]{5}')
  AND o.temporal_window = '2023'
  AND m.geography_type = 'COUNTY_FIPS_5'
  AND m.temporal_grain = '2023'
UNION ALL
SELECT o.observation_id, o.measure_id, o.fips, 'COUNTY', o.fips,
       DATE '2025-01-01', DATE '2025-12-31', 'YEAR', o.value, o.value_state,
       m.unit, 'valid_source_supported_area_m2', NULL::VARCHAR,
       r.schema_version, r.release_id, o.source_key, s.label, s.vintage, s.source_url,
       o.retrieved_at, o.transformation_version, m.methodology,
       r.methodology_version, o.limitations, m.limitation, r.limitations,
       s.source_id, s.dataset_id, 'atlas-annual-nlcd-mrlc-local-county/1'
FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
JOIN PRESENTATION.SEMANTIC_RELEASES r
  ON r.release_id=p.current_release_id AND r.status='PUBLISHED'
JOIN PRESENTATION.SEMANTIC_OBSERVATIONS o ON o.release_id=r.release_id
JOIN PRESENTATION.SEMANTIC_MEASURES m
  ON m.release_id=r.release_id AND m.measure_id=o.measure_id
JOIN PRESENTATION.SEMANTIC_DATA_SOURCES s
  ON s.release_id=r.release_id AND s.source_key=o.source_key
WHERE p.pointer_key='ATLAS'
  AND r.source_manifest:nlcd_extension:contract_version::VARCHAR =
      'atlas-mrlc-nlcd-reviewed-cohort-extension/1'
  AND r.source_manifest:nlcd_extension:artifact_sha256::VARCHAR =
      'bdd2a4112769c894e069ae23021bb5a716313c3cfa821a7468aeaeebd2c451ee'
  AND r.source_manifest:nlcd_extension:row_count::INTEGER=14
  AND o.source_key='context_nlcd_2025'
  AND s.resource_key='mrlc_annual_nlcd_c1v2_2025_demo_cohort'
  AND s.source_id='mrlc_annual_nlcd_derived_county_aggregates'
  AND s.dataset_id='annual-nlcd-c1v2-2025-reviewed-demo-cohort'
  AND o.source_version_id=s.source_version_id
  AND o.ingestion_run_id=s.ingestion_run_id AND o.artifact_id=s.artifact_id
  AND o.source_version_id=r.source_manifest:nlcd_extension:source_version_id::VARCHAR
  AND o.ingestion_run_id=r.source_manifest:nlcd_extension:ingestion_run_id::VARCHAR
  AND o.artifact_id=r.source_manifest:nlcd_extension:artifact_id::VARCHAR
  AND o.fips IN ('09110','51013')
  AND o.temporal_window='2025' AND m.temporal_resolution='2025'
  AND o.geography_semantics='SELECTED_TIGER_2025_COUNTIES_AND_COUNTY_EQUIVALENTS'
  AND m.geography_semantics=o.geography_semantics
  AND o.transformation_version='atlas-annual-nlcd-mrlc-local-county/1'
  AND m.methodology=o.transformation_version
  AND o.value_state IN ('ZERO','OBSERVED') AND o.quality_state='COMPLETE'
  AND o.measure_id IN (
      'nlcd_forest_area_share_county_year','nlcd_developed_area_share_county_year',
      'nlcd_agriculture_area_share_county_year','nlcd_wetland_area_share_county_year',
      'nlcd_open_water_area_share_county_year','nlcd_mean_impervious_fraction_county_year',
      'nlcd_changed_area_share_county_year');