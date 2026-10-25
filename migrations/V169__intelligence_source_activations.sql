-- DATA #808: one activation row per source version replaces the per-source SHA CASE.
-- Ongoing writes are the protected register workflow's single idempotent MERGE.
-- Backfill covers the five live sources already stored in the registry.
-- A superseded version is BLOCKED. The latest stored version is ACTIVE.
-- state is ACTIVE, BLOCKED, or RETIRED. The writer admits only those tokens.
-- Runtime roles can read the table. They cannot insert, update, or delete it.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS GOVERNANCE.INTELLIGENCE_SOURCE_ACTIVATIONS (
    source_id VARCHAR(200) NOT NULL,
    registry_version NUMBER NOT NULL,
    registry_sha256 VARCHAR(64) NOT NULL,
    state VARCHAR(16) NOT NULL,
    decision_id VARCHAR(200) NOT NULL,
    activated_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (source_id, registry_version)
);

GRANT SELECT ON TABLE GOVERNANCE.INTELLIGENCE_SOURCE_ACTIVATIONS
    TO ROLE OH_LYME_{{ ENV }}_RUNTIME;
GRANT SELECT ON TABLE GOVERNANCE.INTELLIGENCE_SOURCE_ACTIVATIONS
    TO ROLE OH_LYME_{{ ENV }}_READ;

MERGE INTO GOVERNANCE.INTELLIGENCE_SOURCE_ACTIVATIONS target
USING (
    SELECT source_id, registry_version, registry_sha256, state, decision_id
    FROM (
        SELECT
            s.source_id,
            s.registry_version,
            s.registry_sha256,
            IFF(newer.source_id IS NULL, 'ACTIVE', 'BLOCKED') AS state,
            s.registry_document:approval:decision_ref::VARCHAR AS decision_id
        FROM GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS s
        LEFT JOIN GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS newer
          ON newer.source_id = s.source_id
         AND newer.registry_version > s.registry_version
        WHERE s.source_id IN (
            'cdc-eid-ahead-of-print',
            'cdc-eid-expedited',
            'cdc-mmwr',
            'cdc-outbreaks',
            'nih-news-releases'
        )
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY s.source_id, s.registry_version
            ORDER BY newer.registry_version NULLS FIRST
        ) = 1
    )
) source
ON target.source_id = source.source_id
 AND target.registry_version = source.registry_version
WHEN MATCHED AND (
    target.registry_sha256 <> source.registry_sha256
    OR target.state <> source.state
    OR target.decision_id <> source.decision_id
) THEN UPDATE SET
    registry_sha256 = source.registry_sha256,
    state = source.state,
    decision_id = source.decision_id,
    activated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
    source_id, registry_version, registry_sha256, state, decision_id
) VALUES (
    source.source_id,
    source.registry_version,
    source.registry_sha256,
    source.state,
    source.decision_id
);

CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V2 COPY GRANTS AS
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
       OBJECT_CONSTRUCT_KEEP_NULL(
           'publisher', c.item_document:publisher_metadata:publisher,
           'source_family', c.item_document:publisher_metadata:source_family,
           'source_item_id', c.item_document:publisher_metadata:source_item_id,
           'authors', c.item_document:publisher_metadata:authors,
           'categories', c.item_document:publisher_metadata:categories,
           'language', c.item_document:publisher_metadata:language,
           'media', c.item_document:publisher_metadata:media,
           'date_states', OBJECT_CONSTRUCT_KEEP_NULL(
               'published_at', c.item_document:field_states:published_at,
               'updated_at', c.item_document:field_states:updated_at
           )
       ) AS publisher_metadata,
       OBJECT_CONSTRUCT() AS derived_metadata,
       s.registry_document:organization::VARCHAR AS organization,
       s.registry_document:trust_classification::VARCHAR AS reviewed_trust_classification
FROM GOVERNANCE.INTELLIGENCE_ITEM_CAPTURES c
JOIN CONFORMED.INTELLIGENCE_ITEM_REVISIONS r
  ON r.item_id = c.item_id AND r.revision_id = c.revision_id
JOIN GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS s
  ON s.source_id = c.source_id AND s.registry_version = c.registry_version
JOIN GOVERNANCE.INTELLIGENCE_SOURCE_ACTIVATIONS a
  ON a.source_id = s.source_id
 AND a.registry_version = s.registry_version
 AND a.registry_sha256 = s.registry_sha256
 AND a.state = 'ACTIVE'
WHERE c.item_document:contract_version::VARCHAR = '2.0.0'
  AND s.registry_document:approval:status::VARCHAR = 'approved'
  AND s.registry_document:trust_review:status::VARCHAR = 'approved'
  AND s.registry_document:state::VARCHAR IN ('active', 'manual')
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY c.item_id, c.revision_id, c.source_id, c.transport
    ORDER BY c.retrieved_at DESC, c.capture_id
) = 1;
