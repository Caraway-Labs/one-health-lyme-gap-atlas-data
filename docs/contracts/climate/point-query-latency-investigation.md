# January PROD point-query latency investigation

Status: actual profile analyzed; SELECT-only candidates, no migration. DATA #443
owns this investigation; API #84 remains disabled. No paid execution, timeout
change, warehouse resize or PROD mutation is authorized by this document.

## Authorized execution checkpoint

The owner subsequently authorized one diagnostic session at reviewed commit
`d1cb811fc50eb09018e0f8957d3f45dcb1683e7b`, maximum seven read-only statements
and $1. The actual session stopped at identity query
`01c7c756-030c-442e-0064-2d07012890a2`: one row returned in 0.110s client time,
but it did not match the pinned user/role/database/warehouse/account/region tuple.
No EXPLAIN or performance SELECT ran. Base-table access remains unverified;
candidate performance, compilation, pruning and spilling remain unmeasured.

The local runner incorrectly persisted identity values only after asserting a
match, so the mismatched field is not in the retained report. Do not infer which
field failed. Reporting now retains all six allowlisted fields and their match
flags before rejection; seven offline expected/mismatch cases pass. The existing
query-result row has been requested from the owner, without rerunning SQL.

An earlier local CLI initialization failure occurred before the connector call,
as reproduced offline with a fake connector. Its files are preserved separately;
it was not a second Snowflake session. The corrected local context then made one
actual connection attempt/session and submitted only the identity SELECT. SQL
submission used the installed connector's explicit `_no_retry=True`; the process
completed in 7.971s without triggering its 180s deadline. No fallback identity,
grant, warehouse or object change occurred. The actual session is consumed: no
further execution is inferred from its unrun statements or the cumulative budget.
The $1 planning reservation remains recorded; actual billed usage is unknown.

## Evidence and reproducibility

### Access correction after the second diagnostic session

The fresh OWNER session passed all six identity fields, including COMPUTE_WH,
then baseline EXPLAIN `01c7c768-030c-43ea-0064-2d0701287512` failed 002003/42S02.
Retained owner export `Untitled 33_2026-10-16-1832.csv` identifies the inaccessible
climate view and explicitly names the primary OWNER role. No benchmark ran.

Retained grant exports independently inspected locally establish the existing
MIGRATION_DEPLOYER permissions; no new Snowflake session was needed:

| Object | Existing MIGRATION_DEPLOYER access | Retained export |
|---|---|---|
| CURRENT_CLIMATE_COUNTY_DAY_OBSERVATIONS_V | OWNERSHIP | 1833.csv |
| SEMANTIC_RELEASE_POINTER | SELECT | 1834.csv |
| SEMANTIC_RELEASES | SELECT | 1834 (1).csv |
| GOVERNED_SOURCE_RECORD_REVISIONS | OWNERSHIP and SELECT | 1834 (3).csv |

All filenames share prefix `Untitled 33_2026-10-16-`. V099/V103 corroborate the
intended table privileges. The stable role model documents MIGRATION_DEPLOYER
holding OWNER, so the new direct OWNER warehouse USAGE should be inherited.
The current inheritance edge is not in these exports: the first live identity
check must confirm effective COMPUTE_WH selection, not presume it from the model.

Minimal proposal: use existing named ATLAS_PROD_MIGRATOR, configured principal
MATTHEWCARAWAY, role OH_LYME_PROD_MIGRATION_DEPLOYER, account TXB06009. Its stored
database and warehouse are unset; explicitly select the suffixed PROD database
and COMPUTE_WH at connection initialization, without altering stored configuration
or credentials. Configured identity is verified offline; live identity/authentication
remain gated. This is an exceptional read-only diagnostic use of a deployment
role, not routine lineage-audit authority or actual API service acceptance.

Do not add revision SELECT to OWNER or READ. No new grant is recommended from
the present evidence. If the effective warehouse check fails, stop; do not add
USAGE or change roles automatically. Only if current evidence then proves a
warehouse grant necessary would warehouse-only USAGE to the existing diagnostic
role be considered separately; it grants lasting compute-use/billing capability,
not additional revision-data access, and requires explicit owner authorization.

