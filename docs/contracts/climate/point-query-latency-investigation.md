# January PROD point-query latency investigation

Status: actual profile analyzed; SELECT-only candidates, no migration. DATA #443
owns this investigation; API #84 remains disabled. No paid execution, timeout
change, warehouse resize or PROD mutation is authorized by this document.

## Evidence and reproducibility

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

**Access prerequisite:** OH_LYME_PROD_READ is view-only; inline candidates reference
protected base tables and cannot be assumed accessible to it. Do not add grants.
Propose existing ATLAS_PROD_OWNER / OH_LYME_PROD_OWNER for authorized diagnostic
SELECT/EXPLAIN only on COMPUTE_WH, subject to verifying its actual identity and
existing base-table SELECT/warehouse access. Stop if inaccessible; never treat
an access error as object absence or substitute an admin identity. Owner-role
measurements are diagnostic evidence, **not** API service-role acceptance. Exact
connection binding must be reviewed before authorization/dispatch.

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
allowance is reused; no benchmark has executed.

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
