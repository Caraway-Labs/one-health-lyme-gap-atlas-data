# Intelligence storage v1 — proposed implementation

DATA #135 implements the accepted #131 contract. V135 is the provisional next
migration after current V134; reconcile the owning migration inventory before
merge. It has not been applied in DEV or PROD. No indexing/clustering is added
without volume/query evidence.

The human-managed source-version registry is read-only to the runtime. Registry
documents, checksums, approval/change-review references and trust review stay
immutable by version. The runtime validates exactly one matching source version,
its checksum and permissions before persisting a public-safe item. It cannot
create or approve registry rows.

Publication content revisions live separately from run-pinned captures. Captures
retain source/version, transport, canonical dates and missingness, permitted text,
tag origin, run/artifact provenance and limitations. A repeat fetch gets a new
capture; unchanged content keeps its revision. Cross-channel captures share an
article identity when a reviewed canonical URL supports it, without losing
attribution. Conflicting publisher dates/titles remain distinct revisions.

The writer must validate source/transport/excerpt rights, deterministic hashes,
and real run/artifact/checksum references; execute bounded writes in one explicit
transaction; and reject conflicting replay instead of overwriting immutable rows.
Snowflake ordinary keys are documentation, not uniqueness enforcement. Production
execution remains guarded and requires the parent-controlled deployment path.

The consumer view retains each revision/source attribution and joins the pinned
registry version. It exposes no raw feed bytes, private artifact locations,
mailbox/provider IDs, recipient lists or headers. Readers receive only view SELECT,
not raw/capture-table access. No reader/writer/owner roles are created.

Retention/deletion policy remains source-specific and must resolve to an actual
approved policy before live acquisition/publication. This change does not invent
retention durations or authorize deletion. Disabling a source or reader view
stops new delivery without rewriting old evidence. Forward-only migration and
intended-role DEV/PROD integration evidence remain release gates; fixture and
transaction-failure tests are not a substitute for that evidence.