Both previous session approvals are consumed. Switching to ATLAS_PROD_MIGRATOR
requires approval of the changed role and one fresh bounded diagnostic attempt.
All seven statement hashes, candidate SQL, point filters and resource safeguards
are unchanged. No alternate identity, grant, data mutation or new paid session
has been used for this reconciliation.

Original query `01c7c3ed-030c-3e2e-0064-2d0701278042` succeeded in 8.206s:
2.162s compilation, 5.914s execution, 0.130s provisioning, no queue, 141,499,392
aggregate history bytes scanned. Existing reader role: OH_LYME_PROD_READ;
warehouse: COMPUTE_WH, X-Small STANDARD. The retained warehouse CSV records
600s auto_suspend, auto_resume=true and blank generation. Blank generation alone
is not proof of a generation or contractual rate.

Owner-supplied `Untitled 33_2026-10-16-1053.csv` is the actual operator export,
SHA-256 `bdb92a927337e1d7d9c178cc34cd42ac258920d8f0e75260881bd72b860b4100`.
`tests/fixtures/climate/prod_point_query_profile.json` retains all 22 operators,
parent arrays, attributes, statistics and time breakdowns without raw records.
All operators are step 1. Percent-like CSV fields are fractions: 0.4927536 is
49.27536%, not 0.4927536%. These are reported operator shares, not additive
wall-clock stages or guaranteed removable latency.

Scan-level bytes sum to 30,435,376, whereas the separate history export reports
141,499,392. Both are retained; this discrepancy is unresolved. Do not invent an
explanation or force reconciliation. Operator shares sum to about 98.55%; do not
renormalize them or derive exact operator seconds by multiplying query totals.

## Complete executed graph

Parent means downstream consumer. Source paths are:

```text
8(pointer scan) ------------------------> 7(release join) -> 6(shared CTE)
11(release scan) -> 10 -> 9 -------------> 7
6 -> 5 -> 4(metadata flatten) -> 3(metadata filter) -------------------> 2
6 -> 18 -> 17(shared reference/spill) -> 16 -> 15 -> 14 ---> 13 -> 12 -> 2
21(revision scan) -> 20 -> 19 ---------------------------------> 13
2(metadata join) -> 1(limit) -> 0(result)
```

The release join has two inputs: 8 and 9. The graph does **not** show repeated
physical scans of SEMANTIC_RELEASES: one shared WithClause feeds two references.

| ID | Operator / parent(s) | Observed input -> output and attributes |
|---|---|---|
| 0 | Result / none | 1 input; C.RELEASE_ID output expression |
| 1 | Limit / 0 | 1 -> 1 |
| 2 | Metadata Join / 1 | 2 -> 1; release equality and approved metadata measure = revision canonical measure |
| 3 | Metadata Filter / 2 | 4 -> 1; requested PRCP measure, nonnull |
| 4 | Metadata Flatten / 3 | 1 -> 4; extension.metadata |
| 5 | WithReference / 4 | 1 -> 1; C |
| 6 | WithClause / 5,18 | 1 -> 1; CURRENT_CLIMATE shared producer |
| 7 | Release Join / 6 | 2 -> 1; pointer current_release_id = release_id |
| 8 | Pointer TableScan / 7 | 1 output, 1/1 partition, 1,024 bytes, cache fraction 0 |
| 9 | Release Filter / 7 | 1 -> 1; PUBLISHED and extension-v2 contract |
| 10 | Release JoinFilter / 9 | 1 -> 1; join_id 7 |
| 11 | Release TableScan / 10 | 1 output, 1/1 partition, 12,632,096 bytes, cache 0; 7.246% reported share |
| 12 | Metadata JoinFilter / 2 | 1 -> 1; join_id 2 |
| 13 | Membership/revision Join / 12 | 389,857 -> 1; capture/run/artifact/hash equality; 7.971% share |
| 14 | Membership Filter / 13 | 389,856 -> 389,856; member string nonnull; 21.739% share |
| 15 | Capture-ID Flatten / 14 | 1 -> 389,856; extension.capture_ids; 10.145% share |
| 16 | Metadata JoinFilter / 15 | 1 -> 1; join_id 2 |
| 17 | WithReference / 16 | 1 -> 1; C; 23,601,152 bytes local spill, 1.449% share |
| 18 | Lineage Filter / 17 | 1 -> 1; run/artifact/hash scalars nonnull |
| 19 | Revision Filter / 13 | 1 -> 1; January resource/version 2, county 48277, date 2025-01-17, canonical PRCP/non-null |
| 20 | Membership JoinFilter / 19 | 1 -> 1; join_id 13; 0.725% share |
| 21 | Revision TableScan / 20 | 1 output, **29/29 partitions**, 17,802,256 bytes, cache 0; **49.275% share, remote disk IO** |

