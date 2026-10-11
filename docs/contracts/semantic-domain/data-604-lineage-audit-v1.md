# DATA #604 internal semantic lineage audit v1

Status: Proposed for independent access-control review. Owner: Atlas data engineering. This is an internal audit projection, not a public API or a consumer-safe lineage response.

## Decision

Use one secure `LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V` view, owned by the migration identity, with schema `USAGE` and object-level `SELECT` for the environment's existing `READ` role. The protected migration identity creates this dedicated schema using its existing database `CREATE SCHEMA` grant; it lacks `CREATE VIEW` on the pre-existing PRESENTATION, CONFORMED, and GOVERNANCE schemas in PROD. The view joins semantic observations and release/source metadata to immutable artifact and source-record evidence. It includes the V103 immutable revision path and the V069 conformed fallback. It emits `UNMATCHED` when neither path resolves; an audit must also reject duplicate matches. No base-table, DML, approval, migration, or release-control grant is added to `READ`.

The view is deliberately internal: artifact IDs and hashes are needed to prove immutable ancestry and must not be copied to public API responses. The consumer-safe #193 projection still excludes them.

| Candidate evidence | Classification | Reason |
| --- | --- | --- |
| Observation ID, release ID, measure ID | REQUIRED | Exact semantic and release membership. |
| County FIPS and temporal window | REQUIRED | Deterministic observation reconciliation. |
| Source key, source version, ingestion run, artifact ID and artifact SHA-256 | REQUIRED | Exact immutable source chain. |
| Release bundle SHA-256 | REQUIRED | Release identity. |
| Source ID, dataset ID, resource key | REQUIRED | Governed source tuple and safe join disambiguation. |
| Semantic source-record ID/hash and governed record/revision IDs/hash | REQUIRED | Exact source identity, legacy fallback, mismatch and duplicate detection. |
| Standalone semantic revision ID | OPTIONAL | V071 storage has no such column; the release observation ID and bundle are the available persisted identity. Do not synthesize one. |
| Labels, publisher, source URL, method text | OPTIONAL | Useful for presentation, not needed for the bounded identity proof. |
| Raw payload, unrestricted source rows, artifact URI/signed URL, credentials, article text, unrelated columns, write/approval controls | PROHIBITED | They exceed this internal audit purpose. |

## Alternatives

An owner-rights procedure could constrain input IDs but adds code, execution privilege, and result-shaping complexity for a read-only relational audit. Extending a public/current-release projection would mix internal artifact/record hashes into a consumer-facing contract and hide historical release rows. A separate role would increase role and connection count without improving isolation over object-level SELECT on existing `READ`.

## Acceptance query

Run with `ATLAS_DEV_READ` in DEV. In PROD, use a separately configured named PAT connection bound to `OH_LYME_PROD_READ`, with its identity checked first, and substitute the reviewed PROD release ID. This connection is not present in the 2026-09-16 inventory and must be created through the approved connection process; never repurpose the runtime/owner/migrator or ACCOUNTADMIN connection.

```sql
SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE();
SELECT observation_id, release_id, measure_id, county_fips, temporal_window,
       source_key, source_version_id, governed_source_version_id,
       ingestion_run_id, governed_ingestion_run_id, artifact_id,
       artifact_sha256, release_bundle_sha256, source_id, dataset_id,
       resource_key, semantic_source_record_id, semantic_source_row_hash,
       revision_record_id, capture_record_id, record_revision,
       revision_artifact_sha256,
       conformed_record_id, governed_source_record_id,
       governed_source_row_hash, record_match_kind
FROM LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V
WHERE release_id = 'governed-2026-09-17-unknown-coverage'
  AND source_key IN ('context_svi', 'context_rucc')
ORDER BY observation_id
LIMIT 20;
```

For acceptance, count rows per observation ID and require exactly one authoritative match for each selected representative; compare semantic and governed row hashes, source/run/artifact tuple, revision artifact SHA-256 (where present), and release bundle. Null governed source-version/run IDs or artifact digest, `UNMATCHED`, multiple rows, or disagreeing identity fails acceptance. The query above is an example, not yet live proof.

## Rollback

After checking dependents and the migration ledger, use a reviewed forward migration with the following environment-rendered operations:

```sql
REVOKE SELECT ON VIEW LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V
  FROM ROLE OH_LYME_{{ ENV }}_READ;
REVOKE USAGE ON SCHEMA LINEAGE_AUDIT FROM ROLE OH_LYME_{{ ENV }}_READ;
DROP VIEW IF EXISTS LINEAGE_AUDIT.SEMANTIC_LINEAGE_AUDIT_V;
-- Only after confirming the dedicated schema contains no other objects:
DROP SCHEMA IF EXISTS LINEAGE_AUDIT;
```

Do not roll back V069/V071/V103, touch source or semantic rows, change pointers, or grant a broader role. PROD rollback uses the protected migration path and an exact reviewed image digest. The commands above are documented and parsed as SQL; rollback is not executed against the live DEV or PROD lineage without a separate recovery decision.
