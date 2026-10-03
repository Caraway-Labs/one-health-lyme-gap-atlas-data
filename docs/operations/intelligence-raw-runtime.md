# Intelligence raw expiry runtime review

DATA #135 retains eligible normalized/native metadata and provenance long term,
while raw RSS/Atom copies expire 30 days after the original successful capture.
This change integrates that policy with existing ingestion paths. It does not
activate a source, schedule ingestion or cleanup, apply SQL, change a bucket
lifecycle, delete real data, or change scientific ingestion retention.

## Composition and authority

An explicitly composed feed runtime supplies one `FeedRawRetention` controller
to `IntelligenceFeedAdapter`, `IntelligenceStageEffects`, and a corresponding
`IntelligenceMemoryCheckpoints`, `IntelligenceFileCheckpoints`, or
`IntelligenceSnowflakeCheckpoints`. The orchestrator refuses live feed work
without this controller and refuses an incompatible checkpoint store. Generic
scientific checkpoint stores preserve their existing behavior.

The controller receives independent current registry and reviewed retention
policy lookups. Neither source YAML nor payload dates confer authority. The
adapter creates an immutable lease and issued validation receipt only after a
bounded successful acquisition. Payload verification checks that issued receipt
before base64 decoding. A 304 records revalidation against the same original
lease; retries, checkpoint resaves and resume cannot change its deadline. A
fresh successful 200 creates a new capture, even when its bytes match.

`SQLiteRawLedger` is a caller-owned durable local metadata store for DEV/offline
integration. Its separate audit database commits pending cleanup intent even
if physical deletion crashes and the main guard rolls back. PROD requires the
shared `SnowflakeRawLedger`, whose exact runtime role, suffixed database and
transaction context are checked before private ledger SQL. Both implementations
use an immutable checksum-verified document ledger and bounded inventories.
Do not hand untrusted code either ledger's writable connection or authority
callbacks: these are trusted runtime components, not an authorization service.

## Covered boundaries

| Raw copy | Registration and read boundary |
| --- | --- |
| Feed object | Commit private copy claim before the existing Spaces PUT; guard PUT and replay GET |
| Warehouse XML-bearing payload | Bind run/lease and commit claim before save; check independently before SELECT |
| Local JSON payload | Claim final and staging paths before atomic save; guard before JSON read |
| Binary replay and members | Claim physical replay locator; guard before save/load/checksum reads |
| Conditional cache | Claim before body copy; gate before parsing; expire bytes and validators before fresh request |
| Orchestrator memory and resume | Claim managed buffer; gate completed ACQUIRE before any raw fallback; release buffer at execution exit |

Atomic staging files use explicitly claimed raw temporary names. A hard crash
before rename leaves a discoverable claim; exact cleanup can remove that staging
copy after its original lease expires. Completed rename leaves an already-absent
staging claim, preserving crash accounting without retaining duplicate bytes.
An incomplete ACQUIRE may acquire a genuinely fresh 200 on retry. Immutable
run bindings append a generation under the guard; prior leases/claims remain
unchanged. Completed ACQUIRE resume selects its existing capture and never
re-fetches solely to extend expiry. An old binding cannot overwrite the current
generation's payload.

Claim registration commits **before** physical writes. A second guard rechecks
expiry and rights and remains held during I/O. Ambiguous provider failures retain
their claim. Nested uncommitted copy writes fail closed. Cleanup acquires the
same guard, so it cannot race a registered reader/writer or delete bytes protected
by a live claim under another logical copy kind. External processes bypassing
this composition are not covered. Retained inventories fail closed beyond
100,000 documents; compaction requires separate review, never silent eviction.

Managed cache/memory buffers have host-hash/PID/nonce locators. Release records
are immutable and idempotent; released locators cannot be reused. Unknown live
owners are not reported as deleted. Runtime process liveness checks are read-only.
These gates control managed references and reads, not secure memory erasure or
arbitrary copies held outside the runtime. Expired resume records a redacted
policy failure with `new-approved-feed-run`; valid normalized checkpoints and
provenance survive. Legacy raw captures without leases fail closed.

## Cleanup and recovery

`cleanup` requires an exact environment/source/inventory-bound approved plan.
There is no default approval. Before each physical mutation it independently
commits a redacted pending receipt; it subsequently appends deleted,
already-absent or failed outcomes. Audit failure stops further mutations. A
crash after physical deletion leaves pending intent; retry with the same plan
and unchanged inventory records already-absent safely.

`FileRawDelete` accepts only raw payload/binary/member files in an explicitly
owned root, rejecting escapes and symlinks/junctions. `ObjectRawDelete` accepts
only the exact configured bucket/prefix/environment/source/run/content-hash
key. Neither deletes normalized checkpoints or provenance. Buffer cleanup uses
the owning controller. `WarehouseRawDelete` calls the reviewed owner-rights
procedure under the existing guard; runtime never receives direct DELETE.

## Concrete release gate

The unnumbered, unapplied
[`raw-runtime-schema-review.sql`](../contracts/intelligence/v2/raw-runtime-schema-review.sql)
contains the proposed private document/audit/exact-plan-approval tables and
scoped checkpoint purge procedure. It supersedes the earlier preparation-only
fielded-ledger proposal. No migration number or deployment slot is claimed.

Before DEV activation, the parent must review this exact schema/procedure,
allocate a forward-only migration, and approve intended roles: runtime gets
private document SELECT/INSERT, audit INSERT, existing V135 guard access and
procedure USAGE; a dedicated least-privilege purge owner gets only the procedure's
dependencies; a separate trusted operator can insert reviewed exact-plan
approvals. Runtime cannot approve plans. Validate transaction behavior,
negative-role checks and bounded synthetic restart/readback under the intended
DEV identity. Do not use Alpha or ACCOUNTADMIN as a runtime substitute.

Before any real cleanup, separately authorize the exact private inventory and
plan, verify pending/outcome audit durability and recovery, and coordinate the
shared deployment slot with the parent (PubMed #495/#528). PROD deployment,
DDL/grants, source activation and real deletion each remain unapproved here.
Existing NIH access and generated PubMed RSS URL blockers remain unchanged.

## Evidence

Offline tests exercise actual File/Memory checkpoint methods and fresh-object
restart/resume, expiry before warehouse/object access, 304 cache behavior,
forged or revoked capture authority, ambiguous writes, durable claim visibility,
idempotent buffer release, exact cleanup scope and crash-after-delete recovery.
All deletions are synthetic files in pytest temporary roots or provider doubles.
These tests do not substitute for Snowflake SQL execution or intended-role DEV
integration, and no production enforcement is claimed.
