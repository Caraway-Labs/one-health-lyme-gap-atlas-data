# Intelligence source health v1 — DATA #136

This is an internal, inactive health path over the accepted DATA #131 health
schema and #535/#536 ingestion interfaces. It adds no ingestion framework,
schedule, source approval, alert sender, warehouse object, grant or deployment.
Only delivered RSS/Atom paths are supported. Email/web remain gated stories.

## Evidence and interpretation

`health_from_run` consumes the existing durable `RunState` checkpoints, atomic
intelligence LOAD receipt, matching acquisition context and accepted normalized
records. It rejects dry-run/planned receipts, wrong source/version/context,
wrong run/artifact/hash, impossible counts and future/out-of-order chronology.
A source-local history binds the complete registry checksum; history cannot be
relabelled after a source-policy/version change. Its caller must resolve that
registry from the authoritative approved registry, not a self-approved file.

The source-local accepted revision set distinguishes first observation from
repoll. A globally existing revision may still be new for this source, so a
zero global `revisions_inserted` count never proves quiet. Successful retained
304 captures use the same accepted records/receipt path. No new revision means
quiet; a valid empty capture is also quiet. Rejected rows mean partial failure,
never quiet. Existing RSS parsing is all-or-nothing; the partial-count input is
available only for a future trusted composition that supplies actual rejected
counts. It does not claim partial item rejection is live today.

`last_item_observed_at` is accepted retrieval chronology, not publisher time.
Delayed publication dates remain untouched on normalized evidence. Repeated
polls do not advance the last new-item time. Coverage start/end describe the
accepted capture envelope, not continuous publisher availability or completeness.
`last_fetch_success_at` advances only with validated acquisition and completed
atomic storage evidence, not an HTTP 200 that failed parsing or loading.
Failures preserve last valid items/revision history and all prior good timestamps.
Post-LOAD QUALITY/PUBLISH failure is conservatively partial/storage, not healthy;
its committed load evidence is preserved for recovery.

One completed checkpoint attempt is counted once. The private attempt key and
input checksum bind run, stage, attempt/status, context, accepted items and
receipt/failure metadata. Same-attempt changed evidence fails closed. Replay
updates observation time only; it does not refetch, rewrite publisher chronology
or increment failure count. Durable cross-process history, immutable snapshots,
concurrent writers and replay serialization still require an approved store;
this module does not invent or authorize one.

## Reviewed freshness and maintenance policy

The optional `HealthPolicy` binds the exact registry checksum and an authoritative
review callback. It has no default thresholds: policy reference, escalation owner,
fetch grace, optional item grace and failure threshold must be supplied from a
reviewed immutable policy. The synthetic policy in tests is not a pilot decision.

For active sources, fetch staleness is strictly greater than reviewed registry
poll cadence plus approved grace; equality is within budget. Manual sources do
not imply a polling commitment. Publication staleness additionally requires a
known publisher-declared/reviewed cadence, an explicitly approved item grace and
a previously observed item. Unknown cadence or absence of any initial item is
missing evidence, not an invented stale deadline. Arbitrary fractional UTC
precision is preserved at boundaries. Missing reviewed thresholds create no
stale classification or incident. An existing fetch/parser/policy/storage failure
is never hidden behind quiet/stale freshness classification.

Health states map finite outcomes: malformed XML → malformed/parser; unsupported
or ambiguous structure → parser_drift/parser; denied access → access_expired/fetch;
429 → rate_limited/fetch; network/upstream failure → upstream_outage/fetch;
policy refusal → access_expired/policy; failed storage → partial/storage. The
accepted v1 schema has no distinct policy_blocked state; its policy category,
diagnostic and next action provide that distinction. Inactive candidate/paused/
retired sources project paused with review-source-policy; health never activates
or automatically disables the registry. Retry-deferred remains a bounded fetch
failure, without claiming the provider cause is known.

Retries/backoff remain #535's source-reviewed maximum attempts/deadline/Retry-After
handling. Health reduction performs no retry. Incident descriptors follow the
existing finite event/stable deduplication-key convention, with source/version,
reviewed policy, state and first unhealthy episode time. Repeated failures or
stale polls share one key; recovery followed by a new failure has a new episode.
Descriptors and escalation-owner metadata are not permission to send alerts.

