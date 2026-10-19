-- PROPOSAL ONLY. Additional exact-action protected authorization is required.
-- Read-only diagnostic surface; no historical observation/model is rewritten.
USE DATABASE ONE_HEALTH_LYME_GAP_ATLAS_PROD;

CREATE SECURE VIEW LINEAGE_AUDIT.RETAINED_MODEL_HUMAN_RECORDS_V AS
WITH pins AS (
 SELECT s.release_id,r.bundle_sha256,s.source_version_id,s.ingestion_run_id,s.artifact_id,
        f.value:artifact_sha256::VARCHAR AS artifact_sha256
 FROM LINEAGE_AUDIT.RETAINED_MODEL_SOURCES_V s
 JOIN LINEAGE_AUDIT.RETAINED_MODEL_RELEASES_V r ON r.release_id=s.release_id,
 LATERAL FLATTEN(INPUT=>r.source_manifest:sources) f
 WHERE s.source_key='human' AND f.value:source_key::VARCHAR='human'
   AND s.resource_key='cdc_lyme_x5j9_wybp'
   AND s.source_version_id='6e0cb93f-ea95-4b3a-a358-b343321223b8'
   AND s.ingestion_run_id='819259d8-a362-44ac-903a-16754f28b87c'
   AND s.artifact_id='df4e8edc-8033-4c17-b237-f72ef6c27a9d'
   AND f.value:artifact_sha256::VARCHAR='c00584e1a940f31369ad130f6e67c8bdc2526794f86a81289e106dba67e0b68e'
   AND ((r.release_id='governed-2026-09-18-unknown-coverage'
     AND r.bundle_sha256='038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026')
     OR (r.release_id='governed-2026-10-15-january-climate-prod'
     AND r.bundle_sha256='53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d'))
   AND CURRENT_TIMESTAMP()<TO_TIMESTAMP_TZ('2026-10-25T00:00:00Z')
 QUALIFY COUNT(*) OVER (PARTITION BY s.release_id)=1
)
SELECT p.release_id,p.bundle_sha256,p.source_version_id,p.ingestion_run_id,
       p.artifact_id,p.artifact_sha256,c.source_record_id,c.payload:fips::VARCHAR AS county_fips,c.payload:year::NUMBER AS report_year,
       UPPER(TRIM(CASE WHEN TYPEOF(c.payload:record)='OBJECT'
         THEN c.payload:record:state::VARCHAR ELSE c.payload:state::VARCHAR END)) AS state_token,
       (c.payload:year::NUMBER=2023 AND LOWER(c.payload:case_status::VARCHAR) IN ('confirmed','probable')
        AND REGEXP_LIKE(c.payload:fips::VARCHAR,'^[0-9]{5}$')) AS county_linked_2023,
       (c.payload:year::NUMBER=2023 AND LOWER(c.payload:fips::VARCHAR) IN ('unknown','suppressed','not reported'))
        AS state_unallocated_2023,
       SHA2(TO_JSON(c.payload),256) AS derived_retained_payload_sha256,
       'SHA256_SNOWFLAKE_TO_JSON_RETAINED_RAW_PAYLOAD_V1' AS hash_derivation
FROM pins p
JOIN RAW.CDC_LYME_X5J9_WYBP c
 ON c.data_source_version_id=p.source_version_id
 AND c.ingestion_run_id=p.ingestion_run_id AND c.artifact_id=p.artifact_id;

-- One physical retained record per output row: preserve duplicate multiplicity.
-- No payload, frequency/case counts, sex, age, URI, write or approval access.
-- Derived fingerprints are labeled; they are not historical semantic row hashes.
GRANT SELECT ON VIEW LINEAGE_AUDIT.RETAINED_MODEL_HUMAN_RECORDS_V TO ROLE OH_LYME_PROD_READ;
