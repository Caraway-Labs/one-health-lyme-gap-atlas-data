USE DATABASE {{ DATABASE }};

-- Snowflake validates the approval branch at procedure execution time. The
-- owner needs the matching read privilege in addition to the V005 write grant.
GRANT SELECT ON TABLE GOVERNANCE.DATA_SOURCE_VERSIONS
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
