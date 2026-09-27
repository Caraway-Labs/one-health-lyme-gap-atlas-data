# nClimGrid Snowflake persistence investigation

Baseline: January 2025, 389,856 normalized rows, 1,560 logical partitions.
This is a code-shape accounting against `main` at `eb98472` and the reported
post-#487 protected benchmark. It is not a reconstructed query-history export;
the exact call-site attribution of every observed statement remains to be
measured in the next authorized DEV benchmark.

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
Actual total queries, runtime, compute, and stage storage require a protected
benchmark; no success claim follows from this estimate.

## Benchmark and preservation gate

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