Other displayed operators report zero share; zero does not prove zero overhead.
Release scan 11 extracts the extension, frozen IDs, lineage scalars and metadata.
Revision scan 21 extracts measure, county and date plus scalar lineage columns.
No operator reports remote spilling; local spill is specifically on reference 17,
not attributed to a join or revision scan.

## Revised diagnosis

The profile disproves the original missing-measure-pushdown rationale. Operator
19 already contains county, date and canonical measure before membership join
13; the revision branch produces one row. Projection-only candidate A
(`sql/january_climate_point_query_candidate.sql`) is retained as a control, not
recommended as a demonstrated improvement. It may produce the identical plan.

Two independent costs remain: all revision micro-partitions are read (49.275%
reported share, entirely remote IO in this export), and the complete frozen
membership is expanded/filtered/joined for a single surviving revision. The
metadata join and four-row metadata flatten are not the observed bottleneck.
Manifest buffering also spills locally. There is no basis to blame privileges,
queueing, NOAA normalization, repeated ingestion or repeated release scans.

Predicate filtering and micro-partition pruning are different: predicates are
present and selective, yet zero revision partitions were eliminated. The profile
does not tell why partition statistics could not prune (layout, VARIANT stats,
expression, or other optimizer constraints). Canonical V103 defines no clustering
key or typed county/date/measure projection. Do not claim an indexed lookup from
its unenforced PRIMARY KEY. Live physical table DDL/policies have not been read.

## Minimal supported experiment B: exact membership test

`sql/january_climate_membership_probe_candidate.sql` replaces the membership
FLATTEN/join with:

```sql
AND ARRAY_CONTAINS(TO_VARIANT(v.capture_record_id), c.extension:capture_ids)
```

It retains published pointer/v2 checks; exact run/artifact ID/hash joins;
resource/version 2; approved metadata measure equality; and the complete original
scientific SELECT projection byte-for-byte. It has one source reference to
current_climate rather than two. No production view, metadata view, grant, release
pointer, RAW/annual/NLCD content or API shape changes.

Published v2 manifests validate exactly 389,856 sorted unique SHA-256 **strings**
(climate_release.py). Under that precondition the predicate tests the same exact
capture set. It never admits an entire run merely because run lineage matches.
Malformed duplicate/nonstring/null arrays are not equivalent to the old coercing
FLATTEN; existing publication validation must remain fail-closed. No silent
normalization of malformed manifests is introduced.

Expected effect to test: replace 389,856 intermediate membership rows with a
boolean membership test for the selective revision and avoid the shared CTE
spill. These are **hypotheses**, not optimizer guarantees. ARRAY_CONTAINS still
reads/searches the large array; the optimizer could evaluate it before filtering
or once per metadata row. It can regress broad January reads. No speedup is
predicted by subtracting operator percentages. It does not itself fix the 29/29
revision partition scan. Warm-cache behavior may reduce IO but is not physical
pruning or a durable cold-cache fix.

## Relational/prunable serving alternative if B is insufficient

The existing V071 SEMANTIC_OBSERVATIONS storage serves the retained annual/NLCD
release content, not the 389,856 climate extension captures. Canonical migrations
declare no separate persisted typed climate serving table or materialized view.
Reusing the annual rows as a climate cache would silently change their contract
and the accepted release; it is not a drop-in point-query optimization.

