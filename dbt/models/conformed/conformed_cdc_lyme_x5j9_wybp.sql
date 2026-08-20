select
  source_record_id,
  payload,
  data_source_version_id,
  ingestion_run_id,
  artifact_id,
  'COUNTY_OF_RESIDENCE' as geography_semantics,
  '2022-current surveillance era; not comparable to prior eras without review' as caveat,
  retrieved_at
from {{ ref('stg_cdc_lyme_x5j9_wybp') }}
