-- DATA #132/#135: PROD-only forward promotion of the DEV-verified V142 retention and v2 projection.
-- Existing V1 grants are preserved; V2 is separately granted to the PROD reader.
-- No cleanup procedure, source admission, or feed acquisition is implied.
USE DATABASE {{ DATABASE }};

CREATE TABLE IF NOT EXISTS GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS (
    DOCUMENT_TYPE VARCHAR(32) NOT NULL,
    DOCUMENT_KEY VARCHAR(256) NOT NULL,
    DOCUMENT_SHA256 VARCHAR(64) NOT NULL,
    DOCUMENT VARIANT NOT NULL,
    REGISTERED_AT TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
-- lease/capture/validation/run/run_source/copy/write_complete/buffer_release only:
-- bounded structured metadata, never XML,
-- base64 or raw feed body. Standard-table uniqueness is enforced under V135's
-- existing write guard by the runtime, not assumed from unenforced constraints.

CREATE TABLE IF NOT EXISTS GOVERNANCE.INTELLIGENCE_RAW_RETENTION_AUDIT (
    RECEIPT_SHA256 VARCHAR(64) NOT NULL,
    DOCUMENT VARIANT NOT NULL,
    REGISTERED_AT TIMESTAMP_TZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
);
-- Independent committed append-only audit transaction/table: pending intent
-- must survive outer claim-lock rollback or a crash after physical deletion.

CREATE OR REPLACE VIEW PRESENTATION.INTELLIGENCE_FEED_V COPY GRANTS AS
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
WHERE c.item_document:contract_version::VARCHAR = '1.0.0'
  AND s.registry_document:approval:status::VARCHAR = 'approved'
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


CREATE VIEW IF NOT EXISTS PRESENTATION.INTELLIGENCE_FEED_V2 AS
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
WHERE c.item_document:contract_version::VARCHAR = '2.0.0'
  AND s.registry_document:approval:status::VARCHAR = 'approved'
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


GRANT SELECT, INSERT ON TABLE GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS TO ROLE OH_LYME_PROD_RUNTIME;
GRANT INSERT ON TABLE GOVERNANCE.INTELLIGENCE_RAW_RETENTION_AUDIT TO ROLE OH_LYME_PROD_RUNTIME;
GRANT SELECT ON VIEW PRESENTATION.INTELLIGENCE_FEED_V2 TO ROLE OH_LYME_PROD_READ;
