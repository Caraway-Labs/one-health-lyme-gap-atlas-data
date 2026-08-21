select
  source_record_id,
  payload,
  data_source_version_id,
  ingestion_run_id,
  artifact_id,
  county_fips,
  report_year,
  case_status,
  sex,
  age_category_years,
  frequency,
  source_value_status,
  'COUNTY_OF_RESIDENCE' as geography_semantics,
  'COUNTY_YEAR_CASE_STATUS_SEX_AGE' as source_resolution,
  'ANNUAL_SURVEILLANCE_YEAR' as temporal_window,
  '2022-current surveillance era; not comparable to prior eras without review' as caveat,
  retrieved_at
from {{ ref('stg_cdc_lyme_x5j9_wybp') }}
