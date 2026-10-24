# Additional CDC DEV qualification: exact operational handoff

Scope and US$5/four sequential capture/repoll runs are owner-approved by
`Sentinel_dafa6b0ae8108191b308b077e58b0f27` at 2026-10-22 01:17 UTC.
No additional policy/budget approval is being requested. Runs used: 0; publisher
requests used: 0. Read-only preflight warehouse cost remains unreconciled.

## Completed bounded inspection

Existing `ATLAS_DEV_READ` verified MATTHEWCARAWAY / OH_LYME_DEV_READ /
ONE_HEALTH_LYME_GAP_ATLAS_DEV / OH_LYME_DEV_INGEST_XS_WH. It can read the
migration ledger. V069, V135, V142 and V143 match the repository's pinned
checksums. The existing DEV owner connection also verified its actual identity
and exposed runtime SELECT/INSERT/UPDATE on GOVERNANCE.INGESTION_RUNS.
Read/owner SHOW metadata does not expose all intelligence storage/cleanup
objects; this is insufficient visibility, not proof those objects are absent.
No grants, schemas, approvals, jobs or stored data were changed.

## Finalized review package

`config/intelligence/cdc-mmwr-source-v1.json` and
`cdc-newsroom-source-v1.json` record the actual owner decision, manual state,
official publisher trust and no inferred topics/geographies. Exact hashes:

- MMWR: `61edf259b572c7ef119ee7b79a9c4fc716ec39785d36140de76a7e6d06eacbf2`
- Newsroom: `2424b80aa8e4bb392e156c23618f3f121464e7bd2261395f52bac33e4dd8e2b6`

`additional-cdc-dev-policy-receipts.json` binds those hashes to the eight-field
native policy, source-specific restricted raw policy and 3000/32MB limits.
It is intentionally not loaded by canonical_pilot before operational review.
No live registry row has been inserted. Historical candidate proposals remain
separate evidence; their pending fields do not supersede the actual decision.

## Concrete remaining execution prerequisites

1. Under the existing DEV pipeline service (OH_LYME_DEV_PIPELINE_SVC /
   OH_LYME_DEV_RUNTIME), verify V135/V142 object shapes and existing exact
   privileges. Targets: GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS (SELECT),
   INTELLIGENCE_WRITE_GUARD (SELECT/UPDATE), INTELLIGENCE_ITEM_CAPTURES and
   INTELLIGENCE_ACQUISITION_CONTEXTS (SELECT/INSERT),
   CONFORMED.INTELLIGENCE_ITEM_REVISIONS (SELECT/INSERT),
   GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS (SELECT/INSERT),
   INTELLIGENCE_RAW_RETENTION_AUDIT (INSERT), and existing run/checkpoint/artifact
   surfaces. Compare against the deployed contracts; do not apply speculative
   grants based on role-filtered metadata. Existing permission failure must be
   reported with exact object/privilege before any new grant is requested.
2. DEV V143's purge procedure and Python executor currently allow EID Expedited
   only. A separate reviewed forward extension is needed for these two source
   IDs before new raw capture. Exact SQL target is
   ONE_HEALTH_LYME_GAP_ATLAS_DEV.GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT
   (four VARCHAR arguments), plus INTELLIGENCE_RAW_CLEANUP_EXPECTED_HANDOFF_V
   and its immutable handoff attestation. Preserve EID scope, 30-day expiry,
   source/copy/run hash binding, one-source exact plans and zero direct executor
   DELETE. This is a code/security-owner review and native migration/handoff
   gate; no migration number, grant, credential placement, attestation or actual
   deletion is authorized by this document. Do not rewrite V143.
3. Reconcile private accounting, existing XS warehouse headroom and cleanup
   credential source coverage. Existing scripts require independent
   FEED_PREFLIGHT_ACCOUNTING_CONFIRMED evidence; do not set it true from the
   mere existence of the US$5 approval. No LLM work is involved; LLM_BUDGET_USAGE
   is not an RSS cost ledger. Preflight reads are included in reconciliation.
4. After independent review, deploy the exact reviewed immutable DEV image via
   .github/workflows/quality.yml workflow_dispatch deploy_dev=true, environment
   dev, existing app b33dbae7-e243-4e27-b3ca-1018f5897f87. The existing workflow
   temporarily uses a proof job and restores its baseline. Check other sessions
   before dispatch; do not alter PROD or the six production jobs. No dispatch
   or native approval has occurred here.
5. Register only the two exact manual source documents through the existing
   separately authorized registry path, wire reviewed DEV receipts, then run one
   capture and unchanged repoll per source sequentially. Stop the first failure.
   Inspect representative description values in the restricted workflow and
   emit only safe aggregate semantics/length/size evidence publicly. Do not
   silently omit values, truncate descriptions or enlarge 4096/32MB bounds.

## API proof

API #279 still needs the exact union/state read under the actual API service.
API #280 additionally needs the OBJECT_CONSTRUCT_KEEP_NULL description/category
projection, historical null handling and actual continuation across metadata
pages. Native doctl and installed WinPTY both fail before shell/SQL on Windows;
the supported control-panel Console is the smallest verified handoff. Use the
existing API app/component with existing credentials, never an owner READ-role
substitute, copied key, grant or new service. Mock tests are not this proof.
