USE DATABASE {{ DATABASE }};

-- V016's owner-rights approval views join CATALOG_DATASETS for catalog-level
-- evidence.  Views require the Streamlit owner to have direct access to every
-- underlying table at runtime; keep this read grant narrowly scoped.
GRANT SELECT ON TABLE GOVERNANCE.CATALOG_DATASETS
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
