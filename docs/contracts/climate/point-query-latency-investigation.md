# January PROD point-query latency investigation

Status: hypothesis and SELECT-only candidate, not an approved migration. No
Snowflake session, PROD change, timeout extension or API activation is authorized
by this document. Owning issue: DATA #443; consumer: API #84.

## Retained evidence

Owner-supplied `Untitled 33_2026-10-16-0326.csv` contains one successful query
history row for `01c7c3ed-030c-3e2e-0064-2d0701278042`: 8.206s total,
2.162s compilation, 5.914s execution, 0.130s provisioning, zero queueing,
141,499,392 bytes scanned, COMPUTE_WH X-Small. These are observed facts, not
operator attribution. Neither warehouse undersizing nor failed predicate
pushdown follows from these totals.

Owner-supplied `Untitled 33_2026-10-16-0319.csv` records COMPUTE_WH STANDARD,
X-Small, auto_suspend=600, auto_resume=true, generation blank, resource monitor
null. A blank generation is not independently interpreted as a generation
guarantee. No grant or warehouse change is proposed. Actual billed costs remain
unknown; public planning rates are not contractual billing evidence.

Neither CSV contains table/operator scans, pruning, join cardinalities, spills
or operator times. The required retained Query Profile is still missing. Do not
invent these metrics or call the static source a Snowflake query plan.

## Dependency audit at e6516fa

`PRESENTATION.CURRENT_CLIMATE_COUNTY_DAY_OBSERVATIONS_V` is defined by immutable
V152. Its dependencies are stored tables, not another climate view:

1. SEMANTIC_RELEASE_POINTER: pointer_key ATLAS chooses the current release.
2. SEMANTIC_RELEASES: matching release, PUBLISHED, extension contract v2.
3. GOVERNED_SOURCE_RECORD_REVISIONS: exact capture ID, ingestion run, NOAA
   artifact ID/hash, January resource key and definition version 2.

V071 defines both presentation tables; V103 defines the revision ledger. No
clustering key, search optimization or relational county/day/measure serving
index is declared on that ledger in canonical migrations. Live physical changes
have not been inspected. Snowflake primary-key declarations here are not proof
of an indexed lookup or uniqueness enforcement.

V152 expands capture_ids into 389,856 membership rows, independently expands four
metadata definitions, joins revisions on four lineage scalars, and checks the
canonical revision measure against approved metadata. The final county/date
expressions directly reference the revision payload. The final measure ID is
re-extracted from metadata, making its revision-side filter path indirect.
SQL CTE structure does not establish physical materialization or filter order.
The optimizer may already infer every predicate. Repeated physical release
scans, exploding joins and absent pruning are unverified.

## Minimal candidate and alternatives

`sql/january_climate_point_query_candidate.sql` changes only the final measure ID
projection to the canonical expression over record:measure. The existing inner
join still requires that exact value to equal the approved metadata measure ID.
Frozen membership, all lineage guards, output fields/types, values, zeros,
negative temperatures, missingness, out-of-coverage, availability dates and
metadata remain unchanged. Metadata view, grants and release pointer are untouched.

Expected effect, **if the plan currently fails to infer that filter**: expose
the measure predicate directly on the revision payload and reduce rows reaching
the join. No numerical speedup or sub-five-second result is predicted. This may
do nothing if Snowflake already pushes it down. Offline SQL equivalence tests
are semantic evidence only.

Do not replace frozen membership with run-only selection. Replacing the large
FLATTEN with ARRAY_CONTAINS is not this candidate: it trades row expansion for
per-record large-array evaluation, can regress broad reads, and changes duplicate
membership multiplicity outside validated manifests. A new materialized serving
table, clustering/search service or refreshed cache is a larger governed change;
none is justified before scan/operator evidence. No such infrastructure is added.

## Required profile evidence and decision

Inspect the retained Snowsight Query Profile for the exact query above. Record
object names; scan predicates; partitions scanned/total and bytes by object;
FLATTEN output; every join's inputs/output and conditions; operator time; local/
remote spill; and cache contribution. Preserve no raw observation records in a
public report. SQL alternative, **not executed or authorized here**:

