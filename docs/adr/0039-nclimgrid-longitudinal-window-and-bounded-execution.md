# 0039: nClimGrid longitudinal window and bounded execution

Status: Revised for independent review under #443 (2026-10-06)
Date: 2026-09-26
Decision owner: Atlas data stewardship and engineering

## Context

PR #434 proved January 2025 through the canonical #198/#424/#426/#432 path.
NOAA publishes scaled nClimGrid-Daily v1.0.0 monthly NetCDF files from 1951.
DATA #443 now selects environmental context from 1985-01 through the latest
complete supported scaled month. Supervised labels are not an execution gate;
Tier 1 ML does not wait for climate. Historical as-of eligibility and ML feature
admission remain separate decisions.

## Decision proposed for review

Record **1951-01 through 2026-08 inclusive** as NOAA source availability,
not an approved Atlas execution window. This is the broadest contiguous scaled
monthly range found in NOAA's official year indexes on 2026-09-26. The 908
expected months comprise 75 complete years plus eight scaled months in 2026.
The source is only NOAA nClimGrid-Daily v1.0.0 **scaled** monthly NetCDF.
There were no missing or duplicate scaled month links in that inventory.
Preliminary files are not substitutes. A new scaled month beyond August 2026
requires a later reviewed window update.

Generate each monthly definition deterministically from the reviewed #198
January source definition. The generated definition pins the month URL, 2025
TIGER archive, #198 measures/coverage rules, source-definition digest, and the
frozen grid identity verified in early, middle, and recent artifacts. A
generated definition runs through the ordinary `atlas-data source run` and
`atlas-data runs resume` path. A batch of at most twelve definitions invokes
that same orchestrator sequentially, with one governed artifact capture and
one run per month. The #424 county/grid weights may be reused only in process
when the verified TIGER and grid identities match. The cache is disposable;
artifact replay remains run pinned.

The Atlas target is **1985-01 through a frozen approved end month**, presently
2026-08 (500 months). Source availability from 1951 remains unchanged for
retained replay. The September 26 assessment is historical, superseded as a
selection gate; it does not limit the new target to supervised-label overlap.
The first proposed proof is exactly two singleton DEV scopes: 198501, then
202608 after acceptance of the first. This is not permission to ingest 500 months.
See the [bounded plan](../operations/nclimgrid-1985-proof-plan.json).

## Cost and execution gate

Ingesting the complete NOAA availability range would imply 27,637 expected
days, 86,890,728 county-days,
347,562,912 county-day-measure records, and at least 1,390,854 normalized
partitions at the #426 limit of 250 rows. Six inspected NOAA files are
56.6–62.5 MB; their mean projects about 54.7 GB of NOAA files. Retaining the
84.0 MB TIGER input per independent run projects about 76.3 GB of analysis
reference captures before object-store deduplication, if any.

A local source-backed run for each of January–March 1951, January 1988, and
January 2025 succeeded. February and March ran in one bounded canonical
batch; an unchanged rerun skipped both. Together the five captures produced
7,649 partitions containing 3.187 GB of normalized JSON and retained 724.3
MB of NOAA/TIGER artifacts. January 1951 alone used 635.7 MB of partitions
and 146.3 MB of artifacts. The reproducible full-window report records only
5 Tier A captures and 903 not-attempted months. Linear projection is about
579 GB of uncompressed local partition JSON and 132 GB of
artifact captures, before V103 physical storage, recaptures, and
environment overhead. Snowflake compression and physical bytes remain
unmeasured. Its fresh-process resume after completed ACQUIRE and
VALIDATE took 24.6 minutes; the interrupted earlier attempt took 17.1 minutes
before normalization produced a partition under the original eager-weight
code. The 1988 and 2025 fresh-process resumes took 21.7 and 11.7 minutes,
respectively; those runs reused the retained named inputs, and the 2025 run
reused an ephemeral geometry-weight cache. The adjacent February and March
batch months took 18.8 and 9.5 minutes respectively, including canonical
checkpoints. These are local measurements,
not DEV cost or full-window completion claims.

At the 2026-09-26 published rates, [DigitalOcean Spaces Standard](https://docs.digitalocean.com/products/spaces/details/pricing/)
includes 250 GiB in the $5 monthly subscription and charges $0.02/GiB-month
above it. The projected 132 GB of independently retained artifacts is about
123 GiB, or about $2.46/month of incremental storage **if all of it falls
above the existing allowance**. Current bucket usage, recaptures, transfer,
and Snowflake V103 physical storage are unknown. [Snowflake documents](https://docs.snowflake.com/en/user-guide/warehouses-overview)
1 credit/hour for a running Gen1 X-Small warehouse, but local Tier A wall
time does not measure DEV warehouse active time, account credit price, or
compressed storage. A DEV cost budget needs a measured protected pilot.

**New execution remains blocked on exact runtime/storage/spend authority**,
not label availability or an obsolete missing-V103 claim. V103/V117 and current
identity, active workers, ledger reuse and resource headroom must be verified
before dispatch. ADR 0040 retains 64-partition recovery groups. Existing DEV
January and 2008 proofs are retained evidence, not permission to recapture them.
The accepted January benchmark is 25m38.119s, 815 queries and 233 MERGEs;
warehouse active time, peak RSS and physical-storage cost are separate facts.

## Consequences

The scientific meaning in the #198 climate contract remains unchanged:
PRCP/TMIN/TMAX/NOAA TAVG, native units, #424 area weighting, the monthly
source-support mask, daily valid-area completeness, distinct zero/missing/
partial/out-of-source states, and exact NOAA/TIGER/run/revision lineage.
There is no PRISM, drought, rolling/lag/anomaly feature, ML admission, public
API, or PROD publication. Availability time remains unresolved; original
historical publication timestamps are not inferred from observation dates,
HTTP Last-Modified, NetCDF date_modified, or current retrieval time.

## Alternatives considered

- Treating all NOAA availability as the initial Atlas backfill: no approved
  bounded spend authorization covers the whole availability range.
- One all-history blob or run: violates independent monthly capture and
  bounded #426 replay.
- Preliminary substitution: changes the approved source product.
- Immediate full DEV backfill: the measured
  footprint requires cost and retention review first.

## Acceptance and rollout

Review the exact finite plan, runtime/spend/storage bounds, retained capture
reuse, resource headroom and deployed prerequisites before any Tier B execution. A
measured single-month Tier B checkpoint pilot is the recommended prerequisite.
Execute one to twelve months at a time through the nClimGrid-only operation
of the protected ingestion workflow. Re-run a
failed batch to skip successful months and resume failed runs; explicitly
resume an interrupted nonterminal run after confirming it is inactive. A
recapture requires an explicit operator flag. The longitudinal report reads
governed run/partition records and distinguishes unattempted, unavailable,
failed, and captured months. Failed revisions do not replace successful ones.
Rollback stops new batches; immutable prior captures remain available for
review.

## Links

- [#198 source contract](../contracts/climate/nclimgrid-daily-v1.md)
- [#443 longitudinal contract](../contracts/climate/nclimgrid-longitudinal-v1.md)
- ADR [0036](0036-county-analysis-geometry-and-area-weighting.md),
  [0037](0037-binary-replay-and-bounded-ingestion-revisions.md), and
  [0038](0038-run-pinned-artifact-member-replay.md)
- [NOAA nClimGrid-Daily product](https://www.ncei.noaa.gov/products/land-based-station/nclimgrid-daily)
