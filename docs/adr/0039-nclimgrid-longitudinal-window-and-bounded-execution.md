# 0039: nClimGrid longitudinal window and bounded execution

Status: Proposed for protected review under #443
Date: 2026-09-26
Decision owner: Atlas data stewardship and engineering

## Context

PR #434 proved January 2025 through the canonical #198/#424/#426/#432 path.
NOAA publishes scaled nClimGrid-Daily v1.0.0 monthly NetCDF files from 1951.
Data #110/#113 require measured historical depth and point-in-time evidence,
while machine-learning #23 has not approved a target, horizon, or split. A
short model-specific slice would preempt those decisions. The current
per-month partition design also makes the full historical cost material.

## Decision proposed for review

Select **1951-01 through 2026-08 inclusive**, the broadest contiguous scaled
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

## Cost and execution gate

The window implies 27,637 expected days, 86,890,728 county-days,
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
579 GB of partition JSON and 132 GB of
artifact captures, before V103 physical rows, indexes, recaptures, and
environment overhead. Its fresh-process resume after completed ACQUIRE and
VALIDATE took 24.6 minutes; the interrupted earlier attempt took 17.1 minutes
before normalization produced a partition under the original eager-weight
code. The 1988 and 2025 fresh-process resumes took 21.7 and 11.7 minutes,
respectively; those runs reused the retained named inputs, and the 2025 run
reused an ephemeral geometry-weight cache. The adjacent February and March
batch months took 18.8 and 9.5 minutes respectively, including canonical
checkpoints. These are local measurements,
not DEV cost or full-window completion claims.

**Full-window DEV execution is pending a reviewed cost/window decision and
the protected application of V103.** The read-only DEV migration ledger
contained V101/V102 but no V103 on 2026-09-26. The current read role cannot
inspect the source-run ledger. Do not infer that the selected 908 months have
been ingested or that a retrospective NOAA observation was available at a
historical prediction cutoff.

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

- An arbitrary short recent window: insufficiently justified while #23 is
  open and NOAA supplies a much longer consistent scaled record.
- One all-history blob or run: violates independent monthly capture and
  bounded #426 replay.
- Preliminary substitution: changes the approved source product.
- Immediate full DEV backfill: V103 is not deployed in DEV, and the measured
  footprint requires cost and retention review first.

## Acceptance and rollout

Review this candidate window, projected footprint, retention feasibility,
and DEV migration before authorizing broad batches. Execute one to twelve
months at a time through the generic protected ingestion workflow. Re-run a
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