```sql
SELECT step_id, operator_id, parent_operators, operator_type,
       operator_statistics, execution_time_breakdown, operator_attributes
FROM TABLE(GET_QUERY_OPERATOR_STATS('01c7c3ed-030c-3e2e-0064-2d0701278042'))
ORDER BY step_id, operator_id;
```

Snowflake documents a 14-day retention window and OPERATE/MONITOR warehouse
privileges for this function. Do not assume the API reader has them, add grants,
substitute an admin identity or run a new metadata session without approval.
See https://docs.snowflake.com/en/sql-reference/functions/get_query_operator_stats.

If revision scan filters already include the canonical measure, reject this
candidate as an unproven optimization. If membership expansion or repeated
release-manifest processing dominates, design the next smallest change using
that actual plan. If compilation dominates after execution improves, include
compilation in the API latency decision; do not report execution-only success.

## Controlled comparison proposal — separate authorization required

After the profile supports a candidate, pin its reviewed commit and SQL checksum.
Use the existing authorized service initialization with OH_LYME_PROD_READ on
COMPUTE_WH X-Small STANDARD and the same PROD account/database. No credentials,
warehouse size, grants, API configuration or deployed statement limits change.

One proposed session, five read-only statements, no retries:

1. Verify current user, role, database and warehouse; stop on mismatch.
2. EXPLAIN JSON for the exact baseline point SELECT.
3. EXPLAIN JSON for the equivalent candidate point SELECT.
4. Execute baseline point SELECT once, fetching at most one release ID.
5. Execute candidate point SELECT once, fetching at most one release ID.

Both point queries select county 48277, 2025-01-17, nclimgrid_prcp_county_day.
Set USE_CACHED_RESULT=false in the connector's approved session parameters;
do not flush warehouse caches, suspend/resume or alter objects to manufacture a
cold cache. Record order/cache state; a single pair is preliminary, not p95 or
durable cold-cache acceptance. A separately approved diagnostic statement cap
of 60s and 180s process deadline plus 15s grace would accommodate the known 8.206s
baseline; this does not change the deployed API's five-second cap.

Capture actual query IDs and client elapsed time from the connector. Obtain
total/compile/execution/provision/queue times, bytes, partitions, join cardinalities
and operator times through owner exports of the retained profiles; those exports
are not hidden additional SQL in this five-statement session. Any programmatic
history/operator queries require their own explicit statement/resource scope.
Require the same release ID
and a reduction in the implicated work. Target total server latency below 4.5s
to leave margin under the existing five-second API cap; a slower result fails.
The historical 8.206s row is retained; do not pretend two differently cached
executions are a statistically controlled SLO measurement.

Planning reservation for that proposed session: at 1 credit/hour and the owner's
$2/credit public planning rate, 195s process/grace plus 600s observed idle tail
is $0.441667 compute; adding an explicitly assumed 25% planning contingency is
$0.552084. Proposed maximum $1 within the existing cumulative ceiling, subject
to reconciliation before dispatch. This is not a contractual bill or hard
warehouse-wide spend cap; unrelated shared workload and actual cloud-services
billing remain unknown. No prior consumed allowance is reused.

Only after the candidate demonstrates benefit and complete contract parity:
create a reviewed forward-only view migration, preserving COPY GRANTS and the
existing role/ownership path. Do not edit V152. Verify pending migrations and
expected checksum; use existing protected deployment with a separately scoped
mutation allowance. Rollback is an explicitly approved restoration of the prior
V152 view definition with COPY GRANTS, never migration-ledger deletion or pointer
change. Deployment/rollback execution inputs cannot be finalized before choosing
a proven candidate and its actual migration checksum.

Finally authorize one actual deployed API startup probe under the existing
five-second cap. Keep the flag off until that passes; then use separately
authorized controlled enablement and bounded decoded HTTP scientific acceptance
for all four measures. Disable promptly on HTTP acceptance failure. Keep API #84
open until actual service and HTTP evidence pass. No ingestion, publication,
historical backfill or CDC consumer-control change is part of this work.
