# Historical CDC full ingestion: DEV only

The owner approved DEV schema/grants, deployment, full acquisition and validation
after the Streamlit decision for `qtbi-xd4i`. This implements the existing
source-onboarding contract and ADRs 0005/0006/0018; it does not authorize PROD,
a refresh schedule, an API change, a new metric, or cross-era comparisons.

## Delivery and acceptance

1. Review and merge the change after lint, type checks, tests, dbt parse, container
   checks and full-history secret scanning pass.
2. Apply DEV-only V046 with the existing migration deployer. It creates historical
   RAW and retained snapshot relations and grants only SELECT/INSERT to runtime,
   plus exact reads to the existing governed-view owner. Runtime cannot approve.
3. Apply V047 as the existing DEV governed-view owner. It extends the restricted
   validation and explorer views. No RAW payload or private artifact URI is exposed.
4. Deploy the reviewed immutable image using the existing Quality workflow with
   `deploy_dev=true`. Retain the image digest and live current-source fixture proof.
5. Dispatch `ingest-dev-cdc-historical.yml` with that digest and the exact active
   historical source-version UUID. The workflow verifies the current DEV digest,
   runs one temporary PRE_DEPLOY job, and restores the captured normal topology.
6. Verify the historical run, eleven persisted passing quality results, RAW and
   CONFORMED counts, era range, provenance and the Data Explorer. Confirm the
   current-era 5,045-record publication is unchanged. Local tests alone do not
   constitute this runtime evidence.

## Acquisition and publication

The command rejects PROD and checks the active approved version before any source
request. It acquires deterministically ordered pages with the existing immutable
artifact and request ledger. Publisher metadata fingerprints and total counts
must remain stable across capture. The explicit safety bound is one million rows;
exceeding it requires a reviewed change, not a silent partial publication.

Historical data uses separate RAW, STAGING candidate and retained CONFORMED
relations. A resource-specific 30-minute lease serializes operations; publication
rechecks approval, quality, lease and expected pointer revision within the
transaction. Failed validation or copying cannot replace the published snapshot.
An identical source-content multiset does not advance the pointer.

The eleven checks cover nonempty RAW, row reconciliation, payload/lineage multiset,
required provenance and explicit value states, registered lineage, source hashes,
exact duplicate hashes, value preservation, 2008–2021 years, the correct source
endpoint and publisher row-count reconciliation. Duplicate hashes block review;
they are not silently removed or interpreted as a verified natural key.

Zero, explicit null, missing, unknown, suppressed and not-reported values remain
distinct. FIPS remains text. The explorer labels county of residence and the
2008–2021 era; reported cases are not infection incidence or exposure locations.

## Rollback and recovery

The scoped V046 recovery initially created the historical published view under
AccountAdmin. DEV-only V048 grants the dedicated governed-view owner only the
three underlying reads needed by that view, transfers its ownership while
preserving current grants, and removes AccountAdmin's temporary source-version
read. It does not change data, publication pointers, runtime writes, or PROD.

Use `pipeline rollback-cdc-historical --source-version-id <approved-uuid>
--ingestion-run-id <retained-run> --expected-revision <current-revision>` only for
an explicitly selected retained historical snapshot. It revalidates retained rows
and approval, then appends a publication event. It never deletes RAW, artifacts,
quality results or snapshot history. Before first publication there is no earlier
historical snapshot to roll back to; do not claim a same-snapshot repoint proves
rollback to different data. Exercise changed/failed/rollback behavior in isolated
DEV fixtures before claiming operational readiness.

For a failed acquisition or validation, inspect governed evidence and resolve the
failure before authorizing another acquisition. Do not start discovery or another
registration backfill. PROD promotion and unattended refresh remain separate work.
