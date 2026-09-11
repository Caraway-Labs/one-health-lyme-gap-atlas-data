{{ config(enabled=(target.database in ['ONE_HEALTH_LYME_GAP_ATLAS_DEV', 'ONE_HEALTH_LYME_GAP_ATLAS_PROD'])) }}
select
  raw.payload, raw.data_source_version_id, raw.ingestion_run_id, raw.artifact_id,
  raw.source_record_id, raw.retrieved_at,
  payload:fips::varchar as county_fips,
  try_to_number(payload:year::varchar) as report_year,
  payload:case_status::varchar as case_status,
  payload:sex::varchar as sex,
  payload:age_cat_yrs::varchar as age_category_years,
  try_to_number(payload:frequency::varchar) as frequency,
  object_construct(
  {% for source, dest in [('fips','county_fips'),('sex','sex'),('case_status','case_status'),('age_cat_yrs','age_category_years'),('frequency','frequency')] %}
    '{{ dest }}', case
      when payload:{{ source }} is null then 'missing'
      when is_null_value(payload:{{ source }}) then 'null'
      when lower(payload:{{ source }}::varchar) in ('unknown','suppressed','not reported')
        then lower(payload:{{ source }}::varchar)
      when payload:{{ source }}::varchar = '0' then 'zero'
      else 'observed' end{% if not loop.last %},{% endif %}
  {% endfor %}
  ) as source_value_status
from {{ source('raw', 'cdc_lyme_qtbi_xd4i') }} raw
where exists (
  select 1 from {{ target.database }}.GOVERNANCE.DATA_SOURCE_VERSIONS version
  where version.data_source_version_id=raw.data_source_version_id
    and version.resource_key='cdc_lyme_qtbi_xd4i'
    and version.status='APPROVED' and version.retired_at is null
)
