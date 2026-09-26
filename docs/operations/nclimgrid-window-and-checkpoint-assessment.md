# #443 initial-window and checkpoint assessment (2026-09-26)

This is a read-only planning assessment. It does not authorize V103, Tier B
backfill, PROD mutation, or ML feature admission.

## Three distinct windows

**NOAA source availability:** 1951-01 through 2026-08, 908 scaled nClimGrid-Daily
v1.0.0 monthly links in the inspected NOAA year indexes. Generated definitions
are frozen to this known range. This is an inventory, not Atlas ingestion.

**Provisional initial Atlas candidate:** 2008-01 through 2025-12 (216 complete
calendar months). This covers the governed historical CDC Lyme surveillance
era (2008–2021), the separately governed 2022-current era, and two full recent
climate years for current investigation. It avoids treating post-August 2026
data as available and keeps full years for seasonal comparisons. It does not
assume the eras can be pooled, that every county-year has a usable label, or
that retrospectively obtained climate was historically available at a model
cutoff. Choose this candidate only after the source steward can verify live
county-year continuity and #110/#113/#23 decide the intended use and as-of
rules. It is a planning preference, **not an approved execution window**.

**Optional extension:** pre-2008 NOAA months, and newer scaled months after
2025 when a reviewed investigation or approved model target demonstrates
value. Pre-2008 climate has no demonstrated overlap with the currently
governed 2008–2021 and 2022-current county surveillance sources. The
1992–2007 CDC era is separately identified in the source-onboarding decisions,
but is not evidence of an admitted, continuous county label series.

The actual target and horizon remain open in machine-learning #23. Data #110
still requires label maturity, eligible county-period and source-portfolio
evidence; data #113 requires cutoff and historical availability proof. The
current DEV `ATLAS_DEV_READ` identity was checked as user `MATTHEWCARAWAY`,
role `OH_LYME_DEV_READ`, database `ONE_HEALTH_LYME_GAP_ATLAS_DEV`, warehouse
`OH_LYME_DEV_INGEST_XS_WH`. It cannot inspect `CONFORMED` or
`GOVERNANCE.V_DATA_EXPLORER_CONFORMED_CDC` (not visible/not authorized).
Accordingly, live county-year coverage, value-state continuity, and label
maturity cannot be quantified in this pass. The reviewed repository confirms
the source-year ranges and different reporting eras, not a complete training
label matrix. A steward-accessible read-only query of approved conformed
snapshots by source, year, county, value state, and reporting era is needed
before choosing an exact start year or an ML window.

## Volume comparison

All estimates assume four measures and 3,144 canonical counties per day.
Partitions use the observed 250-row limit; a 900,000-byte cap may increase
counts if row shapes change. NOAA bytes use the mean of six inspected files;
local JSON uses 3,186,698,867 bytes across 152 captured days. TIGER is
83,989,800 bytes independently retained per month. Decimal GB; before
revisions, Snowflake compression, metadata, and compute. The batch ceiling is
12 consecutive months.

| Candidate | Months | Days | County-day-measure rows | Projected partitions | NOAA GB | NOAA + TIGER retained GB | Local JSON GB | 12-month batches |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2022-01–2025-12, minimal current era | 48 | 1,461 | 18,373,536 | 73,526 | 2.89 | 6.92 | 30.63 | 4 |
| 2008-01–2023-12, label-era overlap through known 2023 source | 192 | 5,844 | 73,494,144 | 294,104 | 11.57 | 27.70 | 122.52 | 16 |
| **2008-01–2025-12, provisional preference** | **216** | **6,575** | **82,687,200** | **330,892** | **13.02** | **31.16** | **137.85** | **18** |
| 2008-01–2026-08, include latest listed partial year | 224 | 6,818 | 85,743,168 | 343,121 | 13.50 | 32.31 | 142.94 | 19 |
| 2000-01–2025-12, pre-label sensitivity extension | 312 | 9,497 | 119,434,272 | 477,944 | 18.80 | 45.01 | 199.11 | 26 |
| 1951-01–2026-08, complete NOAA availability | 908 | 27,637 | 347,562,912 | 1,390,854 | 54.72 | 130.99 | about 579 | 76 |

The 2022–2025 candidate is smallest, but only the post-2022 reporting era
could overlap it and its county-year continuity is unverified. The 2008–2023
candidate reaches both known source eras but has no newer full-year climate
for prospective investigation. The 2000–2025 candidate adds eight pre-2008
years without demonstrated governed label overlap. None is a claim that a
future predictor may use historical NOAA values at an unproven cutoff.

Five local source-backed Tier A captures (195101–195103, 198801, 202501)
retained 7,649 partition files, 3.187 GB JSON, and 724.3 MB NOAA/TIGER
artifacts. February and March 1951 ran in one bounded batch (18.8 and 9.5
minutes), with successful idempotent rerun. The other 903 source months were
unattempted; 202608 was inspected only. These times are not Tier B forecasts.

## What 250-row partitions mean in Tier B

`partitioning.py` caps canonical partitions at 250 rows **and** 900,000
canonical JSON bytes. Both the local file store and `SnowflakeCheckpointStore`
receive the same `NormalizedPartition` objects. V103 creates one row per
partition in `GOVERNANCE.INGESTION_RUN_NORMALIZED_PARTITIONS`, with identifiers,
hash, row and byte counts, and a `records VARIANT` array. The Snowflake store
serializes each partition to canonical JSON, calls `PARSE_JSON` inside a
per-partition `MERGE`, then verifies the stored metadata by a `SELECT` and
commits. The observed 1,560 partitions per 31-day local month therefore
project roughly the same physical checkpoint row count in Tier B if row
shapes remain consistent. V103 also has one completion row per run. There is
no checkpoint deletion/TTL after successful ingestion in the migration,
store, orchestrator, or #426 contract; captures remain available for resume
and run-pinned reads. This is retained operational state under current code.

The 579 GB figure is **uncompressed local canonical JSON**, not a measured
Snowflake physical-storage estimate. Snowflake `VARIANT` encoding,
micro-partition compression and table metadata can change physical bytes;
neither a compression ratio nor a DEV bill is evidenced here. Retained
artifacts are separate, independently captured NOAA and TIGER members.
V103 also stores immutable record revisions separately; their physical
footprint is additional if that path is exercised.

Each partition requires a Snowflake `MERGE`, verification `SELECT`, and
transaction commit. Completion and later stage reads traverse all partitions
for a run in ordinal order; the coverage reporter does too. Thus 330,892
partition rows for the provisional candidate imply at least that many write
and verification round trips, plus repeat reads. The full NOAA range implies
about 1.39 million. This is a code-derived operation count, not a measured
Snowflake latency/cost estimate. Even the provisional candidate is too large
to call safe for DEV without a measured Tier B pilot and review of retained
checkpoint storage and query time. Recommend a bounded prerequisite story:
measure one approved month in DEV after protected V103 deployment, including
partition write/read latency, Snowflake compressed bytes, warehouse credits,
retention growth, and resume/report time; then decide whether #426 needs a
separately reviewed efficiency/retention change before any historical batch.
Do not redesign #426 inside #443.