A persisted, immutable release-membership projection could key each accepted
capture by release ID plus typed county/date/measure and retained run/artifact/
hash, built once from the validated frozen manifest. It would replace repeated
array decoding and permit matching before ledger access. Typed columns/layout
could help partition pruning; that still requires measured plans. Merely moving
389,856 IDs to an unorganized table does not guarantee a point lookup.

Such a table requires reviewed build/backfill for the existing release, digest/
count parity, insert-only ownership, release-pointer binding, complete-row/value-
type equivalence, and fail-closed publication/reconciliation. A serving projection
must never widen membership or skip immutable provenance. This is a larger change
than B and is **not implemented** before the smallest experiment is measured.
No materialized-view/search-optimization entitlement, new service, new role,
clustering maintenance or warehouse resizing is assumed. Do not recluster or
rewrite the immutable V103 ledger speculatively.

## Smallest discriminating benchmark — NOT authorized

Keep PR #695 draft. Pin reviewed commit and all three SQL checksums first. The
old five-statement proposal compared two variants; this revised scope compares
three and therefore requires its own explicit authorization. Maximum **7 read-only
statements**, one session, no automatic retries, 180s process + 15s grace, at most
60s per diagnostic statement. The deployed API five-second limit stays unchanged.

**Access prerequisite:** OH_LYME_PROD_READ is view-only; OWNER was proven to lack
the climate-view/revision privileges. Use the proposed existing ATLAS_PROD_MIGRATOR
binding above only after explicit changed-scope authorization. This reuses retained,
verified object privileges rather than broadening access. Effective warehouse,
database/schema access and all EXPLAINs must pass before runtime queries. Do not
add grants or substitute an admin identity. Diagnostic-role measurements are not
API service-role acceptance. The consumed OWNER approval does not authorize this
role change or another session.

1. SELECT effective user/role/database/warehouse. Require approved diagnostic
   identity, PROD database and COMPUTE_WH; stop on mismatch.
2. EXPLAIN JSON baseline V152 point query.
3. EXPLAIN JSON projection-only A point query.
4. EXPLAIN JSON membership-probe B point query.
5. Execute baseline point SELECT once, fetching at most one release ID.
6. Execute B point SELECT once, fetching at most one release ID.
7. Execute A once **only if its plan differs materially**; otherwise record
   redundant plan and skip this statement, consuming six total. Never add a
   replacement statement or repeat a variant after failure.

All queries use PRCP, county 48277, date 2025-01-17 and select release_id LIMIT 1.
Set USE_CACHED_RESULT=false through reviewed connector session parameters. Never
flush/suspend/resize the warehouse for artificial cold-cache control. Record
order/cache fractions: baseline-first favors B if caches warm, so this pair is
preliminary, not a p95 claim or proof of <2s interactive latency. If promising,
a later separately authorized reverse-order/warm repetition can test stability.

Capture query IDs, client elapsed and EXPLAIN graphs within those statements.
Owner exports retained profiles/history for compile/execute/provision/queue,
partitions/bytes, row counts, membership placement and spill; no hidden metadata
SQL is included. Require unchanged published release ID and contract parity.
Look for removal of the 389,856-row branch and spill, not only a cache-dependent
time drop. Target total server time below 4.5s for margin under 5s, ideally <2s
warm. An execution-only improvement that still totals >=5s fails the API goal.
Broader scientific read/pagination parity must be separately bounded before any
view replacement; this one-row diagnostic cannot establish broad-read behavior.

Planning: 195s process/grace + 600s observed idle tail at an **assumed** 1 credit/hr
and owner's $2/credit public rate = $0.441667 compute. Explicit 25% contingency
makes $0.552084; proposed maximum $1 within the cumulative project ceiling after
reservation reconciliation. This is not actual/contractual billing or a hard
warehouse-wide spend cap. Shared traffic/cloud charges are unknown. No consumed
allowance is reused; no benchmark had executed at preparation time; see the completed attempt below.

Only after measured evidence and parity: prepare a forward-only view migration,
COPY GRANTS, unchanged ownership/reader grants, sole-approved pending migration
and checksum, existing protected deployment with separate mutation allowance.
Rollback is a separately approved restoration of V152 with COPY GRANTS, not
ledger deletion or a release-pointer change. No migration checksum or executable
production replacement is claimed before selecting a measured winner.

