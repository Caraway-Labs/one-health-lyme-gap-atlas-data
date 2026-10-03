# Intelligence source-health persistence review

DATA #136 already reduces accepted ingestion receipts into finite health state.
`IntelligenceHealthPersistence` now reads actual durable run/normalized
checkpoints and an independent structured acquisition-context lookup, then
serializes read/reduce/append into a private journal. Raw XML is not needed.
Current source/version authority must match. Only health metadata and revision/
attempt hashes are stored, preserving replay detection across restarts.

Compose `run_binding_lookup=retention.source_binding` with the raw runtime's
durable metadata ledger. The orchestrator pins source ID, registry version/hash,
parser and fetch versions before acquisition. Context-free pre-LOAD failures
require that binding; reconfigured or unbound legacy failures are rejected
before journal writes. Legacy accepted LOADs may use their independently
validated immutable acquisition receipt. Accepted native parser provenance
survives a later QUALITY or other stage failure and journal restart.

`SQLiteHealthJournal` supports caller-owned offline/DEV checkpoint integration.
`SnowflakeHealthJournal` proposes the same append-only semantics under V135's
guard, with exact runtime-role/suffixed-database/transaction checks. Wrong owner
roles and Alpha fail before private SQL. No DDL, grants or source activation
have been executed. The unapplied `health-persistence-schema-review.sql` requires
parent-coordinated migration review and actual intended-role DEV proof.

The service explicitly supplies `policy=None`: cadence and raw observation
times remain visible, but no stale threshold, failure notification, escalation
owner or automatic pause/recovery policy is invented. Reviewed alert ownership
and thresholds are still missing. Notifications remain disabled. Optional
existing telemetry emission occurs after the durable commit; an outage does not
replace health or silently count another attempt.

Offline tests read actual FileCheckpointStore evidence and exercise new-journal
restart, duplicate-attempt replay, concurrent recording, conflict/out-of-order
rollback, corruption/source-authority rejection, policy-free observation and
telemetry outage. Normalized items/provenance are neither deleted nor rewritten.
Native accepted items report their actual parser version; empty polls preserve
the last known parser. No notification delivery, scheduler or API publication
is introduced. Health recording is explicitly composed, not hooked into shared
production jobs. Complete #136 acceptance still needs real delivered-transport
run/health readback, API projection review and owner-approved maintenance policy.
