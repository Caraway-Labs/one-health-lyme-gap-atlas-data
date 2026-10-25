-- DATA #844: FEED_V2 passes captured abstracts through and flags suppressions.
-- GOVERNANCE.INTELLIGENCE_ABSTRACT_SUPPRESSIONS records a PMID or a publisher.
-- A match replaces that item's abstract with text null, state suppressed, and
-- copyright_line null. Any other captured abstract is projected unchanged.
-- Grouped lookups keep one feed row when both a PMID and a publisher match.
-- The row stays in the feed. Runtime and reader roles can select the table.
-- They cannot insert, update, or delete it.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS GOVERNANCE.INTELLIGENCE_ABSTRACT_SUPPRESSIONS (
    scope VARCHAR(16) NOT NULL,
    pmid VARCHAR(16),
    publisher VARCHAR(1000),
    reason VARCHAR NOT NULL,
    decision_id VARCHAR(200) NOT NULL,
    created_at TIMESTAMP_LTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT ck_intelligence_abstract_suppression_scope CHECK (
        (
            scope = 'PMID'
            AND pmid IS NOT NULL
            AND publisher IS NULL
        )
        OR (
            scope = 'PUBLISHER'
            AND publisher IS NOT NULL
            AND pmid IS NULL
        )
    )
);

GRANT SELECT ON TABLE GOVERNANCE.INTELLIGENCE_ABSTRACT_SUPPRESSIONS
    TO ROLE OH_LYME_{{ ENV }}_RUNTIME;
GRANT SELECT ON TABLE GOVERNANCE.INTELLIGENCE_ABSTRACT_SUPPRESSIONS
    TO ROLE OH_LYME_{{ ENV }}_READ;

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
       (
           pmid_suppression.pmid IS NOT NULL
           OR publisher_suppression.publisher IS NOT NULL
       ) AS abstract_suppressed,
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
           ),
           'description', c.item_document:publisher_metadata:description,
           'abstract', IFF(
               pmid_suppression.pmid IS NOT NULL
               OR publisher_suppression.publisher IS NOT NULL,
               OBJECT_CONSTRUCT_KEEP_NULL(
                   'text', NULL,
                   'state', 'suppressed',
                   'copyright_line', NULL
               ),
               c.item_document:publisher_metadata:abstract
           ),
           'mesh', c.item_document:publisher_metadata:mesh,
           'publication_types', c.item_document:publisher_metadata:publication_types,
           'matched_queries', c.item_document:publisher_metadata:matched_queries,
           'abstract_suppressed',
               pmid_suppression.pmid IS NOT NULL
               OR publisher_suppression.publisher IS NOT NULL
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
LEFT JOIN (
    SELECT pmid
    FROM GOVERNANCE.INTELLIGENCE_ABSTRACT_SUPPRESSIONS
    WHERE scope = 'PMID'
      AND pmid IS NOT NULL
    GROUP BY pmid
) pmid_suppression
  ON pmid_suppression.pmid = IFF(
      IS_NULL_VALUE(c.item_document:publisher_metadata:source_item_id),
      NULL,
      c.item_document:publisher_metadata:source_item_id::VARCHAR
  )
LEFT JOIN (
    SELECT publisher
    FROM GOVERNANCE.INTELLIGENCE_ABSTRACT_SUPPRESSIONS
    WHERE scope = 'PUBLISHER'
      AND publisher IS NOT NULL
    GROUP BY publisher
) publisher_suppression
  ON publisher_suppression.publisher = IFF(
      IS_NULL_VALUE(c.item_document:publisher_metadata:publisher),
      NULL,
      c.item_document:publisher_metadata:publisher::VARCHAR
  )
WHERE c.item_document:contract_version::VARCHAR = '2.0.0'
  AND s.registry_document:approval:status::VARCHAR = 'approved'
  AND s.registry_document:trust_review:status::VARCHAR = 'approved'
  AND s.registry_document:state::VARCHAR IN ('active', 'manual')
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY c.item_id, c.revision_id, c.source_id, c.transport
    ORDER BY c.retrieved_at DESC, c.capture_id
) = 1;
