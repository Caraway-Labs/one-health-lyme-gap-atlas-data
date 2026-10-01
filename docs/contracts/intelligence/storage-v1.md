# Intelligence storage v1 - implementation awaiting release review

DATA #135 implements the accepted #131 contract. V135 is the provisional next
migration after current V134; reconcile the owning migration inventory before
merge. It has not been applied in DEV or PROD. No indexing/clustering is added
without volume/query evidence.

The human-managed source-version registry is read-only to the runtime. Registry
documents, checksums, approval/change-review references and trust review stay
immutable by version. The runtime validates exactly one matching source version,
its checksum and permissions before persisting a public-safe item. It cannot
create or approve registry rows.

Before item insertion, `INTELLIGENCE_ACQUISITION_CONTEXTS` pins the private v1
source ID/version/registry checksum, requested/effective URL, status/time,
HTTPS capture mode and raw SHA to the actual run/artifact. Registration verifies
`INGESTION_RUNS.resource_key == source_id` and the RAW artifact's joined request
endpoint/checksum under the writer guard. Exact receipt replay is allowed; changed
context is rejected. Item writes independently check this receipt against the
current reviewed registry and pinned retrieval time. Unchanged bytes cannot be
relabelled as another source/version. Legacy captures without receipts and
fixture-mode manifests fail closed. Runtime has only SELECT/INSERT on the private
receipt table; consumers receive no access. The provisional migration remains
unapplied and requires parent reservation and grant review.

All public store operations redact connection creation, context entry/setup,
lookup, transaction and context cleanup errors to finite diagnostics, without a
raw exception chain. Rollback/cleanup failures preserve the original failure.
A cleanup error after a successful commit is reported as failure; callers must
retry the immutable unit and rely on exact replay, never assume no rows committed.

Publication content revisions live separately from run-pinned captures. Captures
retain source/version, transport, canonical dates and missingness, permitted text,
tag origin, run/artifact provenance and limitations. A repeat fetch gets a new
capture; unchanged content keeps its revision. Cross-channel captures share an
article identity when a reviewed canonical URL supports it, without losing
attribution. Conflicting publisher dates/titles remain distinct revisions.

The writer validates source/transport/excerpt rights, deterministic hashes,
and real run/artifact/checksum references, executes bounded writes in one explicit
transaction, and rejects conflicting replay instead of overwriting immutable rows.
Snowflake ordinary keys are documentation, not uniqueness enforcement. A
migrator-created singleton guard is updated before identity lookups, serializing
all cooperating writers through the transaction's UPDATE resource lock. Runtime
cannot insert or delete guard rows. Missing/duplicate guard rows fail closed.
Every invocation uses a fresh owned connection and rejects an already active
transaction, wrong database, or a role other than the intended environment's
runtime. Lock wait is five seconds and statements are limited to 120 seconds.
Writes cap at 1,000 items and 10 MB of normalized JSON per run/source unit.
Production execution remains guarded and requires the parent-controlled
deployment path.

The consumer view retains each revision/source attribution and joins the pinned
current approved registry version; a newer pending/paused version hides old
captures until an approved version is captured again. It exposes no raw feed
bytes, private artifact locations,
mailbox/provider IDs, recipient lists or headers. Readers receive only view SELECT,
not raw/capture-table access. No reader/writer/owner roles are created. Publisher
date fields are canonical UTC strings in the consumer projection, preserving
the contract's fractional precision and explicit SQL nulls; warehouse retrieval
timestamps are internal ordering metadata. No conflicting publisher revision is
chosen as authoritative solely by arrival time.

`IntelligenceStageEffects` injects this writer into the existing orchestrator:
NORMALIZE validates permitted items, LOAD commits revisions/captures atomically,
and later stages identify the approved public projection. Existing private
artifact registration is reused only after an authoritative source lookup and
an injected policy check binding the reviewed retention reference to the actual
artifact retention class. No generic seven-year policy is silently approved.
Unreviewed scientific quality rules and partitioned effects fail closed. The
composition is not enabled by default source YAML or CLI execution.

Normalization is owned by DATA #132. This PR is stacked on #132, contains only
storage/migration/effects changes relative to that branch, and must follow it
through review and current-main reconciliation. This avoids two divergent
canonicalization implementations. The current migration inventory was refreshed
from origin/main `fba0efb`; its last migration remains V134. V135 is provisional
until the parent coordinates the deployment/migration slot.

The concurrency design follows Snowflake's documented UPDATE resource-lock and
READ COMMITTED behavior: https://docs.snowflake.com/en/sql-reference/transactions.
Intended-role tests must verify concurrent writers/read visibility with the
actual account's session read-consistency behavior; the in-memory ledger double
does not prove warehouse locking or grants. No account consistency setting is
changed or assumed globally.

Retention/deletion policy remains source-specific and must resolve to an actual
approved policy before live acquisition/publication. This change does not invent
retention durations or authorize deletion. Disabling a source or reader view
stops new delivery without rewriting old evidence. Forward-only migration and
intended-role DEV/PROD integration evidence remain release gates; fixture and
transaction-failure tests are not a substitute for that evidence.
