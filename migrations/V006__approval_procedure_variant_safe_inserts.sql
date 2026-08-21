USE DATABASE {{ DATABASE }};

-- The procedure is owned by the dedicated Streamlit owner role. Give that
-- deployment identity the migration-ledger access it needs before V007
-- replaces the procedure under its own role.
GRANT SELECT, INSERT ON TABLE GOVERNANCE.SCHEMA_MIGRATIONS
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
