# nClimGrid longitudinal operations (#443)

The [longitudinal contract](../contracts/climate/nclimgrid-longitudinal-v1.md)
and [ADR 0039](../adr/0039-nclimgrid-longitudinal-window-and-bounded-execution.md)
retain 1951-01 through 2026-08 as source availability/replay bounds. The Atlas
target is 1985-01 through a reviewed complete scaled endpoint; current endpoint
202608 was rechecked on 2026-10-06. Label-panel and historical missing-V103
gates are superseded. No full-history backfill is authorized. Review the
[exact two-singleton proposal](nclimgrid-1985-proof-plan.json) first: 198501,
then 202608 only after early-month acceptance. Credit/currency and physical
storage/headroom approvals remain outstanding. No NOAA download, paid SQL or
workflow dispatch belongs to this documentation change.

## Read-only planning and bounded local checks

```text
uv run atlas-data source nclimgrid-inventory --start 195101 --end 202608
uv run atlas-data source validate --definition nclimgrid:198501
uv run atlas-data source validate --definition nclimgrid:202608
uv run atlas-data source nclimgrid-inspect-artifact --month 195101 --path <local-off-repo-NOAA-file>
```

The inventory makes one bounded directory request per year and reports missing
or duplicate scaled month links. It does not capture source bytes. The local
artifact inspector validates actual NetCDF bytes and reports the SHA-256,
grid, product metadata, days, native variables, fill, and monthly support
mask. It labels this evidence as local source backed. Downloaded NetCDF/TIGER
files and generated run checkpoints remain outside Git and are never a
substitute for private governed DEV artifact retention.

The source-backed local two-month batch proof used the approved TIGER bytes
and downloaded scaled NOAA files in an off-repository fixture root. Each
`noaa_nclimgrid_daily_YYYYMM` subdirectory contained `nclimgrid-scaled.nc`
and `tl_2025_us_county.zip`:

```text
uv run atlas-data source nclimgrid-batch --definitions nclimgrid:195102..195103 --tier A --fixture-root <off-repo-fixture-root>
```

The first invocation produced two successful, independent run IDs. Repeating
the same command returned `skip_succeeded` for both IDs. This is a local
execution check, not governed DEV ingestion.

## Monthly and batch execution after governance gates

The canonical single-month operation remains:

```text
uv run atlas-data source run --definition nclimgrid:198501 --tier B
uv run atlas-data runs show --run-id <run-id>
uv run atlas-data runs resume --run-id <run-id> --definition nclimgrid:198501
```

The existing generic `run-ingestion.yml` workflow accepts the same generated
definition. Its `nclimgrid-batch` operation accepts a range such as
`nclimgrid:198501..198501` and calls `source nclimgrid-batch` with the DEV runtime
identity. Each invocation is limited to twelve generated nClimGrid definitions; a
YAML/path list or unrelated adapter cannot enter the batch or `--recapture` path. One
month is one independent run. Rerunning a batch skips successful months and
resumes `FAILED` months. A `RUNNING` or other nonterminal run must first be
inspected to rule out a concurrent worker, then resumed explicitly with its
run ID. The optional `recapture` workflow input creates new immutable
captures, including when the URL is stable. Identical bytes are not a new
physical content revision; changed bytes retain the earlier capture and
create a revision. A corrupt retained member blocks resume; do not refetch
after completed ACQUIRE.

Before a protected DEV batch, verify its effective user, role, database, and
warehouse, the V103/V117 migration ledger and ADR 0040 grouping, the reviewed monthly range and cost
budget, and that its source definition matches this contract. Use only the
dedicated DEV runtime identity via the generic workflow. The Alpha POC
database is excluded. Do not use the read-only PAT as a writer or manually
apply V103. The production connection and Tier C remain separate protected
operations.

## Reproducible report

Where the governed runtime can read run-pinned partitions:

```text
uv run atlas-data source nclimgrid-report --start 195101 --end 202608 --county-csv <output.csv> --output <output.json>
```

The JSON records every selected month, including not attempted, NOAA 404,
and failed runs. The CSV contains one row per selected successful
county-month-measure with status-day counts, monthly source support,
source-time days, and factual full-day completeness. Its
`historical_publication_time_known` is false. Do not treat this as an as-of
admission; future supervised/as-of admission remains separately owned; current Tier 1 ML does not wait for climate.
The report streams one month's partitions at a time; broad reporting itself
has a material read/runtime cost and should be scheduled in bounded ranges.

If a month fails blocking quality, the report continues to select the last
successful capture and lists the failed run separately. Do not overwrite or
delete an earlier capture or approve a public release from this report.

## Stop/reuse and publication boundary

Preflight matching successful runs and active workflows before either singleton.
Reuse success with recapture=false; inspect nonterminal runs before explicit
resume, since overlapping ranges are not serialized by definition-keyed concurrency.
Stop on unresolved source, quality, integrity, resource or spend failures. Record
peak RSS, actual free disk, stage residuals, attributable credits and physical
storage where visible; unknown is never zero. No NLCD budget is inherited.
The 360-minute workflow timeout is not the proposed 60-minute monthly allowance;
an enforceable approved bound must be established before dispatch.

January release work reuses the existing ATLAS pointer, four metadata definitions
and two V136 view contracts. The failed export 37098434706 returned
FROZEN_MEMBERSHIP_READ_UNAVAILABLE and no artifact. V137 joins existing semantic
observations and lacks normalized_sha256; it cannot supply the full unpublished
five-tuple membership. Source-specific stage/access diagnosis is still required;
absence is not established. See the January handoff below. No new schema or
migration is reserved by this change.
