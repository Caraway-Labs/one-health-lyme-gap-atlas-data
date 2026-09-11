{{ config(enabled=(target.database in ['ONE_HEALTH_LYME_GAP_ATLAS_DEV', 'ONE_HEALTH_LYME_GAP_ATLAS_PROD']),
          alias='CDC_LYME_HISTORICAL_CANDIDATE', schema='STAGING', copy_grants=true) }}
select source_record_id, payload, data_source_version_id, ingestion_run_id, artifact_id,
  county_fips, report_year, case_status, sex, age_category_years, frequency,
  source_value_status, 'COUNTY_OF_RESIDENCE' as geography_semantics,
  'COUNTY_YEAR_CASE_STATUS_SEX_AGE' as source_resolution,
  'ANNUAL_SURVEILLANCE_YEAR' as temporal_window,
  '2008-2021 surveillance era; county of residence, not exposure; reported cases are not infection incidence; no direct comparison with 2022 onward without reviewed methodology' as caveat,
  retrieved_at
from {{ ref('stg_cdc_lyme_qtbi_xd4i') }}
