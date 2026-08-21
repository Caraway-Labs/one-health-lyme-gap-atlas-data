USE DATABASE {{ DATABASE }};

-- Streamlit ownership cannot be transferred by this Snowflake account. The
-- designated DEV deployer therefore creates the app directly under its owner role.
GRANT ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER TO USER MATTHEWCARAWAY;
