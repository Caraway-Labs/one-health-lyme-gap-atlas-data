USE DATABASE {{ DATABASE }};

-- The dedicated owner may replace only the approval procedure that it owns.
-- This is required by Snowflake for CREATE OR REPLACE PROCEDURE and is not a
-- grant to create unrelated schemas, tables, roles, or warehouses.
GRANT CREATE PROCEDURE ON SCHEMA GOVERNANCE
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
