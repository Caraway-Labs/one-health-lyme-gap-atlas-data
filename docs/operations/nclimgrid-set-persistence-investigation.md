# nClimGrid Snowflake persistence investigation

Baseline: January 2025, 389,856 normalized rows, 1,560 logical partitions.
The first section preserves the pre-implementation code-shape accounting
against `main` at `eb98472` and the reported post-#487 protected benchmark.
It is not a reconstructed query-history export. The protected #488 result and
its query-text attribution appear below.

| Class | Current approximate January shape | Why it exists | Set-oriented shape |
| --- | ---: | --- | ---: |
| V103 normalized checkpoint MERGE | 1,560 | Retry insert-only semantics; one per partition is avoidable | 25 |
| V103 completion SELECT before checkpoint writes | 195 | Guard completed set; one per eight is avoidable | 25 |
| V103 checkpoint metadata readback SELECT | 195 | SHA/count/byte/ID verification; keep group verification | 25 |
| STAGING first-write MERGE | 1,560 | Preserve first V069 projection and unchanged reruns; partition coupling avoidable | 25 |
| CONFORMED first-write MERGE | 1,560 | Same | 25 |
| RAW first-write MERGE | 1,560 | Same | 25 |
| V103 immutable capture MERGE | 1,560 | Preserve capture identity under retry; partition coupling avoidable | 25 |
| V103 revision conflict SELECT | 1,560 | Reject changed row under same artifact/transformation; per-partition form avoidable | 25 |
| Transport row-count/digest SELECT | 0 | New stage transfer integrity check before projection writes | 50 |
| Explicit three-path COMMIT/connection scopes | 585 | Bounded atomicity, but eight-partition size is historical choice | 75 |
| Transport PUT | 0 | New bulk transfer to avoid parameterized row/partition SQL | up to 75 |
| Transport REMOVE after commit | 0 | Remove only the exact ephemeral upload after durable write | up to 75 |
| Completion, run/stage-state, artifact, quality and publication writes | O(stages/artifacts) | Durable evidence, retry and run state | unchanged |
| Ordered checkpoint reads and identity validation | O(stages) plus row stream | Fresh-process replay, hash/ordinal/duplicate verification | unchanged |

The five dominant MERGE paths yield about 7,800 statements structurally. The
observed 7,914 includes additional run, artifact, quality, completion, and
publication MERGEs. A successful normal run also performs some run/stage-state
MERGEs and UPDATEs independent of partition count. The observed 2,014 SELECTs
and 1,208 COMMITs exceed the simple path model because connector-generated
statements, state reads, completion checks, readback, quality/reporting, and
retries all contribute. The 604 ALTER_SESSION statements indicate repeated
session setup; new groups should reduce sessions, but query-history attribution
is still required. There is no evidence that the XS warehouse size or
micro-partition clustering is the primary cause. Python normalization,
serialization and grid computation may contribute to total time, but the
roughly 3h38m of reported write-query spans and thousands of small writes
make SQL topology the first correction.

The group size of 64 bounds checkpoint source JSON near 57.6 MB before JSON
envelope and compression, with at most 16,000 normalized rows. This is a
recovery limit, not a logical partition rule or a final throughput target.
About 25 groups give approximately 125 destination MERGEs and 25 revision
conflict SELECTs, 50 transport integrity SELECTs, about 75 upload statements, 75 exact transport cleanup
statements, and 75 explicit commits.
Run-level work, connector statements, stage reads, and any retries remain.
The estimates alone did not establish runtime, query count, compute, or stage
storage; the protected result below supplies the measurements available now.

## Pre-benchmark preservation gate

Only a separately authorized January 2025 governed recapture may measure this
change. It must create a new run and retain the prior successful January runs,
failed-run evidence, V103 partitions, capture revisions, and Spaces artifacts.
Record merge commit SHA, workflow run ID, governed run ID, user/role/database/
warehouse, stage timestamps, total wall time, query counts by type and path,
row and partition counts, completion receipt, revision count, source digests,
retained bytes, exact partition identities/hashes, coverage signature and
county coverage, fresh-process ordered read, report generation, and unchanged
rerun. Include active/time-travel and stage storage, with Account Usage latency
noted; claim credits only when attributable. Compare against both the original
5h58m56s / 26,794-query pilot and the 3h47m22s / 11,740-query post-#487
capture. Do not use the old <20,000-query gate as architectural acceptance.
Require material reductions in dominant statements and wall time with every
integrity and lineage check passing. Freeze numeric pass gates after live
query attribution, rather than hard-coding them from structural estimates.

