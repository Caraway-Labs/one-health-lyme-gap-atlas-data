-- DEV-only, one-time attachment. Before running, SHOW AUTHENTICATION POLICIES
-- ON USER OH_LYME_DEV_DATASET_DISCOVERY_SVC must resolve to BUILT-IN. If it
-- already resolves to the dedicated policy, skip this file. If it resolves to
-- another user or account policy, stop for security review. Snowflake rejects
-- re-attaching even the same policy, so replay must be decided by the preflight.
ALTER USER OH_LYME_DEV_DATASET_DISCOVERY_SVC SET AUTHENTICATION POLICY
  ONE_HEALTH_LYME_GAP_ATLAS_DEV.SECURITY.DATASET_DISCOVERY_SERVICE_AGENT_AUTH;
