select
  payload,
  data_source_version_id,
  ingestion_run_id,
  artifact_id,
  source_record_id,
  publisher_updated_at,
  retrieved_at,
  snowflake_loaded_at,
  payload:fips::varchar as county_fips,
  payload:year::number as report_year,
  payload:case_status::varchar as case_status,
  payload:sex::varchar as sex,
  payload:age_cat_yrs::varchar as age_category_years,
  payload:frequency::number as frequency,
  coalesce(
    source_value_status,
    object_construct(
      'county_fips', iff(lower(payload:fips::varchar) in ('unknown', 'suppressed', 'not reported'), lower(payload:fips::varchar), null),
      'sex', iff(lower(payload:sex::varchar) in ('unknown', 'suppressed', 'not reported'), lower(payload:sex::varchar), null),
      'age_category_years', iff(lower(payload:age_cat_yrs::varchar) in ('unknown', 'suppressed', 'not reported'), lower(payload:age_cat_yrs::varchar), null)
    )
  ) as source_value_status
from {{ source('raw', 'cdc_lyme_x5j9_wybp') }} raw
where exists (
  select 1
  from {{ target.database }}.GOVERNANCE.DATA_SOURCE_VERSIONS version
  where version.data_source_version_id = raw.data_source_version_id
    and version.status in ('APPROVED', 'CONDITIONAL')
    and version.retired_at is null
)
