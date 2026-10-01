-- DATA #135: publication-grain storage; never county observations.
-- Source-version rows are human-managed reviewed registry records. Runtime may
-- read them but cannot create, approve, modify or delete them.
USE DATABASE {{ DATABASE }};

-- Every writer updates this migrator-created singleton before checking keys.
-- The UPDATE resource lock lasts through COMMIT/ROLLBACK; INSERT alone would
-- not serialize competing writers on ordinary Snowflake tables.
CREATE TABLE IF NOT EXISTS GOVERNANCE.INTELLIGENCE_WRITE_GUARD (
    guard_id NUMBER NOT NULL,
    write_sequence NUMBER NOT NULL,
    PRIMARY KEY (guard_id)
);
INSERT INTO GOVERNANCE.INTELLIGENCE_WRITE_GUARD (guard_id, write_sequence)
SELECT 1, 0 WHERE NOT EXISTS (
    SELECT 1 FROM GOVERNANCE.INTELLIGENCE_WRITE_GUARD WHERE guard_id = 1
);

CREATE TABLE IF NOT EXISTS GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS (
    source_id VARCHAR(200) NOT NULL,
    registry_version NUMBER NOT NULL,
    registry_sha256 VARCHAR(64) NOT NULL,
    registry_document VARIANT NOT NULL,
    recorded_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (source_id, registry_version)
);

CREATE TABLE IF NOT EXISTS CONFORMED.INTELLIGENCE_ITEM_REVISIONS (
    item_id VARCHAR(64) NOT NULL,
    revision_id VARCHAR(64) NOT NULL,
    content_sha256 VARCHAR(64) NOT NULL,
    content_document VARIANT NOT NULL,
    recorded_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (item_id, revision_id)
);

-- Run-pinned captures keep publisher conflicts and each transport/source
-- attribution. Repeat polls retain new fetch/run/artifact evidence, not new
-- publication or content-revision timestamps.
CREATE TABLE IF NOT EXISTS GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES (
    capture_id VARCHAR(64) NOT NULL,
    item_id VARCHAR(64) NOT NULL,
    revision_id VARCHAR(64) NOT NULL,
    source_id VARCHAR(200) NOT NULL,
    registry_version NUMBER NOT NULL,
    transport VARCHAR(10) NOT NULL,
    ingestion_run_id VARCHAR NOT NULL,
    artifact_id VARCHAR NOT NULL,
    artifact_sha256 VARCHAR(64) NOT NULL,
    item_sha256 VARCHAR(64) NOT NULL,
    item_document VARIANT NOT NULL,
    retrieved_at TIMESTAMP_LTZ NOT NULL,
    recorded_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (capture_id)
);

-- Existing runtime identities receive only the exact required table operations.
-- Ordinary Snowflake PK/FK declarations do not enforce uniqueness or lineage;
-- the bounded writer verifies both inside its transaction.
GRANT SELECT ON TABLE GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS
    TO ROLE OH_LYME_{{ ENV }}_RUNTIME;
GRANT SELECT, UPDATE ON TABLE GOVERNANCE.INTELLIGENCE_WRITE_GUARD
    TO ROLE OH_LYME_{{ ENV }}_RUNTIME;
GRANT SELECT, INSERT ON TABLE CONFORMED.INTELLIGENCE_ITEM_REVISIONS
    TO ROLE OH_LYME_{{ ENV }}_RUNTIME;
GRANT SELECT, INSERT ON TABLE GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES
    TO ROLE OH_LYME_{{ ENV }}_RUNTIME;

-- Keep every source and revision. This projection does not decide which
-- conflicting publisher revision is authoritative from arrival time.
CREATE VIEW IF NOT EXISTS PRESENTATION.INTELLIGENCE_FEED_V AS
SELECT c.item_id, c.revision_id, c.source_id, c.registry_version, c.transport,
       c.item_id AS deduplication_key,
       c.item_document:content_sha256::VARCHAR AS content_sha256,
       c.item_document:transport_identity_sha256::VARCHAR AS transport_identity_sha256,
       IFF(IS_NULL_VALUE(c.item_document:canonical_url), NULL,
           c.item_document:canonical_url::VARCHAR) AS canonical_url,
       IFF(IS_NULL_VALUE(c.item_document:title), NULL,
           c.item_document:title::VARCHAR) AS title,
       IFF(IS_NULL_VALUE(c.item_document:published_at), NULL,
           c.item_document:published_at::VARCHAR) AS published_at,
       IFF(IS_NULL_VALUE(c.item_document:updated_at), NULL,
           c.item_document:updated_at::VARCHAR) AS updated_at,
       IFF(IS_NULL_VALUE(c.item_document:event_at), NULL,
           c.item_document:event_at::VARCHAR) AS event_at,
       c.item_document:fetched_at::VARCHAR AS fetched_at,
       IFF(IS_NULL_VALUE(c.item_document:excerpt), NULL,
           c.item_document:excerpt::VARCHAR) AS excerpt,
       c.item_document:field_states AS field_states,
       c.item_document:geographies AS geographies,
       c.item_document:topics AS topics,
       c.item_document:provenance AS provenance,
       c.item_document:limitations AS limitations,
       c.item_document:contract_version::VARCHAR AS contract_version,
       c.item_document:content_is_untrusted::BOOLEAN AS content_is_untrusted,
       s.registry_document:organization::VARCHAR AS organization,
       s.registry_document:trust_classification::VARCHAR AS reviewed_trust_classification
FROM GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES c
JOIN CONFORMED.INTELLIGENCE_ITEM_REVISIONS r
  ON r.item_id = c.item_id AND r.revision_id = c.revision_id
JOIN GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS s
  ON s.source_id = c.source_id AND s.registry_version = c.registry_version
WHERE s.registry_document:approval:status::VARCHAR = 'approved'
  AND s.registry_document:trust_review:status::VARCHAR = 'approved'
  AND s.registry_document:state::VARCHAR IN ('active', 'manual')
  AND NOT EXISTS (
      SELECT 1 FROM GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS newer
      WHERE newer.source_id = s.source_id AND newer.registry_version > s.registry_version
  )
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY c.item_id, c.revision_id, c.source_id, c.registry_version, c.transport
    ORDER BY c.retrieved_at DESC, c.capture_id
) = 1;

GRANT SELECT ON VIEW PRESENTATION.INTELLIGENCE_FEED_V
    TO ROLE OH_LYME_{{ ENV }}_READ;
