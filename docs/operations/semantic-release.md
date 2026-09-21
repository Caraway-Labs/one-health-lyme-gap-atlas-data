# Governed semantic release runbook

This runbook is for Epic #252. The semantic release is the only product-facing
data boundary. The API reads the current-release views in `PRESENTATION`; it
does not read RAW, STAGING, CONFORMED, or the retained Alpha POC database.

## Evidence and review order

1. Use the successful GitHub Actions DEV Quality run and DEV deployment run as
   the automated-runtime evidence. A personal Snowflake account does not need
   `OH_LYME_DEV_RUNTIME`.
2. Review the source approval records and the exact DEV run, artifact, and
   quality evidence for every manifest source.
3. Review the generated candidate manifest and bundle SHA-256. The candidate
   must contain exactly 3,144 unique county FIPS values, valid Polygon
   geometry, and distinct tick and pathogen source entries.
4. Approve the protected GitHub `production` environment before a PROD build
   or publication. The workflow applies checksum-validated migrations first.
5. After publication, run the PROD queries below and verify that the API
   returns the same release ID and bundle SHA-256.

The tick county-status workbook and any pathogen source are separate review
items. Never use the tick workbook as evidence for pathogen observations.

## Protected workflow operations

Run `.github/workflows/publish-semantic-release.yml` from the repository's
Actions tab with the exact commit that passed DEV quality:

- `build` creates an immutable `CANDIDATE`; it never changes the API pointer.
- `publish` changes the pointer atomically after environment approval and
  `confirm=true`.
- `rollback` points the API to a retained release and records the reason; it
  is production-only.

The source-pinned file in the repository is a template. Copy it into a
reviewed manifest only after replacing every `REPLACE_WITH_*` value with the
approved source version, completed run, retained artifact, and exact artifact
SHA-256. Do not commit credentials or private workbook bytes.

## PROD Snowflake proof queries

Use the read-only `OH_LYME_PROD_RUNTIME` audit connection for these
queries. It is sufficient for the release tables after the protected
migrations. Do not use `ACCOUNTADMIN` for routine proof.

```sql
SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE();

SELECT release_id, status, schema_version, methodology_version, bundle_sha256,
       current_release_id, county_count, observation_count,
       missing_observation_lineage
FROM PRESENTATION.SEMANTIC_RELEASE_STATUS_V
ORDER BY loaded_at DESC;

SELECT release_id, schema_version, generated_at, loaded_at, scope,
       bundle_sha256, methodology_version, limitations
FROM PRESENTATION.CURRENT_RELEASE_V;

SELECT source_key, resource_key, source_id, dataset_id, label, vintage,
       source_url, note
FROM PRESENTATION.CURRENT_SOURCE_METADATA_V
ORDER BY source_key;

SELECT release_id, COUNT(*) AS county_rows,
       COUNT(DISTINCT fips) AS distinct_fips,
       COUNT_IF(LENGTH(fips) <> 5 OR NOT REGEXP_LIKE(fips, '^[0-9]{5}$')) AS bad_fips,
       COUNT_IF(IS_NULL_VALUE(geometry_json) OR geometry_json IS NULL) AS missing_geometry
FROM PRESENTATION.CURRENT_COUNTY_ATLAS_V
GROUP BY release_id;

SELECT event_id, release_id, event_type, previous_release_id, actor, reason, created_at
FROM PRESENTATION.SEMANTIC_RELEASE_EVENTS
ORDER BY created_at DESC;
```

The county query should return 3,144 rows and 3,144 distinct FIPS. The status
view should report zero missing observation lineage values. A failed query or
a different count is a release blocker, not a warning to work around.

## Runtime-audit access correction

V073 is a forward-only correction for the schema-access prerequisite of the
bounded V072 runtime-view grants. It grants only `USAGE` on `PRESENTATION` to
`OH_LYME_{ENV}_PIPELINE_RUNTIME`; it does not grant semantic-table reads or
writes. In PROD, where `PRESENTATION` was bootstrapped by the documented
one-time AccountAdmin session, apply V073 through that same bounded bootstrap
and append its exact source checksum to the migration ledger before retrying a
protected image promotion. Do not alter or delete the V071/V072 ledger rows.

## Rollback proof

After a rollback, the `CURRENT_RELEASE_V` row must match the retained target,
and the most recent event must be `ROLLBACK` with a human-readable reason.
The prior release remains retained in `SEMANTIC_RELEASES`; it is not deleted.

### First governed-release cutover

The first governed release, `governed-2026-09-18-unknown-coverage`, was
published without an earlier governed release. Its initial publication event
therefore has `previous_release_id = NULL`. Do **not** invoke semantic-release
rollback merely to test this condition: a rollback target must be a distinct,
retained `PUBLISHED` release, and this first release has none.

The first-cutover recovery boundary is deliberately split:

1. **Serving recovery:** restore the previously verified API deployment only
   when the current API deployment is unhealthy. Confirm that the restored
   deployment still uses `OH_LYME_PROD_READ` and
   `ONE_HEALTH_LYME_GAP_ATLAS_PROD`, then run `/health/ready`, metadata, and a
   representative county request. This changes application code only; it does
   not change the governed release pointer.
2. **Data recovery:** use the protected semantic-release `rollback` operation
   only after a later, retained governed release exists and a human has
   reviewed its manifest, bundle, and reason. Verify the pointer and append-only
   event record afterwards.
3. **Alpha boundary:** `ONE_HEALTH_LYME_GAP_ATLAS` is an immutable reference,
   not an automatic rollback target. Returning public traffic to Alpha would
   be a separate product and production decision with its own approval,
   deployment evidence, public communication, and restoration plan.

For a rehearsal, record the API deployment identifiers, verify the platform's
previous-deployment relationship and automatic-fallback state, and execute
serving recovery only in an approved non-production environment unless a
production recovery is required by an active incident. Re-deploy the approved
governed artifact after the rehearsal and attach health, metadata, and runtime
query evidence. Never rewrite release events, delete retained artifacts, or
alter the Alpha POC while rehearsing recovery.
