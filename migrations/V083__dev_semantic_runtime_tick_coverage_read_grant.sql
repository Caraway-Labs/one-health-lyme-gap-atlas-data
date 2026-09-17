-- DEV-only semantic builder needs the approved classification aggregate, not source records.
USE DATABASE {{ DATABASE }};

GRANT SELECT ON TABLE GOVERNANCE.EVIDENCE_ONLY_SOURCE_COVERAGE_CLASSIFICATIONS
    TO ROLE OH_LYME_DEV_RUNTIME;
