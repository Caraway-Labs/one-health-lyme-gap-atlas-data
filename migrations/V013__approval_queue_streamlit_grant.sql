USE DATABASE {{ DATABASE }};

-- CREATE OR REPLACE VIEW resets the prior direct grant. Restore the approval
-- app owner's read access after V012 replaces its queue view.
GRANT SELECT ON VIEW GOVERNANCE.V_SOURCE_APPROVAL_QUEUE
  TO ROLE OH_LYME_{{ ENV }}_STREAMLIT_OWNER;
