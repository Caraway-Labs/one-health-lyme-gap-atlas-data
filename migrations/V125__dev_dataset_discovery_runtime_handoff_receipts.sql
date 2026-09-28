-- Data #450: bounded status read for the recommendation-side client.
-- DEV only. No governance DML or handoff procedure USAGE is granted.
USE DATABASE {{ DATABASE }};

GRANT SELECT ON VIEW DATASET_DISCOVERY.V_HANDOFF_RECEIPTS
  TO ROLE OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME;
