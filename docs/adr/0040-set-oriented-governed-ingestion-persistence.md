# 0040: Set-oriented governed ingestion persistence

Status: Proposed for protected review
Date: 2026-09-27
Owner: Atlas data stewardship and engineering

## Context

The January 2025 Tier B capture contains 389,856 normalized rows and 1,560
logical partitions. The original pilot took 5h58m56s and 26,794 Snowflake
queries. After PR #487 grouped eight partitions per transaction, a protected
recapture still took 3h47m22s, 11,740 queries, and 7,914 MERGEs. Its
checkpoint MERGE/readback span was about 40m53s; STAGING/CONFORMED write-query
span about 81m41s; RAW/revision write-query span about 95m43s. These spans
establish small-statement overhead, but do not isolate Snowflake compilation,
execution, network latency, and Python serialization independently.

The code still emits approximately one checkpoint MERGE, one MERGE per each of
three projections, and one revision MERGE per partition: approximately 7,800
MERGEs for 1,560 partitions. Each revision partition additionally performs a
conflict SELECT. The remaining observed MERGEs include run and artifact state.
Partition readback is one SELECT per eight partitions (195), with one
completion SELECT per eight. Three eight-partition write paths have about 585
explicit transaction/connection scopes. The observed 1,208 COMMIT and 604
ALTER_SESSION statements include connector/session activity beyond those
explicit scopes; exact attribution requires query history with IDs. The 2,014
SELECTs include revision checks, checkpoint readbacks/completion checks,
ordered reads, run state, and verification. The six V069/V103 run stages,
completion, and artifact writes are O(1) per run and are not the dominant
write count.

## Decision

Keep three granularities distinct:

1. **Logical:** unchanged partitions of at most 250 records and 900,000
   canonical JSON bytes, with the same ordinal, ID, SHA-256, row count, byte
   count, and ordered V103 representation.
2. **Recovery:** up to 64 logical partitions per transaction. A failure rolls
   back that group; prior groups remain available for deterministic replay.
3. **Physical:** one content-addressed compressed JSON-lines transport file
   per recovery group and data kind, and one insert-only MERGE per destination
   from that staged set. Checkpoint metadata readback remains a group-level
   SELECT. The projected-row transport is checked for expected count, distinct
   logical IDs, and each payload SHA-256 before destination writes. RAW and
   revision captures share a transaction.

V117 adds only a scoped internal transport stage; runtime receives READ/WRITE
on that stage, not CREATE STAGE, CREATE TABLE, or schema grant powers. Stage
files are content-addressed and run scoped. After each destination transaction
commits, the runtime removes only that exact transport file. A failure before
commit leaves the file available for retry; a failed removal causes a replayable
stage failure. The governed source bytes continue to live in private Spaces
and RAW_ARTIFACTS; transport files do not replace or remove those artifacts.
Residual transport storage and cleanup failures must be measured before a
large historical batch.

First-write V069 projections and V103 checkpoints/captures remain insert-only
MERGEs because retry must preserve the first committed row. V103 capture and
physical revision IDs keep their existing deterministic SHA-256 formulas.
Conflicts for a repeated artifact/record/transformation identity are checked
once per staged group before the RAW/revision transaction commits. A plain
INSERT would create duplicates under retry because Snowflake standard-table
primary keys are not enforcement of uniqueness. Existing V069/V103 rows are
never rewritten. Ordered reads continue through V103 without a new format.

## Alternatives

- `executemany` with server-side binding may create a temporary stage, which
  requires privilege and session context not currently granted to the runtime.
- Multi-row `VALUES` still leaves at least one large statement per logical
  partition, and large JSON checkpoint documents make giant SQL text brittle.
- `write_pandas` introduces pandas/Arrow serialization and temporary stage
  privileges for a generic JSON/VARIANT path.
- A temporary runtime table requires CREATE TABLE rights; a permanent landing
  table duplicates significant payload storage and needs its own retention and
  retry ledger. Direct staged-set queries avoid that extra relation for this
  bounded monthly workload.
- A single whole-month transaction reduces statements further but abandons
  bounded durable progress on interruption.
- Warehouse resizing does not correct the per-partition statement topology.

## Compatibility and rollout

V117 is additive. There is no DELETE, TRUNCATE, DROP, CREATE OR REPLACE, reset,
or backfill of historical V069/V103 data. Existing partitions retain the
canonical-json-v1 envelope and remain readable. Existing successful run IDs
and artifacts remain unchanged. The orchestration still skips successful
months and resumes failed ones. No recapture, migration execution, DEV batch,
PROD operation, or public release is performed by this code change.

Before considering the design validated, separately authorize one governed
January 2025 DEV recapture and compare exact source SHA, runtime identity,
statement classes, wall time, row/partition/completion/revision counts,
coverage signature, fresh-process ordered read, unchanged rerun, failed-run
preservation, transport storage, and attributable credits with both earlier
benchmarks. A passing test supports a reviewed next-month plan, not replay of
already successful history.