Then authorize one actual API startup probe under the unchanged five-second cap.
Keep climate off until it passes; controlled enablement and bounded decoded HTTP
acceptance follow separately. Disable on HTTP failure. Keep API #84 open until
actual service and four-measure scientific HTTP acceptance succeed.

References: https://docs.snowflake.com/en/sql-reference/functions/get_query_operator_stats
and https://docs.snowflake.com/en/sql-reference/functions/array_contains .


## Fresh migrator benchmark: completed 2026-10-16

Owner authorized the exact changed diagnostic identity in the task conversation.
One fresh $1 reservation (forecast $0.552084) is consumed; previous reservations
remain consumed and actual billing is unknown. No statement or connection retry,
DDL, grant, API change or additional metadata query occurred. The session took
16.250s; the enclosing process took 20.578s without triggering its deadline.
All seven reviewed statements passed. SQL hashes remain those of d1cb811.
The live identity matched MATTHEWCARAWAY / OH_LYME_PROD_MIGRATION_DEPLOYER /
ONE_HEALTH_LYME_GAP_ATLAS_PROD / COMPUTE_WH / TXB06009 / AWS_US_WEST_2.
All three EXPLAINs passed before any benchmark SELECT.

| Statement | Query ID | Client elapsed seconds |
|---|---|---:|
| Identity | 01c7c78e-030c-43ea-0064-2d07012876ae | 0.157 |
| Baseline EXPLAIN | 01c7c78e-030c-43ea-0064-2d07012876b2 | 0.812 |
| A EXPLAIN | 01c7c78e-030c-442e-0064-2d0701289366 | 0.609 |
| B EXPLAIN | 01c7c78e-030c-442e-0064-2d070128936a | 0.266 |
| Baseline SELECT | 01c7c78e-030c-43ea-0064-2d07012876b6 | 6.906 |
| B SELECT | 01c7c78e-030c-43ea-0064-2d07012876ba | 0.531 |
| A SELECT | 01c7c78e-030c-43ea-0064-2d07012876be | 5.532 |

Each SELECT returned exactly the accepted January published release ID. A was
executed because its work signature differs (release/pointer join order changes).
It retains the same membership expansion and is still above five seconds.
B's EXPLAIN has 13 operators versus 22 in baseline/A. Its only FLATTEN is the
four-measure metadata array; capture-ID FLATTEN and shared WithClause/WithReference
branches disappear. ARRAY_CONTAINS is a join filter tied to the unchanged
run/artifact/hash membership join. This is a structural improvement, not evidence
that a measured runtime operator produced zero membership rows.

All three plans assign 31/31 aggregate partitions and 107,813,888 bytes, including
29/29 revision partitions and 95,180,800 assigned revision bytes. These are
EXPLAIN estimates, not actual bytes scanned or pruning statistics. Revision
predicate filtering remains; partition pruning is not improved by B.

B was 92.3% faster in this one ordered client measurement. Result cache was
disabled, but warehouse/local metadata and data caches were not cleared; B and A
ran after baseline. This is preliminary evidence supporting B, not a reliability,
p95, cold-cache, full projection or actual API service-reader acceptance claim.
The approved diagnostic selects only release_id: optimizer projection pruning
means it does not measure all scientific output fields used by the API.
Server compilation/execution split, actual operator row counts, actual scan bytes
and runtime spill are not returned by these seven statements. They remain
unverified for these new query IDs; no eighth history/profile query was executed.

Full sanitized plans, checksums, identities and results are retained in
[evidence/2026-10-16-migrator-point-benchmark.json](evidence/2026-10-16-migrator-point-benchmark.json).
Keep this PR in draft. Next independently safe work is complete offline parity
for the admitted unique-string membership contract and a minimal forward-only
B view migration design preserving COPY GRANTS and all scientific projection.
Before deployment, independent review and CI must pass; separately scoped
runtime profiles/full scientific projection and intended service-role acceptance
must address cache order, scan/spill and broad-read uncertainty. No optimization
is merged or deployed by this benchmark authorization.
