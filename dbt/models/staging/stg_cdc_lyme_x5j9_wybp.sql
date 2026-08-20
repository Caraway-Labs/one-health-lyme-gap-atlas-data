select
  payload,
  data_source_version_id,
  ingestion_run_id,
  artifact_id,
  source_record_id,
  publisher_updated_at,
  retrieved_at,
  snowflake_loaded_at
from {{ source('raw', 'cdc_lyme_x5j9_wybp') }}
