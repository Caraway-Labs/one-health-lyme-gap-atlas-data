USE DATABASE {{ DATABASE }};

-- Repair the DEV catalog parent relation when a previously applied V001 ledger
-- is incomplete.  This is idempotent and limited to the CDC x5j9-wybp parent.
CREATE TABLE IF NOT EXISTS GOVERNANCE.CATALOG_DATASETS (
  catalog_dataset_id VARCHAR PRIMARY KEY,
  dataset_key VARCHAR NOT NULL,
  catalog_name VARCHAR NOT NULL,
  catalog_record_id VARCHAR,
  metadata_payload VARIANT,
  metadata_sha256 VARCHAR(64),
  discovered_at TIMESTAMP_LTZ NOT NULL,
  is_current BOOLEAN NOT NULL
);

-- Preserve the exact parent identifier referenced by the surviving resource.
-- Do not fabricate a catalog-artifact digest: a null digest deliberately keeps
-- approval and pipeline eligibility blocked until a controlled evidence refresh.
INSERT INTO GOVERNANCE.CATALOG_DATASETS (
  catalog_dataset_id, dataset_key, catalog_name, catalog_record_id,
  metadata_payload, metadata_sha256, discovered_at, is_current
)
SELECT r.catalog_dataset_id, r.resource_key, 'CDC_SOCRATA', 'x5j9-wybp',
       OBJECT_CONSTRUCT(
         'recovery_status', 'RECONSTRUCTED_FROM_PRESERVED_RESOURCE_PAYLOAD',
         'recovered_at', CURRENT_TIMESTAMP(),
         'canonical_source_url', r.canonical_source_url,
         'api_dataset_id', r.api_dataset_id,
         'source_resource_payload', r.resource_payload
       ),
       NULL, r.registered_at, TRUE
FROM GOVERNANCE.CATALOG_RESOURCES r
WHERE r.resource_key = 'cdc_lyme_x5j9_wybp'
  AND r.is_active = TRUE
  AND NOT EXISTS (
    SELECT 1 FROM GOVERNANCE.CATALOG_DATASETS d
    WHERE d.catalog_dataset_id = r.catalog_dataset_id
  );

-- V016's owner-rights approval views join CATALOG_DATASETS for catalog-level
-- evidence.  Views require direct access to every underlying table at runtime.
GRANT SELECT ON TABLE GOVERNANCE.CATALOG_DATASETS
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