Next safe actions are finite review-parser, review-access, review-source-policy,
defer-within-approved-budget, resume-storage-checkpoint and review-source-freshness.
Disable/recovery procedure: the owning reviewed registry process pauses the source
(new reviewed policy/version as required), retains last good records, corrects
access/parser/storage under its normal approval path, then allows a bounded manual
capture through the existing orchestrator. Successful accepted replay clears the
failure episode; it never backdates or fabricates publication freshness.

## Telemetry and acceptance evidence

`record_health` accepts the existing telemetry composition's event emitter. Events
include only source/version/state, finite diagnostics, counts and an incident key;
no article text, publisher URL, mailbox, subscriber data or provider exception is
sent. An emitter outage returns false separately and preserves primary health.
The caller must record/retry that telemetry incident through existing conventions;
it must not relabel a source outage as healthy or issue an uncontrolled alert.
No new monitoring platform or external emitter is wired.

| #136 acceptance | Offline evidence | Remaining gate |
| --- | --- | --- |
| Source cadence/state, fetch/item, versions, failures, coverage | Accepted v1 health document plus source-state/cadence envelope; source-bound history | Authoritative registry and durable history integration |
| Quiet vs stale/drift/access/rate/outage/malformed/partial | Independent reduction tests and existing checkpoint diagnostic mapping | Actual approved sources and transport outcomes |
| Reviewed controls and dedup/escalation | Explicit reviewed policy seam, episode keys, finite actions; existing retry budgets | Actual thresholds, owner, channel/suppression and registry decisions |
| Preserve good normalized evidence | No item mutation; failures/replays retain good chronology; source-local revision history | Intended-role concurrency/recovery proof |
| Boundary/delay/failure/outage/recovery/redaction tests | Exact fractional cadence boundary, quiet controls, delayed publication, repeat attempts, telemetry outage and new episode tests | Real runtime telemetry evidence |
| Accepted/rejected/failed execution evidence | Real orchestrator + effects + store with HTTP/object/warehouse seams; accepted receipts and fresh resume; synthetic partial/failure controls | DEV/PROD execution and county consumer demonstration |

Keep #136 open. Tier A fixtures are not source activation, Snowflake authorization,
production delivery or public-health impact. Branch is stacked on exact reviewed
#536 `cbdb17b` (and #535 `91347864`), rooted in refreshed main `fbe8c55`.
#535→#536 order remains; #536 migration/security/live gates and shared PubMed
#495/#528 stable-production deployment hold remain under parent control.

## Review corrections and chronology limits

Processed-attempt identities/checksums are retained as a bounded, complete private
history (up to 100,000 attempts), not just the last attempt. Freshness-only
reduction preserves this history and the latest accepted event time. A replay of
any processed success/failure leaves later health, failure count, accepted-item
chronology and recovery status intact; changed evidence for that identity fails
closed. An unseen event older than the latest accepted event is rejected rather
than applied to current health. Equal event times remain possible with coarse
clocks; distinct authoritative attempt identities distinguish genuinely new work.
The supplied history must be loaded/persisted atomically by the eventual approved
composition. A truncated, nonauthoritative or reset history is not replay proof;
no production store or permissions are added here.

Every supplied checkpoint start/completion must be valid, nonfuture and correctly
ordered. A completed LOAD needs an actual start and completion; retained fetch
must not occur after its storage completion. Failed orchestrator checkpoints
currently retain start but no completion. Their start is explicitly a lower-bound
event time, never an invented failure-end timestamp. A concurrent/out-of-order
failure whose exact finish cannot be established may need operator reconciliation;
this reducer fails closed rather than claiming chronology it cannot prove.

Omitting policy preserves the previously reviewed stale classification/reference;
it cannot produce quiet or recovery from the same old fetch. A newly reviewed
policy may reclassify freshness, but that is not a successful-fetch recovery.
Actual recovery requires accepted new successful attempt evidence. Missing policy
produces no new incident authorization; the telemetry/notification owner must keep
policy availability separate from source health.

Retrieval and persistence have separate clocks. An acquisition/parser failure
remains unresolved until a verified accepted capture was fetched after that
failure; finishing LOAD for an older retained capture preserves its committed
items and timestamps without clearing the later access failure. A successful
QUALITY/PUBLISH resume uses its own terminal checkpoint identity and completion
time, rather than replaying the older LOAD event. It can resolve a persistence
failure without claiming a new retrieval. Both paths preserve complete attempt
history and reject unseen older terminal events.
