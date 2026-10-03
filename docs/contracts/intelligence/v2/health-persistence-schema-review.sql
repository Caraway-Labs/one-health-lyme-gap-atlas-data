-- UNAPPLIED, UNNUMBERED REVIEW TEMPLATE. Parent reserves migration/deployment.
-- No source activation, notification threshold, owner policy or new platform.
CREATE TABLE GOVERNANCE.INTELLIGENCE_SOURCE_HEALTH_HISTORY (
    SOURCE_ID VARCHAR(200) NOT NULL,
    REGISTRY_VERSION NUMBER(38,0) NOT NULL,
    GENERATION NUMBER(38,0) NOT NULL,
    HISTORY_SHA256 VARCHAR(64) NOT NULL,
    HISTORY VARIANT NOT NULL,
    REGISTERED_AT TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
-- Contains finite health document, revision hashes, processed attempt hashes and
-- acquisition-failure barrier. No publisher text, URLs, XML, email or raw body.
-- Append-only; serialization/uniqueness uses the existing V135 write guard.
-- Proposed intended runtime: SELECT/INSERT only plus existing guard access.
-- API read projection and its reader grants require separate review/readback.
-- Do not give API access to private revision/attempt history or runtime writes.
