-- DATA #871: one PubMed feed row per item, plus FEED_SORT_AT.
-- V174 is the next free migration number. V171, V172, V175, and V176 are
-- reserved on open pull requests. This view starts from the V173 body.
-- Entrez keeps the newest capture per item_id. RSS keeps the V173 partition,
-- so one cross-source RSS item stays two rows. No capture, revision, or
-- activation row is deleted or updated.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V2 COPY GRANTS AS
SELECT item_id, revision_id, source_id, registry_version, transport,
       deduplication_key,
       content_sha256,
       transport_identity_sha256,
       canonical_url,
       title,
       published_at,
       updated_at,
       event_at,
       fetched_at,
       excerpt,
       field_states,
       geographies,
       topics,
       provenance,
       limitations,
       contract_version,
       content_is_untrusted,
       publisher_metadata,
       derived_metadata,
       organization,
       reviewed_trust_classification,
       IFF(published_at IS NULL
           OR TRY_TO_TIMESTAMP_TZ(published_at) > first_loaded_at,
           first_loaded_at,
           TRY_TO_TIMESTAMP_TZ(published_at))::TIMESTAMP_TZ AS FEED_SORT_AT
FROM (
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
           ),
           'description', c.item_document:publisher_metadata:description,
           'abstract', c.item_document:publisher_metadata:abstract,
           'abstract_suppressed', c.item_document:publisher_metadata:abstract_suppressed
       ) AS publisher_metadata,
       OBJECT_CONSTRUCT() AS derived_metadata,
       s.registry_document:organization::VARCHAR AS organization,
       s.registry_document:trust_classification::VARCHAR AS reviewed_trust_classification,
       (MIN(c.retrieved_at) OVER (
           PARTITION BY c.item_id, IFF(c.transport = 'entrez', NULL, c.source_id)
       ))::TIMESTAMP_TZ AS first_loaded_at
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
    PARTITION BY c.item_id,
                 IFF(c.transport = 'entrez', NULL, c.revision_id),
                 IFF(c.transport = 'entrez', NULL, c.source_id),
                 c.transport
    ORDER BY c.retrieved_at DESC,
             IFF(c.transport = 'entrez', c.capture_id, NULL) DESC,
             c.capture_id
) = 1
) ranked;
