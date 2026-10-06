# DATA #132/#135 canonical DEV composition review

This is an implementation review, not live-source acceptance. Existing
`source run --tier B` and `runs resume` now compose the feed adapter, normalized
item effects, durable retention controller and intelligence checkpoints. The
scientific paths retain their existing composition. Only the approved Vital
Signs and NIH endpoint definitions are eligible for this first small pass.

## Authority inspection

V135 defines `GOVERNANCE.INTELLIGENCE_SOURCE_VERSIONS` as human-managed immutable
reviewed records. Runtime has SELECT only. Its source ID/version/document hash,
approval and trust decisions, rights and current-version checks are authoritative.
`SP_RECORD_SOURCE_REVIEW_DECISION` writes catalog review/source-version objects;
neither it nor any existing CLI command writes the intelligence registry. It
must not be represented as an intelligence registrar. The existing owner path
is an independently reviewed owner/migration registration of the complete V135
registry document, not a runtime operation. No such registration was executed.

The native-v2 implementation accepts a trusted source/version
`NativeMetadataPolicy` lookup. Repository inspection found no production policy
registrar, policy table or source-specific reviewed Vital Signs/NIH policy.
This composition uses a code-reviewed receipt set for that existing lookup,
pinned to the authoritative registry version and document checksum. The empty
initial set is a release gate, not a completed registration outcome.

Matthew's recorded decision truthfully authorizes these two selected publishers,
their exact endpoints, the DEV-only small first test and the separate $5 test
cap. It does not establish a Snowflake registry version/hash or an observed
native field inventory. The ordinary reader cannot inspect the private registry;
its denied lookup proves neither missing rows nor runtime authorization failure.
Before paid execution, the canonical runtime identity must establish the actual
latest source records. If rows are missing, the existing authorized owner must
register reviewed records without giving runtime approval rights.

The fields not yet established for each actual source are:

- Authoritative `registry_version`, document checksum and complete registry
  document, including existing approval/trust receipts, approved hosts, cadence,
  availability verification, terms/conditions, rights/retention reference and
  reviewed transport bounds. These are unverified, not asserted absent in DEV.
- Reviewed native policy identity, exact source checksum, observed inventory,
  permitted/required paths and explicit publisher-date mapping. These are absent
  from checked-in source-specific policies; synthetic fixtures do not supply them.
- Source-specific raw-retention decision reference and artifact retention class
  tied to the approved 30-day controller policy, without scientific seven-year
  retention inheritance.

An owner-reviewed receipt contains `source_id`, actual `registry_version`,
`source_sha256`, `decision_ref`, `retention_policy_ref`, `raw_policy_ref`,
`artifact_policy` and the existing `NativeMetadataPolicy.document()` fields.
It cannot replace registry approval: both reader and writer still query the
current authoritative document. Receipt updates need independent review, not
runtime discovery followed by self-approval.

## Required durable relations: report before allocating a migration

The unapplied `docs/contracts/intelligence/v2/raw-runtime-schema-review.sql`
already specifies the existing components' durable support. No migration number
has been selected and no DDL/grant has been executed.

For acquisition/checkpoint retention, the required relations are:

- `GOVERNANCE.INTELLIGENCE_RAW_RETENTION_DOCUMENTS`: metadata documents;
  runtime needs SELECT/INSERT.
- `GOVERNANCE.INTELLIGENCE_RAW_RETENTION_AUDIT`: append-only metadata audit;
  runtime needs INSERT.
- Existing V135 `GOVERNANCE.INTELLIGENCE_WRITE_GUARD`: existing runtime
  SELECT/UPDATE; no new guard or orchestrator.

The complete reviewed retention lifecycle additionally specifies
`GOVERNANCE.INTELLIGENCE_RAW_CLEANUP_APPROVALS` and
`GOVERNANCE.PURGE_INTELLIGENCE_RAW_CHECKPOINT(VARCHAR,VARCHAR,VARCHAR)`.
Trusted owner approval needs INSERT on approvals; runtime must not receive it.
Runtime needs USAGE on the narrowly scoped purge procedure. Its dedicated owner
needs SELECT on approvals/documents, SELECT/DELETE on existing
`GOVERNANCE.INGESTION_RUN_PAYLOADS`, and SELECT/UPDATE on the existing guard.
Runtime receives no direct DELETE on checkpoint, scientific or item tables.
These are requirements for parent review, not authorization to grant them.
There is no applicable runtime future-table write grant in the migrations.
Parent must reconcile actual DEV objects/privileges and serialize any required
rollout with the shared PubMed deployment slot. Do not create a purge owner or
change security as part of this composition PR.

