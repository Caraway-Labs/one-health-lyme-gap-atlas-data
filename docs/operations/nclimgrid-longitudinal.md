# nClimGrid longitudinal operations (#443)

The [longitudinal contract](../contracts/climate/nclimgrid-longitudinal-v1.md)
and [ADR 0039](../adr/0039-nclimgrid-longitudinal-window-and-bounded-execution.md)
define the proposed 1951-01 through 2026-08 scaled window. The first 908-month
DEV backfill is **not authorized by this runbook**: the cost/window review and
protected V103 migration are outstanding. No PROD or public release is part of
this procedure.

## Read-only planning and bounded local checks

```text
uv run atlas-data source nclimgrid-inventory --start 195101 --end 202608
uv run atlas-data source validate --definition nclimgrid:195101
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
uv run atlas-data source batch --definitions nclimgrid:195102..195103 --tier A --fixture-root <off-repo-fixture-root>
```

The first invocation produced two successful, independent run IDs. Repeating
the same command returned `skip_succeeded` for both IDs. This is a local
execution check, not governed DEV ingestion.

## Monthly and batch execution after governance gates

The canonical single-month operation remains:

```text
uv run atlas-data source run --definition nclimgrid:195101 --tier B
uv run atlas-data runs show --run-id <run-id>
uv run atlas-data runs resume --run-id <run-id> --definition nclimgrid:195101
```

The existing generic `run-ingestion.yml` workflow accepts the same generated
definition. Its `batch` operation accepts a range such as
`nclimgrid:195101..195112` and calls `source batch` with the DEV runtime
identity. Each invocation is limited to twelve source definitions and one
month is one independent run. Rerunning a batch skips successful months and
resumes `FAILED` months. A `RUNNING` or other nonterminal run must first be
inspected to rule out a concurrent worker, then resumed explicitly with its
run ID. The optional `recapture` workflow input creates new immutable
captures, including when the URL is stable. Identical bytes are not a new
physical content revision; changed bytes retain the earlier capture and
create a revision. A corrupt retained member blocks resume; do not refetch
after completed ACQUIRE.

Before a protected DEV batch, verify its effective user, role, database, and
warehouse, the V103 migration ledger, the reviewed monthly range and cost
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
admission; data #110/#113 and machine-learning #23 still own that decision.
The report streams one month's partitions at a time; broad reporting itself
has a material read/runtime cost and should be scheduled in bounded ranges.

If a month fails blocking quality, the report continues to select the last
successful capture and lists the failed run separately. Do not overwrite or
delete an earlier capture or approve a public release from this report.
