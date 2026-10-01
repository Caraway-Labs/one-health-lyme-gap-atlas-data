# January 2025 climate consumer candidate

DATA #443 / #496; bounded product scope approved by the user on 2026-10-01.
This implementation prepares the minimum source-pinned, safe candidate projection
for independent review. It is not a Snowflake publication migration or an API
release. API #84 stays blocked until live capture proof, reviewed semantic metadata,
the named consumer view and intended API-reader proof land.

## Frozen source and projection

Selected run: `c2eb2146-005d-44d2-bac4-e2805ca42577`,
`noaa_nclimgrid_daily_202501`, definition version 2. Retained NOAA SHA256:
`809a58714578ce654e61e094e5f7d0ee704d332f1ff6a86c644e56de4ee4da31`;
retained TIGER SHA256:
`9c6e9d9076abce2670d1de255de3710c35ecca00a7005d88e012dec52d95f763`.
The source-normalization transform is `atlas-nclimgrid-county-day/2`; it is kept
separate from the capture-ledger transformation and existing candidate measure
metadata. Do not silently relabel the transform as methodology `/1`.

The projection uses the existing immutable V103 capture ledger, not mutable
RAW first-capture rows or a latest-run selector. It checks the actual ingestion
writer's record, source-row, normalized-payload, capture and revision identities.
There must be exactly 389,856 unique identities: 3,144 packaged canonical counties
times 31 days times four measures. The canonical county list is the existing
Atlas identity asset; 2025 is the analysis-geometry vintage, not a claim that the
identity asset itself is a new 2025 Census enumeration.

Fields: four canonical `nclimgrid_{prcp,tmin,tmax,tavg}_county_day` measure IDs;
county FIPS; identical labeled period start/end; DAY; numeric value, semantic
value state, source coverage status and source-time presence; unit; null
denominator; expected/intersected/supported/valid areas and both fractions;
safe capture/run/revision and digest references; retrieval timestamp; unavailable
historical publication timestamp; source modification metadata; geometry,
grid/weight and normalization identities; limitations.

COMPLETE zero remains ZERO; complete nonzero remains OBSERVED, including negative
temperatures. TAVG remains source supplied. PARTIAL_COVERAGE and SOURCE_MISSING
retain distinct coverage statuses with null/MISSING semantic values. AK/HI retain
null/UNAVAILABLE and OUT_OF_SOURCE_COVERAGE. The 95% threshold uses daily
valid/source-supported area. A small monthly supported/legal-county fraction is
not suppressed or relabeled as daily missingness. No trace inference, zero infill,
aggregation, causal interpretation, historical as-of claim or ML admission.

Only explicit safe fields are emitted; arbitrary normalized fields, private object
URIs, raw payloads and credentials are excluded. Output has
`publication_status=CANDIDATE_NOT_RELEASED` and no invented `release_id`.
The candidate is NDJSON with a complete-file digest and stable county/day/measure
order. Failure preserves any existing output and removes the temporary file.

## Existing runtime verification path

With the **already configured** DEV pipeline service's existing runtime access:

```text
uv run atlas-data source nclimgrid-publication-candidate --output <off-repository-candidate.ndjson>
```

This read-only command first requires exact identity
`OH_LYME_DEV_PIPELINE_SVC` / `OH_LYME_DEV_RUNTIME` /
`ONE_HEALTH_LYME_GAP_ATLAS_DEV` / `OH_LYME_DEV_INGEST_XS_WH`.
It checks the selected completed run, exact two retained artifact digests/byte
counts, six completed checkpoints, 1,560 completed contiguous partitions and
389,856 declared rows before streaming immutable revision records in batches.
It performs SELECT only, does not fetch NOAA/TIGER, and does not run/resume
ingestion. No new runtime, source workflow, role, credential or grant is added.
Each existing capture record is independently validated before it can enter the
atomic candidate. This does not substitute for the existing partition reader's
digest/replay proof; retain that run-pinned evidence in the independent review
packet alongside the candidate report.

## Exact current access blocker and release handshake

On 2026-10-01 19:52 UTC, the existing `ATLAS_DEV_READ` connection's direct SELECT
on `GOVERNANCE.GOVERNED_SOURCE_RECORD_REVISIONS` for the selected run failed
`002003 (42S02)`, query `01c77208-040b-c8b7-0064-2d07010c7466`,
role `OH_LYME_DEV_READ`. Bounded SHOW GRANTS on that table also failed under
`OH_LYME_DEV_OWNER`, query `01c77209-040b-c8b7-0064-2d07010c746a`.
This environment has no existing DEV service Snowflake variables. No substitute
credential, broader role or interactive login was attempted. The prior owner
artifact hashes remain valid evidence, but are not a complete revision read.

The minimum next action is the existing runtime owner running this command and
the existing ordered partition reader against the selected run. V103 already
grants the DEV runtime SELECT on revisions/partitions/completions; that invocation
needs no new grant. Do not add audit grants solely to bypass this blocker.
If a separate audit-role read is required, it must be explicitly authorized;
the necessary object reads are INGESTION_RUNS, RAW_ARTIFACTS,
INGESTION_RUN_CHECKPOINTS, INGESTION_RUN_PARTITION_COMPLETIONS,
INGESTION_RUN_NORMALIZED_PARTITIONS and GOVERNED_SOURCE_RECORD_REVISIONS.
Existing visibility must be checked before proposing any missing SELECT.

After proof, #443 data owner freezes the candidate digest, scientific/semantic
metadata and lineage review, and prepares the named read-only publication view
and immutable DEV-tested artifact. No migration version is reserved in this
draft. The existing API deployment's intended reader is `OH_LYME_PROD_READ`;
it needs SELECT on the final exact consumer view, with existing database/schema
USAGE verified first. A newly introduced view may require a separately approved
view-only grant; no broad/future/base-table grant is included here. The approved
product scope alone does not authorize those unspecified access changes.

Coordinate the protected release and migration slot with the sole DATA PROD
topology owner. Preserve prior release pointers/captures and rollback to the prior
approved projection/image through the protected path on failure. No PROD
publication is performed by this code, and historical ingestion remains paused.
API #84 owns the API/OpenAPI implementation once the verified data contract and
real intended-role consumer examples land; this candidate never satisfies RELEASED.
