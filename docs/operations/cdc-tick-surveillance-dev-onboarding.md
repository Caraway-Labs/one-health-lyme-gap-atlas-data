# CDC tick-surveillance DEV evidence onboarding

This runbook creates only the DEV evidence candidate for the CDC county-status
workbook covering *Ixodes scapularis* and *Ixodes pacificus* through December
31, 2025. It does not approve the source, populate RAW, run dbt, create a
schedule, or make a PROD change.

## Preconditions

1. Review the canonical v1 contract and the pinned source profile.
2. Merge a green change and record the immutable image digest deployed to DEV.
3. Verify DEV migrations V053 and V054 and deploy the approval-console source
   as `OH_LYME_DEV_STREAMLIT_OWNER`.
4. Verify the current DEV app is ACTIVE, has exactly the expected baseline jobs,
   and runs the exact requested digest.

## Evidence capture

Dispatch `capture-dev-cdc-tick-surveillance.yml` with the active DEV digest.
The temporary non-routable PRE_DEPLOY job runs only:

```text
uv run atlas-data pipeline cdc-tick-surveillance-sample --sample-limit 25
```

Because CDC supplies a workbook rather than a row API, the command downloads
the complete publisher file under a one-megabyte compressed and ten-megabyte
uncompressed bound. It retains that unchanged file privately for reproducible
evidence but inspects and serializes only the first 25 FIPS-ordered rows as the
review sample. It also snapshots the landing page, embedded data-use agreement,
schema, response checksums, assessment, and source limitations.

## Required verification

- the temporary job completed and the exact prior DEV topology was restored;
- one completed `EVIDENCE_ONLY` run exists for
  `cdc_tick_ixodes_county_status`;
- the request ledger contains the landing page and workbook checksums;
- private artifacts contain the landing page, normalized metadata, unchanged
  workbook, and derived ordered sample;
- the schema lists the seven reviewed workbook columns;
- the assessment is `PENDING_REVIEW` and explicitly says `No records` is not
  evidence of absence;
- there is no tick-surveillance RAW, STAGING, CONFORMED, ANALYTICS, or
  FEATURE_STORE write; and
- the candidate appears in the DEV approval console with zero unresolved
  material-change flags.

Stop after verification. A human steward decides what happens next. Failure
evidence remains append-only; never delete it to make a retry appear clean.
