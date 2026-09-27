# #486 bounded Tier B write efficiency

## January 2025 baseline

The protected #446 pilot (`36297010206`, ingestion run
`12f9ddb2-0216-4537-adb6-749b1656f33f`) succeeded in 5 h 58 m 56 s,
near the six-hour job limit. It stored 389,856 normalized rows in 1,560
partitions. Account query history recorded 26,794 runtime queries: 9,409
COMMIT, 7,924 MERGE, 4,752 SELECT, 4,701 ALTER_SESSION, six UPDATE, and two
INSERT. The 1,560 partition MERGEs and 1,560 following verification SELECTs
spanned 91 m 33.732 s. These query classes are observed, but the history does
not identify every call site uniquely.

Account Usage later reported 232,706,560 active and 6,945,902,592
time-travel bytes for the partition table, plus 156,656,640 active and
4,477,763,072 time-travel bytes for revisions. Those metrics include retained
failed-run evidence and have reporting latency. Query-attributed credits were
incomplete (3.276 credits for 4,745 visible queries); overlapping warehouse
metering was 8.2155 credits and is not an exact pilot cost.

The source code explains the dominant per-partition shape:

| Path | Before, per 8 partitions | After, per 8 partitions | Classification |
| --- | ---: | ---: | --- |
| V103 normalized checkpoint | 8 completion SELECT + 8 MERGE + 8 verification SELECT + 8 commits/connections | 1 completion SELECT + 8 MERGE + 1 verification SELECT + 1 commit/connection | Confirmed round trips; 91-minute observed span includes client work and warehouse waiting |
| STAGING and CONFORMED projections | 16 MERGE + 8 commits/connections | 16 MERGE + 1 commit/connection | Confirmed code shape; separate live time not attributable |
| RAW projection and revisions | 8 RAW MERGE + up to 8 revision SELECT/MERGE pairs + 8 commits/connections | Same MERGE/SELECT count + 1 commit/connection | Confirmed code shape; separate live time not attributable |
| Ordered checkpoint read | One ordered cursor | Unchanged | 13.602 s observed; not a write bottleneck |

For 1,560 partitions, the structural checkpoint shape falls from 4,680 to
1,950 statements (2,730 fewer), and the three write paths fall from 4,680 to
585 explicit connection/commit scopes (4,095 fewer). The revision/projection
MERGE count remains unchanged. This is a local query-shape calculation, not a
prediction of DEV elapsed time or credits. Other run-state writes, connector
queries, and session setup also contributed to the 26,794 total.

## Decision and integrity boundary

An eight-partition maximum groups existing Snowflake writes into a transaction.
At the #426 limit this holds at most 2,000 normalized records and 7.2 MB of
canonical partition JSON before connector overhead. Each checkpoint MERGE
remains insert-only and run/ordinal keyed. A group reads completion once,
performs the existing MERGEs, verifies **all** partition IDs, digests, row
counts, and byte counts in one SELECT, then commits. A mismatch or SQL error
leaves the group uncommitted. Completed groups remain durable after interruption;
retry replays the same insert-only MERGEs and readback. The completion receipt
still follows full contiguous-ordinal and content validation.

STAGING/CONFORMED and RAW/revision groups reuse one transaction, but keep the
existing bounded 250-row MERGEs, revision conflict SELECTs, deterministic
capture/revision identities, artifact lineage, and insert-only semantics. RAW
and revisions commit together. Stage completion still follows the full stage;
failed runs and artifacts are retained. Tier A file/memory stores preserve their
immediate per-partition checkpoint behavior. No V103 DDL, partition-size rule,
scientific transform, source selection, publication rule, or retention policy
changes. ADR 0037 and the simplified-ingestion contract remain authoritative.

Connection reuse alone, without transaction grouping, would leave COMMIT
round trips. A single whole-month transaction would lose bounded recovery.
One giant multi-partition MERGE would increase query/document size and alter
the established row-level verification pattern. Revision-wide set operations
would require a larger lineage redesign. This bounded grouping is the smallest
change aimed at the demonstrated round-trip cost.

## Separate protected DEV benchmark gate

No DEV benchmark is authorized by this PR. A later reviewed request should run
one unchanged January 2025 Tier B recapture or another explicitly chosen
one-month capture, with `recapture` and artifact lineage approved beforehand.
Record exact workflow SHA, runtime identity, run ID, stage timestamps, query
IDs/types, commit/merge/select counts, row and partition counts, checkpoint
write span, artifact bytes, and active/time-travel table bytes with Account
Usage reporting latency. Capture warehouse credits only when query attribution
is defensible; warehouse-hour totals are not exact run cost. Verify fresh-process
ordered read, report, failed-run preservation, and one unchanged skip rerun.

Proposed pass criteria for a first historical tranche: terminal success in
**at most 3 hours** (at least 3 hours of six-hour job margin), checkpoint write
span **at most 45 minutes**, fewer than **20,000** runtime queries, unchanged
389,856 normalized rows and 1,560 partition/completion rows for the same
January source, no false revision or duplicate logical capture, and successful
fresh-process ordered read/report. Any integrity failure is a hard fail even if
time improves. Storage and credit changes must be reported with provenance and
latency, but are not pass/fail without comparable attributable baselines. If
these criteria fail, #443 history stays blocked while the specific remaining
bottleneck is reviewed. A passing single month supports proposing a
conservative, separately authorized first tranche; it is not approval for
historical execution or PROD.