## Small-pass bounds and acceptance

One invocation makes at most one feed HTTP request: 200 only, no redirects,
retries, article fetch or backfill. Request timeout is at most 30 seconds; raw
body at most 2 MiB; at most 250 complete items; normalized JSON at most 1 MiB.
Oversized feeds fail whole-source acceptance, never truncate. The shared budget
guards owned queries (at most 2,500; each connector timeout at most 30 seconds)
and a 300-second process deadline. The canonical job has a six-minute hard stop
for these definition paths. The deadline also guards registry lookup and replay.
No warehouse resize, suspension or other session cancellation occurs.

The CLI additionally starts an owned-process watchdog before composition and
cancels it only after run/resume returns: blocked connector setup, implicit
transaction SQL and Spaces SDK calls cannot extend that process beyond five
minutes. Connector commit/autocommit/rollback are explicitly deadline-checked
and counted; the runtime session has a 30-second statement limit and detached
query abort enabled. Existing stores' 120-second session setting is clamped
for this pilot only. SDK-internal cleanup queries are not claimed to be fully
counted by the wrapper, and Spaces is not claimed to have a 30-second per-call
limit. The process watchdog, plus server/session limits, bounds those paths.

## Independent review fixes and consumer projection prerequisite

An incomplete ACQUIRE checkpoint no longer permits refetch when the immutable
Snowflake payload is already committed. The checkpoint store first checks the
durable binding and guarded immutable payload. The adapter verifies the original
capture, and the existing intelligence store verifies the actual run/artifact
and acquisition context. Resume completes ACQUIRE without HTTP, raw PUT, payload
overwrite, changed attempt IDs, or lease/expiry renewal. The regression executes
the actual Snowflake JSON save/load methods against an immutable SQL seam and
injects the post-payload stage-checkpoint failure; file overwrite is not its
payload implementation.

These definitions now target the existing
`PRESENTATION.INTELLIGENCE_FEED_V2` contract. Publication rejects a version that
does not match its projection. V135's original unfiltered v1 view is insufficient
for native-v2 consumer acceptance. Before live v2 LOAD, parent must reconcile
actual view definitions and coordinate the already-prepared
`docs/contracts/intelligence/v2/presentation-projection.sql` delta: replace the
legacy view with its `contract_version='1.0.0'` filter using COPY GRANTS; create
the version-filtered V2 view exposing canonical publisher metadata and empty
derived metadata; preserve private native/XML/rights receipts; grant the existing
READ role SELECT on V2. No table/column change is needed. This is a proposed
view/SELECT-grant delta, not an executed grant or reserved migration. Actual
objects/grants are unverified until approved preflight. Existing API v1 contracts
are not relabelled or changed, and intended-reader V2 readback remains required.

This bounds owned work, not an account-wide charge or invoice. Parent must
track the already-approved six-request/$5 aggregate, prior preflight and idle
time across dispatches. No paid run is released by this PR. Initial and repeat
polls use complete 200 responses; conditional-cache acceptance is not claimed.

Synthetic composition tests exercise actual adapter/controller/effects/store
with offline HTTP, object-store and SQL seams: authoritative version discovery,
missing policy, stale/hash/unapproved/context gates, bounded transport, first
write, unchanged repoll and fresh replay with native metadata/provenance. They
do not establish intended-reader grants or real-source acceptance.

DATA #132 remains open for three genuine bounded DEV feeds and qualification
or explicit block for all five approved publishers. DATA #135 remains open for
real DEV capture/readback, unchanged repoll and attributable legitimate revision
evidence, including native/derived/provenance through the intended consumer.
WHO remains excluded from this first pass; NIAID has no approved endpoint.
