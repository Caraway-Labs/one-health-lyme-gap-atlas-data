-- DATA #808: activation rows replace the per-source SHA CASE in FEED_V2.
-- The protected register workflow is the ongoing writer. Its MERGE is idempotent.
-- Backfill inserts ACTIVE rows only. A version the current feed serves stays
-- ACTIVE. On PROD that includes cdc-eid-ahead-of-print version 1. DEV keeps the
-- V142 rule: a newer stored version leaves the older one out of the feed.
-- No backfill writes a BLOCKED row. Hiding a version the feed serves is #809.
-- The backfill uses a pins CTE and joins, not a correlated CASE subquery:
-- PROD Snowflake rejects that form (error 002031). Semantics are unchanged.
-- state may later be ACTIVE, BLOCKED, or RETIRED. Runtime roles can read the
-- table. They cannot insert, update, or delete it.
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
    WITH pins AS (
        SELECT column1 AS source_id, column2 AS v1_sha256, column3 AS v2_sha256
        FROM VALUES
            ('cdc-eid-expedited', '51705ebb4c82d7fc8e992f2e5793c45f79f202578ba487747aa2109e695f33a4', '570a796df7086b520136e5deab5917957561314e2f5fe96659bb3c9534124423'),
            ('cdc-eid-ahead-of-print', 'b92e97c9e958c270645c9710118b3a3076228c6bcb2390b5c58cff9bacb2a7be', '12e3003da3e8782b379e321eb61fccecb36a9269c3017c10132bb96c848c39c3'),
            ('cdc-outbreaks', '54793f2c4856602bf8901d09972a44d2a7479056e71eac75ddc88db060646172', 'd8bdcc90b16c98fe2b3661a9316ac78071bd355cbb46ee5d0299c15ca4f53b8f'),
            ('nih-news-releases', '38d7364d5ce7b730d16e07197d0bb1cf88403eae59defc66de05e3a3df825bea', '1542aa4d8f85a650ac216e574907ec19f65e1d17a26dd8c8b607bfdcd17faaa1'),
            ('cdc-mmwr', '875b0bc1b33f2c89ff4596532ccd8504dc6ce60086f8bba9146183da2b2d59a6', '9ee7ceca898a4419241d9706c7cbf0a795287c794cdeb74b0892a4f90ccda0e9')
    ),
    candidates AS (
        SELECT
            s.source_id,
            s.registry_version,
            s.registry_sha256,
            s.registry_document:approval:decision_ref::VARCHAR AS decision_id
        FROM GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS s
        WHERE s.source_id IN (
                'cdc-eid-ahead-of-print',
                'cdc-eid-expedited',
                'cdc-mmwr',
                'cdc-outbreaks',
                'nih-news-releases'
            )
          AND s.registry_document:approval:decision_ref::VARCHAR IS NOT NULL
    ),
    superseded AS (
        SELECT DISTINCT c.source_id, c.registry_version
        FROM candidates c
        JOIN GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS newer
          ON newer.source_id = c.source_id
         AND newer.registry_version > c.registry_version
        LEFT JOIN pins p
          ON p.source_id = c.source_id
        WHERE NOT (
            '{{ ENV }}' = 'PROD'
            AND c.registry_version=1 AND newer.registry_version=2
            AND c.registry_sha256=COALESCE(p.v1_sha256, '')
            AND newer.registry_sha256=COALESCE(p.v2_sha256, '')
            AND newer.registry_document:state::VARCHAR='active'
            AND newer.registry_document:approval:status::VARCHAR='approved'
            AND newer.registry_document:trust_review:status::VARCHAR='approved'
        )
    )
    SELECT
        c.source_id,
        c.registry_version,
        c.registry_sha256,
        'ACTIVE' AS state,
        c.decision_id
    FROM candidates c
    LEFT JOIN superseded x
      ON x.source_id = c.source_id
     AND x.registry_version = c.registry_version
    WHERE x.source_id IS NULL
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
