# Protected PROD historical CDC full ingestion

This runbook begins only after the independent PROD steward decision for
`qtbi-xd4i`. It performs one controlled full refresh and does not create a
schedule or authorize a different source version.

## Preconditions

1. Confirm the immutable PROD decision and exact active source-version UUID.
2. Merge a green implementation and record the immutable image digest deployed
   to DEV. Promote that same digest through the protected production workflow.
3. Verify the migration ledger is checksum-clean. If it contains the exact
   owner-approved PROD V022/V028 legacy conditions, separately authorize and
   run `pipeline reconcile-legacy-prod-migrations --confirm`; require the
   pinned row counts, filenames, and checksums and retain every original row.
4. Obtain explicit authorization for the one-time V051 AccountAdmin DDL session;
   the account currently has no permanent PROD migration-deployer role. Apply
   only V051, then end that admin scope. Apply V052 through a separate PAT
   restricted to
   `OH_LYME_PROD_GOVERNED_VIEW_OWNER`. Verify both exact checksums in
   `GOVERNANCE.SCHEMA_MIGRATIONS`; do not bypass earlier checksum drift or use
   AccountAdmin as a runtime identity.
5. Verify `GOVERNED_DATA_EXPLORER` remains owned by the Streamlit owner and its
   four allowlisted views remain owned by the governed-view owner.

## One-shot ingestion

Dispatch `ingest-prod-cdc-historical.yml` with the exact deployed digest and
approved PROD UUID. Obtain the protected production deployment approval. The
workflow must start from and restore these six scheduled jobs:

- `approved-source-ingestion`
- `catalog-discovery`
- `catalog-registration-01`
- `catalog-registration-02`
- `catalog-registration-03`
- `cdc-operations-watchdog`

The temporary `PRE_DEPLOY` job fully acquires the source with deterministic
paging, stores immutable artifacts, loads source-faithful RAW records, builds
the allowlisted historical dbt path, persists eleven blocking quality results,
and publishes only after all checks pass.

## Required verification

Using read-only PROD queries, record:

- one completed historical ingestion run and its code version;
- publisher, retrieved, RAW, retained-snapshot, and CONFORMED row counts;
- request-page and immutable-artifact counts and checksums;
- exactly eleven distinct passing `cdc_qtbi_v1_*` rules and zero failures;
- publication source version, run, checksum, and revision;
- 2008 minimum and 2021 maximum years;
- preserved missing, null, unknown, suppressed, not-reported, zero, and observed
  value-state semantics;
- Data Explorer visibility and the 2008–2021 non-comparability caveat; and
- restoration of the exact six-job topology with one unique digest and no
  temporary job.

Do not infer success from CI, deployment status, or row count alone.

## Failure and rollback

A failed acquisition or quality gate retains its append-only evidence and must
not replace the current publication. Restore the captured App Platform
specification before any retry.

When a previously published, distinct retained snapshot is explicitly selected,
dispatch `rollback-prod-cdc-historical.yml` with its source version, ingestion
run, the current publication revision, and the same DEV-tested digest. The
command revalidates the retained rows and appends an `OPERATOR_ROLLBACK` event.
It never deletes RAW rows, artifacts, quality results, or snapshot history.
