# DATA197 drought qualification and DATA202 bounded evidence

Status: engineering qualification, pending scientific/source review. Baseline:
`origin/main` aab1041, 2026-10-03. Owns drought-only files; no generic DATA202 rewrite.

## Product decisions

| Product | Decision | Reason and remaining evidence |
| --- | --- | --- |
| USDM native categorical county percent-area statistics | DEFER canonical mapping; bounded native tabular option is defensible for review | Native semantics and transport are defensible independently of the inspected vector. See the [minimal native option](usdm-native-tabular-option-v1.md). County boundary vintage and area denominator equivalence to Atlas 2025 TIGER remain unestablished; matching FIPS does not establish identical polygons. |
| USDM cumulative statistics, population, DSCI | DEFER | Separate products or formats outside this bounded evaluation; never reinterpret them as categorical shares. |
| USDM weekly vector alternative | DEFER | The inspected 2025-01-07 D0 geometry is invalid, and no approved repair or explicit nondrought support mask is established. |
| SPEI | DEFER | No artifact/version, accumulation timescale, calibration/reference period, PET method, geography mapping and revision policy have yet been frozen together. No SPEI values or timescales are admitted. |
| Raw precipitation | Existing DATA198 scope | nClimGrid PRCP remains mm at county-day grain; drought qualification does not recreate or replace it. |

The current nClimGrid decision is in `nclimgrid-daily-v1.md`, its longitudinal
extension and `january-2025-source-reconciliation.md`. Its run and approval state
are independent of this decision. DATA197 and DATA202 remain open.

Follow-up qualification corrects the scope of the blocker: the inspected vector's
invalid geometry and absent nondrought support domain do **not** block acquisition
of the publisher's native tabular statistics. The official table reports its own
None category. Preserving those reported county shares is within DATA197's original
county-share-by-class target; it must be explicitly identified as REPORTED native
AOI percentages, rather than Atlas-derived percentages over frozen TIGER polygons.
The current code remains inactive and its canonical gate remains closed. This
follow-up proposes a minimal contract and implementation boundary, not activation
or approval of a new semantic source tuple.

