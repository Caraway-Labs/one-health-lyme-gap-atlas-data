# NOAA nClimGrid-Daily longitudinal county panel v1

Status: proposed for #443 review; full historical execution is pending the
cost/window and DEV migration gates in [ADR 0039](../../adr/0039-nclimgrid-longitudinal-window-and-bounded-execution.md).
Owner: Atlas data stewardship and engineering.

## Frozen candidate source window

| Item | Decision/evidence |
| --- | --- |
| Start | 1951-01 |
| End | 2026-08 |
| Expected months | 908, in calendar order |
| Product | NOAA NCEI nClimGrid-Daily v1.0.0 monthly **scaled** NetCDF grids |
| Source URI | `https://www.ncei.noaa.gov/data/nclimgrid-daily/access/grids/{YYYY}/ncdd-{YYYYMM}-grd-scaled.nc` |
| Availability check | NOAA year indexes 1951–2026 on 2026-09-26: 908/908 listed, no missing/duplicate scaled month links |
| End rule | August 2026 was the latest listed scaled month; later months require an explicit window update |
| Historical first publication | Unavailable; never infer from observation or modification time |

NOAA's [product page](https://www.ncei.noaa.gov/products/land-based-station/nclimgrid-daily)
describes CONUS data from 1951 to present. The review inventory checks the
official [monthly grid indexes](https://www.ncei.noaa.gov/data/nclimgrid-daily/access/grids/)
one year at a time; `atlas-data source nclimgrid-inventory --start 195101
--end 202608` reproduces the selected-month listing. An index link is
availability evidence, not a capture or checksum. A later 404 or corrupt
artifact is recorded as a failed monthly run and never silently replaced by
preliminary data.

Data #110/#113 need eligible county-period counts, missingness, revisions,
and actual as-of availability. Machine-learning #23 has no approved target or
horizon as of this decision, so the full verified scaled history maximizes
reuse for seasonality, interannual comparison, and later temporal split design.
This contract grants no ML feature admission. Existing human-surveillance
label history may be shorter; an eligible climate month is not an eligible
training example.

## Representative source-backed schema evidence

The `nclimgrid-inspect-artifact` command validated retained local copies of
four official files. These are **local source-backed inspections**, not DEV
ingestion. All four had `time × lat × lon`, a 596 × 1,385 ascending 1/24°
grid, Gregorian whole-day time, the native `prcp`, `tmin`, `tmax`, `tavg`
variables, mm/°C native units, NaN fill, no packing, and the same grid ID
`f6759ec770aa79789cb9e38f170bdb7b820d1c19e89eb734fc66720c392f0c95`.
Their monthly source-support union had 469,758 grid cells and SHA-256
`65debe9c65efb232b8a574e176a0ad4ebe5726b9026b124c6b26f448bb54e3ac`.

| Month | NOAA SHA-256 | Bytes | Product metadata |
| --- | --- | ---: | --- |
| 1951-01 | `2fd26c14f435a3ab43d0ca6dc730c78c217a67ef9e1f0d4246bdfee9bb137d55` | 62,312,946 | `v1-0-0 20220823` |
| 1988-01 | `3e088ebf0faaf7d3103d9716d0a7a1478137ac91b57d3ca2edee302207587aa1` | 61,955,327 | `v1-0-0 20220829` |
| 2025-01 | `809a58714578ce654e61e094e5f7d0ee704d332f1ff6a86c644e56de4ee4da31` | 61,013,299 | `v1-0-0 20250404` |
| 2026-08 | `2f9531cf2c60d8edc53bb08ad93fd4c8fd19174cdce0c86bc5a50f0c9d87ebee` | 57,266,553 | `v1-0-0 20260905` |

Matching samples do not prove that all 908 files share a schema. Each monthly
VALIDATE independently checks version, variables, dimensions, units, fill,
grid, and time before normalization. A changed coordinate grid fails the
frozen longitudinal pin rather than being silently combined with earlier
months. The source-support mask remains derived separately from every retained
monthly artifact; changes can be reported without assuming the source is
spatially constant.

## Definition and execution identity

`nclimgrid:YYYYMM` is a deterministic virtual definition accepted by the
canonical `source validate`, `source run`, and `runs resume` commands. It is
generated from the committed January #198 YAML with a reviewed canonical
template digest. Only resource key, scaled URL, destination, and month change;
the generated definition also pins the longitudinal grid/window identity and
its own SHA-256. The definition digest is stored in the ACQUIRE detail and in
generated normalized rows. A resume refuses a different generated definition.
The legacy January #198 definition remains valid and its row content is not
changed by this extension.

`source batch --definitions nclimgrid:YYYYMM..YYYYMM --tier B` handles at
most twelve consecutive months. It validates all definitions before running,
uses the shared orchestrator for one run per month, skips already successful
months, resumes failed runs, and stops on an unresolved failure. A nonterminal
run requires explicit operator inspection and `runs resume` so another live
worker cannot be mistaken for a stale interruption. `--recapture` explicitly
creates new captures for completed months, retaining prior SHA-256 and V103
revision lineage. Each month retains separate NOAA and TIGER named members;
after completed ACQUIRE, VALIDATE/NORMALIZE replay those retained bytes only.
The ephemeral geometry-weight cache is keyed by TIGER SHA-256 and grid ID and
is never used as governed state.

All scientific values, units, #424 analytical geometry and area weighting,
monthly source-support mask, 95% daily valid/source-supported completeness,
missing/partial/zero/out-of-source states, and NOAA-supplied TAVG remain as in
the [#198 source contract](nclimgrid-daily-v1.md). No rolling feature,
anomaly, drought measure, PRISM copy, or publication is created here.

The #188 semantic mapping registry retains its reviewed January 2025 entries.
`nclimgrid_month_mapping_registry(path, YYYYMM)` derives the same four mapping
rules for exactly one frozen-window month, with that month's resource key and
source vintage. Each rule still requires an independently approved exact
source-version authority and NOAA/TIGER lineage. A caller maps one month at a
time; a 1951 rule rejects a 1988 source tuple. This avoids registering a
historical month under the January 2025 semantic source identity.

## Reproducible coverage and limitations

`source nclimgrid-report` streams selected successful run-pinned normalized
partitions. It emits a JSON month summary and a county-month-measure CSV.
Failed recaptures do not replace the most recent successful capture. The
report distinguishes **NOT_ATTEMPTED**, **UNAVAILABLE** (NOAA 404), **FAILED**,
and **CAPTURED** months; it records unique NOAA digests, revisions, expected
and observed days, missing source dates, CONUS/source-supported counties,
the four coverage states, source-support fractions and signatures, full-day
complete county-months by measure, retrieval/HTTP/NetCDF modification facts,
and retained/normalized/runtime footprint. `all_days_complete` is a factual
completeness indicator, not an ML approval or a claim of historical as-of
availability. Historical first publication time is explicitly unavailable.

The January 1951 local Tier A run used the exact NOAA/TIGER files above. It
produced 389,856 normalized rows in 1,560 bounded partitions: 385,516
`COMPLETE` and 4,340 `OUT_OF_SOURCE_COVERAGE` county-day-measure rows; zero
`PARTIAL_COVERAGE` or `SOURCE_MISSING` for that month. All 3,109 CONUS
counties had some source support, while 314 had less than 95% of full legal
county area in the monthly source mask. All 3,109 CONUS county-months had
every day `COMPLETE` for each measure, yet their historical original
publication times remain unavailable. This is one local historical month,
not evidence of a national historical DEV panel.

The 908-month plan implies 347,562,912 rows and 1,390,854 #426 partitions.
The January 1951 local partition checkpoint was 635.7 MB and the two retained
artifacts were 146.3 MB. A simple linear footprint is about 577 GB of
partition JSON plus about 131 GB of independently retained artifacts, before
Snowflake V103 physical rows, recaptures, and overhead. This cost and DEV's
missing V103 migration require human review before a full backfill. No PROD
or consumer execution is authorized by this contract.
