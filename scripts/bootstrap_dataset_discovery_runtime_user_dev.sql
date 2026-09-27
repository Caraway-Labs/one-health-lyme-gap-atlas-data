-- Account-level, DEV-only identity bootstrap for ADR 0041. Run with the
-- explicitly authorized administrative connection after identity preflight.
-- This does not create a token or place credential material in Snowflake DDL.
-- The service user receives exactly the Dataset Discovery runtime role.

CREATE USER IF NOT EXISTS OH_LYME_DEV_DATASET_DISCOVERY_SVC
  TYPE = SERVICE_AGENT
  DEFAULT_ROLE = OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME
  DEFAULT_WAREHOUSE = OH_LYME_DEV_INGEST_XS_WH
  DEFAULT_NAMESPACE = ONE_HEALTH_LYME_GAP_ATLAS_DEV.DATASET_DISCOVERY
  COMMENT = 'DEV Dataset Discovery recommendation runtime only';

GRANT ROLE OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME
  TO USER OH_LYME_DEV_DATASET_DISCOVERY_SVC;

-- Reconcile an existing DEV-only SERVICE principal created before the
-- SERVICE_AGENT decision. This user remains non-interactive and agent-active.
ALTER USER OH_LYME_DEV_DATASET_DISCOVERY_SVC SET TYPE = SERVICE_AGENT;

-- This dedicated policy changes only the Dataset Discovery DEV user. A future
-- network policy attached to that user is still enforced during authentication.
CREATE SCHEMA IF NOT EXISTS ONE_HEALTH_LYME_GAP_ATLAS_DEV.SECURITY;
CREATE AUTHENTICATION POLICY IF NOT EXISTS
  ONE_HEALTH_LYME_GAP_ATLAS_DEV.SECURITY.DATASET_DISCOVERY_SERVICE_AGENT_AUTH
  AUTHENTICATION_METHODS = ('PROGRAMMATIC_ACCESS_TOKEN')
  PAT_POLICY = (
    NETWORK_POLICY_EVALUATION = ENFORCED_NOT_REQUIRED
    REQUIRE_ROLE_RESTRICTION_FOR_SERVICE_USERS = TRUE
  )
  COMMENT = 'DEV-only auth policy for Atlas Dataset Discovery SERVICE_AGENT';
-- Attach with the separate one-time reviewed script only after confirming
-- SHOW AUTHENTICATION POLICIES ON USER resolves to BUILT-IN, not another policy.
