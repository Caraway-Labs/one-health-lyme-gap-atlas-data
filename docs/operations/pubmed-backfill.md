# PubMed backfill slices

One backfill run reads a reviewed plan and one slice. It does not move the
daily `last_entry_date` watermark and it does not use that day's
`daily_run_id`. The cursor for `(plan_id, slice_id)` is a LOAD checkpoint on
the resource key `pubmed-backfill` (`retstart`, `last_pmid`, `slice_complete`,
`remaining`). `retstart` is how many unique PMIDs in the slice are already
processed. The next run continues after `last_pmid`.

The plan file is `config/intelligence/backfill/<plan_id>.json`. Dates are
inclusive EDAT days. Every slice is 1 to 30 days. `maxdate` must be strictly
older than each source's daily first-window start, which is
`last_entry_date - 30 days`. A missing daily watermark is refused. In PROD,
`approved_by`, `approved_at`, and `approved_request_limit` are required.
`request_limit` cannot exceed that approved value, and neither requests nor
items can exceed the recorded ceiling of 5 requests and 200 items. Transport
bounds stay at the daily values unless the plan sets a lower one: batches of
at most 67 PMIDs, 2 MiB responses, a 30 second timeout, and at least 0.4
seconds between requests.

## Run one slice

Dispatch `.github/workflows/run-prod-intelligence-pubmed-backfill.yml` on
`main` with `image_digest`, `reviewed_commit`, `backfill_plan_id`, `slice_id`,
and `reason`. The workflow has no schedule. It refuses to start while
`run-prod-intelligence-daily-once.yml` is in progress, and during 5:45–6:45 PM
America/Denver. The runner also refuses when a daily ingestion row is
`RUNNING`. The scheduled daily workflow file is not part of this dispatch.

A dry run prints the slice, the planned request count, and the cursor. It
makes no provider request and no write:

```bash
uv run atlas-data pipeline run-intelligence-pubmed-backfill \
  --backfill-plan-id <plan_id> \
  --slice-id <slice_id> \
  --dry-run
```

Overflow stays on the same slice. The next dispatch, outside the blackout and
not during a daily run, continues from the cursor. Items already stored add no
revision. Each raw copy's capture time is the backfill run time, so the 30-day
raw clock starts then.

PROD slices for days 31–365 and days 366–1,825 are separate approvals. This
note does not dispatch them.