The SPEI database documentation was reachable with HTTP 200 on the laptop after
the browser-tool fetch timed out. It describes monthly 0.5-degree SPEIbase grids,
1–48-month accumulations, FAO-56 Penman–Monteith PET (distinct from the operational
monitor's Thornthwaite PET), and version 2.11 based on CRU TS 4.09 through 2024.
The page also includes older detail sections. Coverage start/end is not proof of
the fitted calibration/reference interval for a selected artifact. No full SPEI
dataset was downloaded; ODbL attribution/share-alike terms require their own
governed reuse decision. Reachability is not the remaining scientific blocker.

## Bounded implementation

`drought_qualification.py` validates native USDM categorical CSV evidence only.
It has no caller in ingestion, no SourceDefinition, warehouse write, scheduler,
release registration, semantic mapping or consumer exposure. It rejects canonical
compatibility unconditionally until the geography decision is implemented through
the existing DATA188/191/193/195 contracts. Its objects are not semantic assertions.

Inputs are one explicitly selected native FIPS, Tuesday endpoints spanning at most
28 days (five observations), and at most 64,000 bytes. Exact columns and format ID
2 are required. Values are finite percentages in [0,100]; six category shares must
sum to 100 within 0.03 percentage points, an Atlas engineering allowance for six
independent 0.01-point rounding errors. There is no renormalization. Category names
remain None, D0, D1, D2, D3, D4. None is a source category, not missingness. D0 is
abnormally dry; drought starts at D1. A partial county retains its entire class
distribution; it is not assigned one county-wide class. No mean class, continuous
SPEI substitute, drought-week count, episode length or max-class summary is emitted.

The native MapDate and ValidStart must agree; ValidEnd must be six days later.
These describe the source labeling interval, not a continuous seven-day physical
measurement or actual publication timestamp. Thursday publication uses information
through Tuesday; historic first availability remains unknown. The native product
has no single SPEI-style reference/calibration period. No reference period is
invented from the acquisition window. Missing weeks, missing/nonfinite values,
duplicates, schema/format/date/geography drift block qualification rather than
zero-filling, forward-filling or bridging an episode.

Logical identity is product/native FIPS/map date. The retained byte SHA-256 and
transformation version define a qualification revision; identical bytes repeat
deterministically and changed bytes produce a new revision even if values do not
change. This is not a V103 ingestion capture. Official maps are described as final;
a changed response still requires investigation of statistics/transport/geometry
drift and a new retained capture, never replacement of an approved release.

## Evidence and refresh

One public request on the laptop returned HTTP 200, text/csv, 172 bytes:
`https://usdmdataservices.unl.edu/api/CountyStatistics/GetDroughtSeverityStatisticsByAreaPercent?aoi=48081&startdate=1/7/2025&enddate=1/7/2025&statisticsType=2`.
The retained fixture SHA-256 is
`e40d5bc6b654b827cc884bf375ca34ea58ffa65b088275de926a2cd97cbcdca9`.
This is real publisher evidence, not a synthetic ingestion run. Negative tests
mutate copies and label their intent in the test names.

No automatic refresh is activated. A future reviewed definition should bound
county/date/byte/row scope, use canonical source validate/run and retained members,
and distinguish failed retrieval from an unchanged historical snapshot. A weekly
source schedule does not make an old pinned map invalid. Source use/attribution
review must retain the NDMC/USDA/NOAA/NASA publisher credit; map reproduction
instructions do not alone approve every derived reuse. No causal disease, score
or automatic ML use is authorized.

## DATA202 compatibility matrix

| Dimension | Implemented qualification check | Canonical acceptance gate |
| --- | --- | --- |
| Quality/units | Finite categorical percent area, format 2, class totals | Reviewed native denominator; never mix population or cumulative values |
| Geography | Exact selected native FIPS | Explicit county boundary vintage/denominator reconciliation, or retained vector + approved TIGER intersections |
| Reference/time | Exact Tuesday interval; no calibration invented | SPEI must separately freeze version/timescale/reference period; weekly snapshots cannot silently join daily PRCP |
| Availability | Historic actual timestamp stays unknown | Reviewed metadata must distinguish observation, schedule, retrieval and actual availability |
| Missing periods | Missing expected week blocks | Explicit source missing versus unsupported scope; no fabricated zero |
| Revisions/provenance | Exact byte digest; stable logical identity and changed revision | Canonical orchestrator run/artifact/V103 and DATA193 lineage required |
| Partial county | All six shares retained separately | No categorical averaging or assignment of a whole-county drought class |
| Compatibility | Native canonical join fails closed | Reuse DATA195; no coercion of USDM, SPEI, precipitation or geography |
| Failure/recovery | Pure validation changes no approved release | Existing monitoring/release controls required before activation |

## Blockers and next bounded work

The alternative vector was inspected locally: official
`https://droughtmonitor.unl.edu/data/shapefiles_m/USDM_20250107_M.zip`, HTTP 200,
2,407,168 bytes, SHA-256
`8a3a38b729074de97996afc8ffc3bb2dd8394df48ff206b2b6565c10fdf5fa6d`.
Its retained `.prj` resolves to EPSG:4326, so the general metadata page's Albers
description cannot substitute for artifact CRS. The five records are DM=0–4;
D0 fails Shapely topology validation. No class for nondrought or independent
source-support boundary is included. The redacted inspection facts and topology
reason are in `tests/fixtures/drought/usdm-vector-inspection.json`; full ZIP bytes
remain in the isolated workspace outside the repository. No geometry was repaired.
This is a concrete fail-closed blocker under the county-analysis contract, not a
claim that every USDM weekly vector is invalid. Do not try another week to silently
avoid the failure or infer no drought from every gap in the vector footprint.

Obtain publisher-corrected/valid vector evidence or an explicitly reviewed repair
method retaining originals, plus an authoritative support domain and coverage
policy; alternatively obtain the native statistics boundary vintage/denominator.
Reconcile these with the existing county-analysis geometry contract. Do not infer
boundary vintage from FIPS. If defensible, implement the canonical ingestion path and semantic
mapping with complete coverage/lineage tests. SPEI requires a separately reviewed exact
product artifact and scientific parameter contract. There is no blanket authority for
historical acquisition, new source approval, DEV deployment or PROD work.

Offline tests, laptop HTTP evidence, DEV persistence, PROD persistence and live
consumer evidence are separate: only the first two exist here. No migration,
credentials/grants, paid run, Alpha POC, Web or deployed resources were changed.

## Local verification

- Repository agent-context check: PASS.
- Ruff check and format: PASS; mypy: PASS, 113 source files.
- Initial PR head b997707 drought-only suite: 17 passed. The full Windows suite collected the initial
  15 drought tests and finished with 3,017 passed, 2 skipped, 4 failed in unchanged
  `test_failure_engine_launcher.py` subprocess timeout expectations. The two later
  drought tests cover byte bounds/duplicate headers and empty/dry capture behavior.
  A detached clean aab1041 baseline reproduced the same four failures (2 passed)
  with baseline `src` first on PYTHONPATH. They are not introduced by drought code.
- Review follow-up drought-only suite: 22 passed, adding a successful reversed-input
  five-week capture and both inclusive/exclusive sides of the rounding boundary.
  Ruff check/format also passed. Runtime source code is unchanged by that follow-up.
- Offline dbt parse: PASS. Local Docker build: PASS,
  image `sha256:b48b83750f7da4d4085c5b5636e02e5336bfdfbebd108a080e2d7d5777d65814`.
  These are local checks, not hosted CI, deployment or source acceptance.
- Fresh origin/main reconciliation: aab1041, no competing open drought/generic202
  PR found during the repository inspection. Other agents' worktrees were read
  for inspection only; all changes reside in this ticket's isolated worktree.
- Hosted exact-head Quality for b997707 completed successfully:
  [run 37100039527](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/37100039527).
  All quality steps passed and the DEV deployment job was skipped. Follow-up
  documentation has its own head/check state; prior success is not relabeled.

## Authoritative references reviewed

- [USDM classification](https://droughtmonitor.unl.edu/About/AbouttheData/DroughtClassification.aspx)
- [Statistics explanation](https://droughtmonitor.unl.edu/About/AbouttheData/StatisticsExplanation.aspx)
- [REST format and county scope](https://droughtmonitor.unl.edu/DmData/DataDownload/WebServiceInfo.aspx)
- [Observation, publication and final-map policy](https://droughtmonitor.unl.edu/About/WhatistheUSDM.aspx)
- [Metadata and cumulative Excel distinction](https://droughtmonitor.unl.edu/DmData/Metadata.aspx)
- [Publisher attribution](https://droughtmonitor.unl.edu/About/Permission.aspx)
- [SPEI database](https://spei.csic.es/database.html)
