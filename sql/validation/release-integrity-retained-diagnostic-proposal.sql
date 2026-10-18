-- SECURITY REVIEW PROPOSAL ONLY. NOT AN APPROVED MIGRATION; DO NOT EXECUTE.
-- Requires a separately authorized protected forward migration/security action.
-- No new role, base-table reader grant, owner membership, approval or pointer write.
USE DATABASE ONE_HEALTH_LYME_GAP_ATLAS_PROD;

CREATE SECURE VIEW LINEAGE_AUDIT.RETAINED_MODEL_RELEASES_V AS
SELECT r.release_id,r.bundle_sha256,
 OBJECT_CONSTRUCT('sources',ARRAY_AGG(OBJECT_CONSTRUCT_KEEP_NULL(
 'source_key',f.value:source_key,'artifact_sha256',f.value:artifact_sha256,
 'definition_version',f.value:definition_version,'field_map',f.value:field_map
 ))) AS source_manifest
FROM PRESENTATION.SEMANTIC_RELEASES r,
 LATERAL FLATTEN(INPUT=>r.source_manifest:sources) f
WHERE ((r.release_id='governed-2026-09-18-unknown-coverage'
 AND r.bundle_sha256='038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026')
 OR (r.release_id='governed-2026-10-15-january-climate-prod'
 AND r.bundle_sha256='53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d')) AND f.value:source_key::VARCHAR IN ('human','pathogen','context_svi','context_rucc','tick')
GROUP BY r.release_id,r.bundle_sha256;

CREATE SECURE VIEW LINEAGE_AUDIT.RETAINED_MODEL_SOURCES_V AS
SELECT s.release_id,s.source_key,s.resource_key,s.source_id,s.dataset_id,
 s.source_version_id,s.ingestion_run_id,s.artifact_id,s.vintage,s.note,s.source_url,s.label
FROM PRESENTATION.SEMANTIC_DATA_SOURCES s
JOIN PRESENTATION.SEMANTIC_RELEASES r ON r.release_id=s.release_id
WHERE ((r.release_id='governed-2026-09-18-unknown-coverage'
 AND r.bundle_sha256='038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026')
 OR (r.release_id='governed-2026-10-15-january-climate-prod'
 AND r.bundle_sha256='53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d')) AND s.source_key IN ('human','pathogen','context_svi','context_rucc','tick');

CREATE SECURE VIEW LINEAGE_AUDIT.RETAINED_MODEL_MEMBERSHIP_V AS
SELECT c.release_id,c.fips FROM PRESENTATION.SEMANTIC_COUNTY_ATLAS c
JOIN PRESENTATION.SEMANTIC_RELEASES r ON r.release_id=c.release_id
WHERE ((r.release_id='governed-2026-09-18-unknown-coverage'
 AND r.bundle_sha256='038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026')
 OR (r.release_id='governed-2026-10-15-january-climate-prod'
 AND r.bundle_sha256='53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d'));

CREATE SECURE VIEW LINEAGE_AUDIT.RETAINED_MODEL_OBSERVATIONS_V AS
-- Preserve multiplicity: one row per original observation, not DISTINCT.
-- Only identity/count columns; no observation values, raw payloads or URIs.
SELECT o.release_id,o.fips,o.source_key FROM PRESENTATION.SEMANTIC_OBSERVATIONS o
JOIN PRESENTATION.SEMANTIC_RELEASES r ON r.release_id=o.release_id
WHERE ((r.release_id='governed-2026-09-18-unknown-coverage'
 AND r.bundle_sha256='038aa3f8c383a70699aff92c752f2bbcc6687a726d0c2f142c9f368841b42026')
 OR (r.release_id='governed-2026-10-15-january-climate-prod'
 AND r.bundle_sha256='53e50aa37c701635e96c48cd4931c4c4a9e7e695c146263fb9bb335e541ae74d')) AND o.source_key IN ('human','pathogen','context_svi','context_rucc','tick');

-- Minimum reader surface. Existing DB/schema USAGE must be verified first.
-- Grant USAGE only if absent; it is already present for the V137 audit route.
-- GRANT USAGE ON DATABASE ONE_HEALTH_LYME_GAP_ATLAS_PROD TO ROLE OH_LYME_PROD_READ;
-- GRANT USAGE ON SCHEMA LINEAGE_AUDIT TO ROLE OH_LYME_PROD_READ;
GRANT SELECT ON VIEW LINEAGE_AUDIT.RETAINED_MODEL_RELEASES_V TO ROLE OH_LYME_PROD_READ;
GRANT SELECT ON VIEW LINEAGE_AUDIT.RETAINED_MODEL_SOURCES_V TO ROLE OH_LYME_PROD_READ;
GRANT SELECT ON VIEW LINEAGE_AUDIT.RETAINED_MODEL_MEMBERSHIP_V TO ROLE OH_LYME_PROD_READ;
GRANT SELECT ON VIEW LINEAGE_AUDIT.RETAINED_MODEL_OBSERVATIONS_V TO ROLE OH_LYME_PROD_READ;
-- Existing SELECT on LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V is also required.
-- Security owner defines expiry/revocation and checks dependent consumers.
