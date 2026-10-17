-- API212: extend V138 without rewriting history or granting private-table access.
-- Source-bound admission; #191 INTERNAL envelopes remain unchanged.
USE DATABASE {{ DATABASE }};
CREATE OR REPLACE VIEW PRESENTATION.CURRENT_COUNTY_OBSERVATIONS_V COPY GRANTS AS
WITH context AS (
WITH reviewed(measure_id, semantic_version, metadata_revision_id, source_field, unit,
              denominator, value_type, definition, allowed_states_json, limitations_json,
              source_version_id) AS (
    SELECT * FROM VALUES
    ('population_2022', '1.0.0', 'metadata-revision:v1:b848914c705a99dcfe37ce9d638a6f6a939118fbc5662a6bc56a21e9226c669c', 'E_TOTPOP', 'people', 'NONE', 'integer', 'County total population estimate reported in E_TOTPOP for the 2022 SVI product''s 2018-2022 ACS period.', '["OBSERVED","ZERO","MISSING"]', '[{"category":"INTERPRETATION","code":"context_only","text":"An estimate of county population, not an uninsured count or a direct measure of Lyme disease risk."}]', 'b8b6bf61-c6a3-4538-b0df-1b88c61720b1'),
    ('svi_percentile_2022', '1.0.0', 'metadata-revision:v1:144b7fecaa83ed51d17ff78b9794607252837a4a90ec1d9cfae2ca6b25ab5ccf', 'RPL_THEMES', 'percentile', 'NONE', 'number', 'Overall county Social Vulnerability Index percentile reported in RPL_THEMES for the 2022 SVI product.', '["OBSERVED","ZERO","MISSING"]', '[{"category":"INTERPRETATION","code":"context_only","text":"National county percentile rank for this product and vintage; not a percentage of people, causal driver, or individual risk."},{"category":"DENOMINATOR","code":"national_county_reference","text":"This is a national county rank in the 2022 SVI product, not a person denominator."}]', 'b8b6bf61-c6a3-4538-b0df-1b88c61720b1'),
    ('uninsured_percentile_2022', '1.0.0', 'metadata-revision:v1:93ec76b97a9d485f6117487f3454bb81dff23f2df2f7d656cb3fe1892b571e53', 'EPL_UNINSUR', 'percentile', 'NONE', 'number', 'County percentile rank of the uninsured percentage reported in EPL_UNINSUR for the 2022 SVI product.', '["OBSERVED","ZERO","MISSING"]', '[{"category":"INTERPRETATION","code":"context_only","text":"National county percentile rank of EP_UNINSUR; not an uninsured population percentage or individual risk."},{"category":"DENOMINATOR","code":"national_county_reference","text":"This is a national county rank in the 2022 SVI product, not a person denominator."}]', 'b8b6bf61-c6a3-4538-b0df-1b88c61720b1'),
    ('uninsured_percent_2022', '1.0.0', 'metadata-revision:v1:9a8ee29874e817ac83aade33b313bcd33f54eeaf3daf9962ae37e31980fbb14b', 'EP_UNINSUR', 'percent', 'civilian_noninstitutionalized_population', 'number', 'County percentage of the civilian noninstitutionalized population that is uninsured, reported in EP_UNINSUR for the 2022 SVI product.', '["OBSERVED","ZERO","MISSING"]', '[{"category":"INTERPRETATION","code":"context_only","text":"The denominator is the civilian noninstitutionalized population, not E_TOTPOP; this percentage does not establish individual risk."},{"category":"DENOMINATOR","code":"civilian_noninstitutionalized","text":"EP_UNINSUR uses the civilian noninstitutionalized population; E_TOTPOP is not its denominator."}]', 'b8b6bf61-c6a3-4538-b0df-1b88c61720b1'),
    ('rucc_2023', '2.0.0', 'metadata-revision:v1:cc303005813febd67830aea1e4d1cec3042e4cab442234dec36da283f98f010b', 'RUCC_2023', 'code', 'NONE', 'integer', 'USDA ERS 2023 Rural-Urban Continuum Code category from the RUCC_2023 source attribute for a county.', '["OBSERVED"]', '[{"category":"INTERPRETATION","code":"context_only","text":"Codes 1-9 are vintage-specific categories, not ordered distances, annual observations, causal drivers, or individual risk."},{"category":"SOURCE","code":"rucc_2023_codebook","text":"2023 codes 1-3 are metro population bands; 4-9 are nonmetro urban-population and adjacency categories. The urban threshold changed from 2,500 to 5,000; do not substitute an older vintage."},{"category":"INTERPRETATION","code":"vintage_year_not_observation_date","text":"The 2023 vintage is a publisher classification year, not a known exact observation day or an annual rate."}]', '87872b36-93ab-4a34-b70e-29569192cb48')
), sources(source_key, source_id, dataset_id, resource_key, source_version_id,
           ingestion_run_id, artifact_id, temporal_window, transformation_version) AS (
    SELECT * FROM VALUES
    ('context_svi', 'cdc_atsdr_svi', 'atsdr-svi-2022-county-layer',
     'cdc_atsdr_svi_2022_county', 'b8b6bf61-c6a3-4538-b0df-1b88c61720b1',
     '331f367d-9282-4936-9b49-a480db995016',
     'cdc_atsdr_svi_2022_county:dc042342a2e5abc108af67b439ec04c8',
     '2022 (2018-2022 ACS)', 'svi_numeric_projection_v2'),
    ('context_rucc', 'usda_ers', 'rural-urban-continuum-codes-2023',
     'usda_ers_rucc_2023', '87872b36-93ab-4a34-b70e-29569192cb48',
     'f65bd68a-27de-4ad4-81a5-424ee24af3b6',
     'usda_ers_rucc_2023:ec455ee2a8bc5fc8e070575ea5bee7dc',
     '2023', 'semantic_county_assembly_v1')
), codebook(code, label) AS (
    SELECT * FROM VALUES
    (1, 'Metro: area population at least 1 million'),
    (2, 'Metro: area population 250,000 to 1 million'),
    (3, 'Metro: area population below 250,000'),
    (4, 'Nonmetro: urban population at least 20,000; adjacent'),
    (5, 'Nonmetro: urban population at least 20,000; nonadjacent'),
    (6, 'Nonmetro: urban population 5,000 to 20,000; adjacent'),
    (7, 'Nonmetro: urban population 5,000 to 20,000; nonadjacent'),
    (8, 'Nonmetro: urban population below 5,000; adjacent'),
    (9, 'Nonmetro: urban population below 5,000; nonadjacent')
)
SELECT o.observation_id, o.measure_id, o.fips AS geography_id,
       'COUNTY' AS geography_type, o.fips AS county_fips,
       IFF(m.source_field='RUCC_2023', NULL, DATE '2018-01-01') AS period_start,
       IFF(m.source_field='RUCC_2023', NULL, DATE '2022-12-31') AS period_end,
       IFF(m.source_field='RUCC_2023', 'VINTAGE_YEAR', 'PERIOD') AS temporal_grain,
       o.value, o.value_state, m.unit, m.denominator,
       NULL::VARCHAR AS supported_stratifications,
       r.schema_version AS semantic_contract_version, r.release_id AS release_version,
       o.source_key, s.label AS source_label, s.vintage AS source_vintage, s.source_url,
       o.retrieved_at, o.transformation_version, m.definition AS methodology,
       r.methodology_version AS release_methodology_version,
       o.limitations AS observation_limitations,
       NULL::VARCHAR AS measure_limitation, r.limitations AS release_limitations,
       s.source_id, s.dataset_id, NULL::VARCHAR AS methodology_id,
       m.semantic_version, m.metadata_revision_id,
       'semantic-1.0.0' AS metadata_methodology_version,
       IFF(m.source_field='RUCC_2023', 2023, 2022)::INTEGER AS vintage_year,
       m.value_type, cb.label AS category_label, m.source_field, m.definition,
       PARSE_JSON(m.allowed_states_json) AS allowed_value_states,
       PARSE_JSON(m.limitations_json) AS context_limitations,
       NULL::TIMESTAMP_LTZ AS source_published_at,
       'atlas-county-context-consumer/1' AS context_contract_version
FROM PRESENTATION.SEMANTIC_RELEASE_POINTER p
JOIN PRESENTATION.SEMANTIC_RELEASES r
  ON r.release_id=p.current_release_id AND r.status='PUBLISHED'
JOIN PRESENTATION.SEMANTIC_OBSERVATIONS o ON o.release_id=r.release_id
JOIN reviewed m ON m.measure_id=o.measure_id AND m.source_version_id=o.source_version_id
JOIN sources a ON a.source_version_id=o.source_version_id
JOIN PRESENTATION.SEMANTIC_DATA_SOURCES s
  ON s.release_id=r.release_id AND s.source_key=o.source_key
 AND s.source_key=a.source_key AND s.source_id=a.source_id AND s.dataset_id=a.dataset_id
 AND s.resource_key=a.resource_key AND s.source_version_id=a.source_version_id
 AND s.ingestion_run_id=a.ingestion_run_id AND s.artifact_id=a.artifact_id
JOIN PRESENTATION.SEMANTIC_COUNTY_ATLAS c ON c.release_id=r.release_id AND c.fips=o.fips
LEFT JOIN codebook cb ON m.source_field='RUCC_2023' AND o.value=TO_VARIANT(cb.code)
WHERE p.pointer_key='ATLAS'
  AND r.release_id='governed-2026-10-15-january-climate-prod'
  AND r.bundle_sha256='53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d'
  AND o.source_key=a.source_key AND o.ingestion_run_id=a.ingestion_run_id
  AND o.artifact_id=a.artifact_id AND o.temporal_window=a.temporal_window
  AND o.transformation_version=a.transformation_version
  AND o.geography_semantics='COUNTY_FIPS_5' AND REGEXP_LIKE(o.fips, '[0-9]{5}')
  AND o.quality_state='PASSED' AND s.vintage=o.temporal_window
  AND NULLIF(o.source_record_id, '') IS NOT NULL
  AND REGEXP_LIKE(o.source_row_hash, '[0-9a-f]{64}')
  AND ((m.source_field='RUCC_2023' AND o.value_state='OBSERVED' AND TYPEOF(o.value) IN ('INTEGER', 'DECIMAL', 'DOUBLE')
        AND cb.code IS NOT NULL)
    OR (m.source_field<>'RUCC_2023' AND (
       (o.value_state='MISSING' AND (o.value IS NULL OR IS_NULL_VALUE(o.value)))
       OR (TYPEOF(o.value) IN ('INTEGER', 'DECIMAL', 'DOUBLE')
           AND ((o.value_state='ZERO' AND o.value=TO_VARIANT(0))
             OR (o.value_state='OBSERVED' AND o.value::DOUBLE>0))
           AND ((m.source_field='E_TOTPOP' AND TYPEOF(o.value)='INTEGER'
                 AND o.value::DOUBLE=TRUNC(o.value::DOUBLE))
             OR (m.unit='percentile' AND o.value::DOUBLE BETWEEN 0 AND 1)
             OR (m.unit='percent' AND o.value::DOUBLE BETWEEN 0 AND 100))))))
QUALIFY COUNT(*) OVER (PARTITION BY o.release_id,o.measure_id,o.fips)=1
), existing AS (
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
      'nlcd_changed_area_share_county_year')
)
SELECT existing.*, NULL::VARCHAR AS semantic_version, NULL::VARCHAR AS metadata_revision_id,
       NULL::VARCHAR AS metadata_methodology_version,
       NULL::INTEGER AS vintage_year, NULL::VARCHAR AS value_type,
       NULL::VARCHAR AS category_label, NULL::VARCHAR AS source_field,
       NULL::VARCHAR AS definition, NULL::VARIANT AS allowed_value_states,
       NULL::VARIANT AS context_limitations, NULL::TIMESTAMP_LTZ AS source_published_at,
       NULL::VARCHAR AS context_contract_version FROM existing
UNION ALL
SELECT * FROM context;
