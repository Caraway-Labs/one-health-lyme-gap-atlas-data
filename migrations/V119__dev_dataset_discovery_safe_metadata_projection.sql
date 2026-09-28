-- DEV-only forward correction of the bounded Dataset Discovery observation view.
-- Data.gov registration retains DCAT values inside catalog_record.dcat rather
-- than copying them to top-level metadata_payload keys. No raw payload is exposed.
USE DATABASE {{ DATABASE }};

CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CANDIDATE_OBSERVATION_FIELDS
COPY GRANTS AS
SELECT o.ingestion_run_id AS discovery_run_id,
       o.observation_id, o.canonical_resource_key AS resource_key,
       o.catalog_dataset_id, o.catalog_resource_id, o.observed_at,
       d.metadata_sha256,
       OBJECT_CONSTRUCT_KEEP_NULL(
         'title', IFF(LENGTH(r.resource_payload:title::VARCHAR) <= 300,
                      r.resource_payload:title::VARCHAR, NULL),
         'publisher', IFF(LENGTH(r.resource_payload:publisher::VARCHAR) <= 200,
                          r.resource_payload:publisher::VARCHAR, NULL),
         'description', IFF(LENGTH(d.metadata_payload:description::VARCHAR) <= 500,
                            d.metadata_payload:description::VARCHAR, NULL),
         'issued', IFF(LENGTH(COALESCE(d.metadata_payload:issued::VARCHAR,
                              d.metadata_payload:catalog_record:dcat:issued::VARCHAR)) <= 100,
                       COALESCE(d.metadata_payload:issued::VARCHAR,
                                d.metadata_payload:catalog_record:dcat:issued::VARCHAR), NULL),
         'modified', IFF(LENGTH(COALESCE(d.metadata_payload:modified::VARCHAR,
                                d.metadata_payload:catalog_record:dcat:modified::VARCHAR)) <= 100,
                         COALESCE(d.metadata_payload:modified::VARCHAR,
                                  d.metadata_payload:catalog_record:dcat:modified::VARCHAR), NULL),
         'spatial', IFF(LENGTH(COALESCE(d.metadata_payload:spatial::VARCHAR,
                               d.metadata_payload:catalog_record:dcat:spatial::VARCHAR)) <= 300,
                        COALESCE(d.metadata_payload:spatial::VARCHAR,
                                 d.metadata_payload:catalog_record:dcat:spatial::VARCHAR), NULL),
         'temporal', IFF(LENGTH(COALESCE(d.metadata_payload:temporal::VARCHAR,
                                d.metadata_payload:catalog_record:dcat:temporal::VARCHAR)) <= 300,
                         COALESCE(d.metadata_payload:temporal::VARCHAR,
                                  d.metadata_payload:catalog_record:dcat:temporal::VARCHAR), NULL),
         'license', IFF(LENGTH(COALESCE(d.metadata_payload:license::VARCHAR,
                               d.metadata_payload:catalog_record:dcat:license::VARCHAR)) <= 300,
                        COALESCE(d.metadata_payload:license::VARCHAR,
                                 d.metadata_payload:catalog_record:dcat:license::VARCHAR), NULL),
         'access_level', IFF(LENGTH(COALESCE(d.metadata_payload:accessLevel::VARCHAR,
                                    d.metadata_payload:catalog_record:dcat:accessLevel::VARCHAR)) <= 100,
                             COALESCE(d.metadata_payload:accessLevel::VARCHAR,
                                      d.metadata_payload:catalog_record:dcat:accessLevel::VARCHAR), NULL),
         'keywords', IFF(LENGTH(d.metadata_payload:keywords::VARCHAR) <= 1000,
                         d.metadata_payload:keywords::VARCHAR, NULL),
         'theme', IFF(LENGTH(d.metadata_payload:catalog_record:dcat:theme::VARCHAR) <= 300,
                      d.metadata_payload:catalog_record:dcat:theme::VARCHAR, NULL),
         'resource_title', IFF(LENGTH(r.resource_payload:distribution:title::VARCHAR) <= 200,
                               r.resource_payload:distribution:title::VARCHAR, NULL),
         'resource_role', IFF(LENGTH(r.resource_payload:resource_role::VARCHAR) <= 50,
                              r.resource_payload:resource_role::VARCHAR, NULL),
         'resource_type', IFF(LENGTH(r.resource_type) <= 50, r.resource_type, NULL),
         'canonical_url', IFF(LENGTH(r.canonical_source_url) <= 500,
                              r.canonical_source_url, NULL),
         'distribution_description',
           IFF(LENGTH(r.resource_payload:distribution:description::VARCHAR) <= 300,
               r.resource_payload:distribution:description::VARCHAR, NULL),
         'distribution_media_type',
           IFF(LENGTH(r.resource_payload:distribution:mediaType::VARCHAR) <= 100,
               r.resource_payload:distribution:mediaType::VARCHAR, NULL),
         'distribution_format',
           IFF(LENGTH(r.resource_payload:distribution:format::VARCHAR) <= 100,
               r.resource_payload:distribution:format::VARCHAR, NULL),
         'catalog_record_id', IFF(LENGTH(d.catalog_record_id) <= 500,
                                  d.catalog_record_id, NULL),
         'parent_dataset_id', IFF(LENGTH(d.catalog_dataset_id) <= 200,
                                  d.catalog_dataset_id, NULL),
         'documentation_url',
           IFF(LENGTH(d.metadata_payload:catalog_record:harvest_record::VARCHAR) <= 500,
               d.metadata_payload:catalog_record:harvest_record::VARCHAR, NULL)
       ) AS field_values
FROM GOVERNANCE.CATALOG_DISCOVERY_OBSERVATIONS o
JOIN GOVERNANCE.CATALOG_DATASETS d
  ON d.catalog_dataset_id = o.catalog_dataset_id
JOIN GOVERNANCE.CATALOG_RESOURCES r
  ON r.catalog_resource_id = o.catalog_resource_id;