After review, identify the next outstanding approved month from the governed
run ledger. Skip already successful months; resume failed runs through their
existing recovery path. No full-history restart, PROD action, or automated
warehouse resize follows from this investigation.

## Protected January 2025 DEV result (2026-09-28)

One corrected, authorized Tier B recapture ran on PR #488 persistence SHA
`0adbfe2266fbbae73f4101c2c6b09defa9519f28`: workflow
`36371872821`, governed run `c2eb2146-005d-44d2-bac4-e2805ca42577`.
The protected workflow verified `OH_LYME_DEV_PIPELINE_SVC` /
`OH_LYME_DEV_RUNTIME` / `ONE_HEALTH_LYME_GAP_ATLAS_DEV` /
`OH_LYME_DEV_INGEST_XS_WH`. Its job ran 02:58:47–03:25:06 UTC;
the governed run lasted 1,538.119 seconds (25m38.119s). The prior incorrect
definition dispatch `36369518545` failed before creating a run.

| Metric | Original January | Post-#487 | PR #488 measured |
| --- | ---: | ---: | ---: |
| Governed run wall time | 5h58m56s | 3h47m22s | 25m38.119s |
| Runtime Snowflake queries | 26,794 | 11,740 | 815 |
| MERGE | about 7,924 | 7,914 | 233 |
| SELECT | 4,752 | 2,014 | 153 |
| COMMIT | 9,409 | 1,208 | 186 |
| ALTER_SESSION | 4,701 | 604 | 93 |
| INSERT / UPDATE | not attributed here | 0 / 0 | 0 / 0 |
| PUT / REMOVE | 0 / 0 | 0 / 0 | 75 / 75 |

The #488 result reduced wall time by 88.73%, queries by 93.06%, MERGEs by
97.06%, and COMMITs by 84.60% versus #487. The read-only protected runtime
history action `36374666734` measured query types as `PUT_FILES` and
`REMOVE_FILES`; it counted the service user's queries whose start time falls
within the governed run window. The run had fewer than Snowflake's 10,000-row
query-history function limit. Query-text mentions span 1,038.603s for checkpoint
tables (56 queries), 214.901s for STAGING (25), 213.967s for CONFORMED (25),
320.965s for RAW (27), and 249.018s for revisions (50). These are overlapping
query-text spans, not exclusive stage execution times. Source transport upload
bytes and attributable compute credits were not available from this runtime
history view; do not infer either from canonical partition or artifact bytes.
The benchmark exercised persistence SHA `0adbfe2`; later commits added only
read-only history measurement, its ledger-status correction, and benchmark
documentation. They did not change the exercised persistence path.

Protected inspect `36373674078` confirmed 389,856 normalized rows, 1,560
logical partitions with ordinals 0–1559, 672,364,924 canonical bytes, a
1,560-partition completion, 389,856 immutable revision rows, source definition
version 2 / SHA-256 `808ef6c9420bbf11ecc15b721e69f07b5a7c29f94760484789ef7a45d1dc6b8a`,
and retained NOAA/TIGER source artifacts totaling 145,003,099 bytes with the
same digests as prior runs. The fresh-process ordered read `36373726782` read
all 1,560 partitions in 14.778s without writes; the reader verifies canonical
bytes, SHA-256, partition ID, row count, and contiguous ordinals. The January
report `36373782437` reproduced 3,109 represented counties, support signature
`64dddeb03a3d9dd09d3cb1120fd29bd29d9a53362fb27843ec98b19982109369`,
385,516 COMPLETE and 4,340 OUT_OF_SOURCE_COVERAGE county-day measures.

Exactly one unchanged non-recapture dispatch `36373841926` returned
`skip_succeeded` for the new run. Post-check `36373901528` found all three
previous January runs still present, plus the one new run; artifact count
6→8 and retained bytes 435,009,297→580,012,396, normalized partition rows
4,680→6,240 and canonical bytes 2,017,094,772→2,689,459,696, revision rows
779,712→1,169,568, completions 2→3. The unchanged dispatch added zero
governed records. A read-only stage-owner LIST found zero transport objects
and bytes under the new run prefix and across the transport stage. Active and
time-travel table bytes were not visible to the runtime; Account Usage may
report them later with latency and without exact run attribution.

The steward accepted the bounded, recoverable design for merge on this
evidence. The residual 815 queries and 233 MERGEs exceed the earlier
aspirational shape, but no further optimization is required in PR #488.
Any residual performance refinement belongs in a separate, non-blocking
follow-up. This acceptance does not authorize historical ingestion or PROD
changes.
