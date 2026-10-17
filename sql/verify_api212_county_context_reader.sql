-- Postdeployment, read-only acceptance using named ATLAS_PROD_READ / COMPUTE_WH.
-- Run identity alone first; stop unless role/database/warehouse match the handoff.
SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE();

SELECT release_id,bundle_sha256 FROM PRESENTATION.CURRENT_RELEASE_V LIMIT 1;

SELECT measure_id,county_fips,value,value_state,unit,denominator,source_id,dataset_id,
       source_vintage,source_url,retrieved_at,source_published_at,release_version,
       semantic_contract_version,semantic_version,metadata_revision_id,
       metadata_methodology_version,transformation_version,period_start,period_end,
       temporal_grain,vintage_year,value_type,category_label,source_field,
       definition,allowed_value_states,context_limitations,
       observation_limitations,release_limitations
FROM PRESENTATION.CURRENT_COUNTY_OBSERVATIONS_V
WHERE county_fips IN ('01001','08001')
  AND measure_id IN ('population_2022','svi_percentile_2022','uninsured_percent_2022',
                     'uninsured_percentile_2022','rucc_2023')
ORDER BY measure_id,county_fips LIMIT 10;

SELECT LAST_QUERY_ID() AS context_read_query_id;

SELECT fips,population,svi_percentile,uninsured_percent,uninsured_percentile,rucc_2023
FROM PRESENTATION.CURRENT_COUNTY_ATLAS_V
WHERE fips IN ('01001','08001') ORDER BY fips LIMIT 2;

SELECT measure_id,county_fips,value,value_state
FROM PRESENTATION.CURRENT_COUNTY_OBSERVATIONS_V
WHERE (county_fips='49029' AND measure_id='svi_percentile_2022')
   OR (county_fips='48301' AND measure_id IN
       ('uninsured_percent_2022','uninsured_percentile_2022'))
ORDER BY measure_id,county_fips LIMIT 3;

SELECT measure_id,county_fips,value,value_state,period_start,period_end,temporal_grain
FROM PRESENTATION.CURRENT_COUNTY_OBSERVATIONS_V
WHERE county_fips IN ('01001','09110','51013')
  AND (source_key='human' OR source_key='context_nlcd_2025')
ORDER BY measure_id,county_fips LIMIT 23;

SELECT measure_id,county_fips,value,value_state,period_start,period_end,unit
FROM PRESENTATION.CURRENT_CLIMATE_COUNTY_DAY_OBSERVATIONS_V
WHERE county_fips IN ('48277','02013')
  AND period_start=DATE '2025-01-17' AND period_end=DATE '2025-01-17'
ORDER BY measure_id,county_fips LIMIT 8;
