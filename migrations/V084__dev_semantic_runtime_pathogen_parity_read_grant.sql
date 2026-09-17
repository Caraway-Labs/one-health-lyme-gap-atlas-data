-- DEV-only semantic builder needs the approved pathogen parity aggregate, not restricted rows.
USE DATABASE {{ DATABASE }};

GRANT SELECT ON TABLE GOVERNANCE.RESTRICTED_PATHOGEN_PARITY_CLASSIFICATIONS
    TO ROLE OH_LYME_DEV_RUNTIME;
