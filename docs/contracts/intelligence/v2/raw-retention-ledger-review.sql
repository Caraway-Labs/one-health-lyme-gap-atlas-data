-- UNAPPLIED REVIEW TEMPLATE. Not a numbered migration or executable rollout.
-- Parent must allocate migration/schema/least-privilege owner and deployment
-- slot. Select the suffixed DEV or PROD database explicitly; never Alpha POC.
-- No raw XML/HTML, base64 payload, credentials or metadata deletion here.
-- Snowflake standard-table constraints are not concurrency/uniqueness guards.
-- A reviewed owner-rights operation must validate authority and serialize claim
-- registration, reads and cleanup; runtime receives procedure USAGE only.

CREATE TABLE GOVERNANCE.INTELLIGENCE_RAW_CAPTURE_LEASES (
    LEASE_SHA256 VARCHAR(64) NOT NULL,
    SOURCE_ID VARCHAR(128) NOT NULL,
    REGISTRY_VERSION NUMBER(38, 0) NOT NULL,
    SOURCE_SHA256 VARCHAR(64) NOT NULL,
    CAPTURE_ID VARCHAR(128) NOT NULL,
    ARTIFACT_SHA256 VARCHAR(64) NOT NULL,
    CAPTURED_AT TIMESTAMP_TZ NOT NULL,
    EXPIRES_AT TIMESTAMP_TZ NOT NULL,
    POLICY_REF VARCHAR(128) NOT NULL,
    POLICY_VERSION VARCHAR(64) NOT NULL,
    SUCCESSFUL_FETCH_RECEIPT_SHA256 VARCHAR(64) NOT NULL,
    REGISTERED_AT TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE GOVERNANCE.INTELLIGENCE_RAW_COPY_CLAIMS (
    COPY_SHA256 VARCHAR(64) NOT NULL,
    ENVIRONMENT VARCHAR(4) NOT NULL,
    SOURCE_ID VARCHAR(128) NOT NULL,
    COPY_KIND VARCHAR(32) NOT NULL,
    PRIVATE_LOCATOR VARCHAR(2048) NOT NULL,
    LEASE_SHA256 VARCHAR(64) NOT NULL,
    REGISTERED_AT TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_AUDIT (
    RECEIPT_SHA256 VARCHAR(64) NOT NULL,
    PLAN_SHA256 VARCHAR(64) NOT NULL,
    COPY_SHA256 VARCHAR(64) NOT NULL,
    OUTCOME VARCHAR(32) NOT NULL,
    ATTEMPTED_AT TIMESTAMP_TZ NOT NULL,
    REGISTERED_AT TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);

-- Review requirements before forward-only migration/procedure implementation:
-- 1. Immutable authorized 200-fetch receipt establishes captured_at once;
--    expires_at must equal DATEADD(day,30,captured_at). 304/retry uses old lease.
-- 2. Claim is committed BEFORE the corresponding raw copy is written.
-- 3. Metadata-only lookup refuses expired/denied reads BEFORE selecting payload
--    from INGESTION_RUN_PAYLOADS or reading any object/local/cache/replay bytes.
-- 4. Scoped purge removes raw transport only; append-only source/capture/item
--    and normalized provenance remain. No direct broad DELETE to runtime.
-- 5. Latest claim/inventory is checked under the same serialization guard as
--    physical cleanup, including claims outside the chosen source allowlist.
-- 6. Approved exact plan hash and durable audit intent precede every deletion.
--    Existing XML checkpoint rows without valid immutable lease fail closed;
--    no guessed/fabricated backfill capture timestamps or generic retention.
-- 7. An object-store crash between deletion/outcome is retried idempotently;
--    warehouse/local payload scrub must not restore XML from another copy.
-- 8. No public projection includes private locators or policy/approval receipts.
