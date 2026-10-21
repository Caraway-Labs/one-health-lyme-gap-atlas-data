-- DATA #132: forward correction for Snowflake correlated-subquery error 002031.
-- Preserve the exact V164 admission predicate using an uncorrelated blocked-version join.
-- Only the three pinned CDC v1->v2 transitions may retain their prior captures.
-- Unknown/future/revoked transitions still suppress older versions as before.
-- No source registration, feed request, data mutation, procedure or new grant.
USE DATABASE {{ DATABASE }};
CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V2 COPY GRANTS AS
WITH blocked_source_versions AS (
    SELECT DISTINCT s.source_id, s.registry_version
    FROM GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS s
    JOIN GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS newer
      ON newer.source_id = s.source_id AND newer.registry_version > s.registry_version
    WHERE NOT COALESCE((

            s.registry_version=1 AND newer.registry_version=2
            AND s.registry_sha256=CASE s.source_id WHEN 'cdc-eid-expedited' THEN '51705ebb4c82d7fc8e992f2e5793c45f79f202578ba487747aa2109e695f33a4' WHEN 'cdc-eid-ahead-of-print' THEN 'b92e97c9e958c270645c9710118b3a3076228c6bcb2390b5c58cff9bacb2a7be' WHEN 'cdc-outbreaks' THEN '54793f2c4856602bf8901d09972a44d2a7479056e71eac75ddc88db060646172' ELSE '' END
            AND newer.registry_sha256=CASE s.source_id WHEN 'cdc-eid-expedited' THEN '570a796df7086b520136e5deab5917957561314e2f5fe96659bb3c9534124423' WHEN 'cdc-eid-ahead-of-print' THEN '12e3003da3e8782b379e321eb61fccecb36a9269c3017c10132bb96c848c39c3' WHEN 'cdc-outbreaks' THEN 'd8bdcc90b16c98fe2b3661a9316ac78071bd355cbb46ee5d0299c15ca4f53b8f' ELSE '' END
            AND newer.registry_document:state::VARCHAR='active'
            AND newer.registry_document:approval:status::VARCHAR='approved'
            AND newer.registry_document:trust_review:status::VARCHAR='approved'
        ),FALSE)
)
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
LEFT JOIN blocked_source_versions blocked
  ON blocked.source_id = s.source_id AND blocked.registry_version = s.registry_version
WHERE c.item_document:contract_version::VARCHAR = '2.0.0'
  AND s.registry_document:approval:status::VARCHAR = 'approved'
  AND s.registry_document:trust_review:status::VARCHAR = 'approved'
  AND s.registry_document:state::VARCHAR IN ('active', 'manual')
  AND blocked.source_id IS NULL
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY c.item_id, c.revision_id, c.source_id, c.transport
    ORDER BY c.retrieved_at DESC, c.capture_id
) = 1;
