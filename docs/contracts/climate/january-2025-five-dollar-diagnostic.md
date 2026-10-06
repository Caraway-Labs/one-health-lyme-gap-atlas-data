# Approved read-only January diagnostic

Matthew directly approved up to US$5 for this diagnostic on October 6, 2026
at 05:04 UTC. This is separate from feed and NLCD spending. The US$45 publication
proof and US$100 historical proposal remain unapproved. No publication, source
download, warehouse write, grant, credential configuration or backfill is included.

Use the existing protected `frozen-membership` action on reviewed green main.
The workflow's extra identity session is skipped only for that exact operation;
identity is verified inside the single diagnostic connection. Other operations
retain their existing identity check. Forty SELECT/SHOW statements maximum,
five-minute monotonic/POSIX deadline and job timeout, fifteen-second statement
and socket limits, five-second queue limit, and no driver retry or role fallback.
The actual connector retry-context regression proves the retry increment aborts.

Before source reads, require one supplied billing evidence object:
`unit_price_usd`, `evidence_reference`, `verified_by`, `verified_at`. The reference
must be an actual owner/billing record, not an invented invoice. UTC verification
must be within seven days, and the price must be positive and at most US$20 per
credit. Only its digest is retained. Missing evidence blocks before connecting.
`diagnostic_budget_evidence` is a transient workflow input, not credential setup.

SHOW WAREHOUSES must prove existing Standard Gen1 XS, one maximum cluster,
auto-suspend at most sixty seconds and query acceleration disabled. No ALTER
WAREHOUSE or resource monitor is introduced. Five minutes plus one suspension
minute is at most 0.10 Gen1 compute credit; another 0.10-credit reserve covers
noncompute credit overhead, giving at most US$4 at the accepted price ceiling.
US$1 is reserved for artifact/transfer overhead. These are conservative estimates,
not actual billed charges; unrelated shared-warehouse activity is not attributed
to this session. Unknown/unsupported warehouse facts stop the diagnostic.

Require 1 GiB free temporary disk. There is no new warehouse storage; only the
existing run/artifact/revision/presentation ledgers are read. Full retained IDs,
tuple digest and safe donor manifest use at most 32 MiB and fourteen-day retention.
Oversized output never replaces an earlier artifact. NOAA/TIGER bytes are not
downloaded. No physical-storage expansion is authorized or needed for this read.

The receipt retains actual failing boundary/query ID/effective role and statement
count, elapsed time, verified assumptions and safe artifact hashes. Stage names
cover identity, run, retained artifacts, annual donor, ordered membership, count
and pointer recheck. Error 2003 is OBJECT_OR_ACCESS_UNAVAILABLE; it does not prove
absence or a missing grant. No raw SDK messages, payloads, secrets or endpoints
are included. Principal/query IDs remain in the internal artifact, not stdout.

One bounded QUERY_HISTORY_BY_SESSION read may retain real session execution
time, bytes scanned and cloud-services credits. It uses the same connection and
counts toward all caps; failure/insufficient remaining time stops collection
without retry. Actual invoice/warehouse-credit attribution is explicitly null
until genuine delayed billing evidence is available; a query-history receipt
is not an expense invoice. Preserve actual query IDs for later authorized matching.

No dispatch occurred during preparation. Merge is serialized by the parent after
independent exact-head review and CI. Report a BLOCKED diagnostic separately from
workflow completion; a completed workflow or an estimate is not a successful
membership export or a billed receipt.
