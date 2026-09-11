-- DEV-only grant repair for the existing owner-rights Streamlit approval app.
-- The app reads only this redacted review queue; it retains no direct table access.
USE DATABASE {{ DATABASE }};

GRANT SELECT ON VIEW GOVERNANCE.V_KG_PAPER_REVIEW_QUEUE
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
