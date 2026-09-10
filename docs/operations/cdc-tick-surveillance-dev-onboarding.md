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
The workflow first retrieves exactly the pinned public landing page and workbook
on its GitHub-hosted runner. It enforces first-party HTTPS redirects, status, media
type, byte bounds, and checksums, then builds a short-lived private OCI evidence
envelope from the exact active DEV digest. GitHub never receives the DEV
Snowflake or Spaces credentials.

The temporary non-routable PRE_DEPLOY job runs only:

```text
/app/.venv/bin/atlas-data pipeline cdc-tick-surveillance-sample --sample-limit 25 --evidence-bundle-dir /run/atlas-tick-evidence
```

Because CDC supplies a workbook rather than a row API, the envelope includes the
complete publisher file under a one-megabyte compressed bound. The DEV runtime
independently recomputes both payload checksums and validates the acquisition
manifest, GitHub run identity, active base digest, short-lived envelope digest,
URLs, media types, ten-megabyte uncompressed bound, workbook schema, and source
semantics. Only then does it persist the unchanged source bytes and manifest to
private Spaces and append Snowflake evidence. It serializes only the first 25
FIPS-ordered rows as the review sample. Any mismatch is retained as a failed
`EVIDENCE_ONLY` run and creates no candidate.

## Required verification

- the temporary job completed and the exact prior DEV topology was restored;
- the temporary private-registry tag was removed and both base and envelope
  digests appear in retained evidence;
- one completed `EVIDENCE_ONLY` run exists for
  `cdc_tick_ixodes_county_status`;
- the request ledger contains the landing page and workbook checksums;
- private artifacts contain the landing page, acquisition manifest, normalized
  metadata, unchanged workbook, and derived ordered sample;
- the schema lists the seven reviewed workbook columns;
- the assessment is `PENDING_REVIEW` and explicitly says `No records` is not
  evidence of absence;
- there is no tick-surveillance RAW, STAGING, CONFORMED, ANALYTICS, or
  FEATURE_STORE write; and
- the candidate appears in the DEV approval console with zero unresolved
  material-change flags.

Stop after verification. A human steward decides what happens next. Failure
evidence remains append-only; never delete it to make a retry appear clean.
