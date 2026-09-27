USE DATABASE {{ DATABASE }};

-- Bounded, read-only identity links for one registered discovery snapshot.
-- The application queries one candidate key with LIMIT 2, rejecting ambiguous
-- multiple matches rather than choosing a convenient source. No raw payload,
-- private artifact, approval decision, or acquisition capability is exposed.
CREATE OR REPLACE VIEW DATASET_DISCOVERY.V_CANDIDATE_IDENTITY_LINKS AS
SELECT candidate.discovery_run_id,
       candidate.resource_key,
       candidate.catalog_dataset_id,
       candidate.catalog_resource_id,
       linked.resource_key AS linked_resource_key,
       linked.catalog_dataset_id AS linked_catalog_dataset_id,
       linked.catalog_resource_id AS linked_catalog_resource_id,
       CASE
         WHEN linked.resource_key = candidate.resource_key
           THEN 'EXACT_DUPLICATE'
         WHEN candidate.canonical_source_url IS NOT NULL
          AND linked.canonical_source_url = candidate.canonical_source_url
           THEN 'EXACT_DUPLICATE'
         ELSE 'ALTERNATE_DISTRIBUTION'
       END AS relationship,
       CASE
         WHEN linked.resource_key = candidate.resource_key
           THEN 'EXACT_RESOURCE_KEY'
         WHEN candidate.canonical_source_url IS NOT NULL
          AND linked.canonical_source_url = candidate.canonical_source_url
           THEN 'EXACT_CANONICAL_URL'
         ELSE 'SAME_CATALOG_DATASET'
       END AS relationship_basis
FROM DATASET_DISCOVERY.V_CANDIDATE_SUMMARY candidate
JOIN GOVERNANCE.CATALOG_RESOURCES linked
  ON linked.catalog_resource_id <> candidate.catalog_resource_id
 AND linked.is_active = TRUE
 AND (
   linked.resource_key = candidate.resource_key
   OR (
     candidate.canonical_source_url IS NOT NULL
     AND linked.canonical_source_url = candidate.canonical_source_url
   )
   OR linked.catalog_dataset_id = candidate.catalog_dataset_id
 )
WHERE candidate.resource_is_active = TRUE
  AND candidate.dataset_is_current = TRUE;

-- Do not infer MIRROR from a metadata hash or infer REVISION/SUPERSESSION from
-- dates or titles. Those need separately retained, reviewed link evidence.
-- Runtime SELECT grant remains blocked by proposed ADR 0041; this migration
-- creates no role or grant and is not authorized for protected application yet.
