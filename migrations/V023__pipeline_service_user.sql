USE DATABASE {{ DATABASE }};

-- Provision the non-human principal used by the DigitalOcean worker. Its
-- encrypted key-pair is deliberately not stored in source control; the public
-- key is registered in a separate protected deployment step.
CREATE USER IF NOT EXISTS OH_LYME_{{ ENV }}_PIPELINE_SVC
  TYPE = SERVICE
  DEFAULT_ROLE = OH_LYME_{{ ENV }}_PIPELINE_RUNTIME
  DEFAULT_WAREHOUSE = OH_LYME_{{ ENV }}_INGEST_XS_WH
  DEFAULT_NAMESPACE = {{ DATABASE }}.GOVERNANCE
  COMMENT = 'DigitalOcean governed pipeline worker; key-pair authentication only';
GRANT ROLE OH_LYME_{{ ENV }}_PIPELINE_RUNTIME
  TO USER OH_LYME_{{ ENV }}_PIPELINE_SVC;
