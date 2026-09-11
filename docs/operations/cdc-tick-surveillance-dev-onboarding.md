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

On a trusted operator workstation, run `scripts/publish_tick_operator_evidence.py`
with the active DEV digest, the browser-printed landing-page PDF, the exact
county-status workbook, and `--publish-and-dispatch`. The CLI validates the
complete workbook package, embedded agreement and classification terms, exact
schema, FIPS order, statuses, PDF container, byte bounds, and checksums. It builds
a short-lived private OCI envelope from the active digest and dispatches
`capture-dev-cdc-tick-surveillance-operator.yml`. Raw bytes never enter GitHub;
the workflow receives only immutable digests, a temporary tag, and a retrieval
UUID. GitHub never receives DEV Snowflake or Spaces credentials.

Do not pass the pathogen-status workbook to this command. That workbook has a
different schema and semantics and requires a separate governed source design.

The temporary non-routable PRE_DEPLOY job runs only:

```text
/app/.venv/bin/atlas-data pipeline cdc-tick-surveillance-sample --sample-limit 25 --evidence-bundle-dir /run/atlas-tick-evidence
```

Because CDC supplies a workbook rather than a row API, the envelope includes the
complete publisher file under a one-megabyte compressed bound. The DEV runtime
independently recomputes both payload checksums and validates the acquisition
manifest, operator retrieval UUID, active base digest, short-lived envelope
digest, pinned URLs, media types, ten-megabyte uncompressed bound, workbook
schema, embedded terms, ordering, and source semantics. The PDF is retained as
an opaque operator print and is never rendered or executed by the runtime. Only
then does it persist unchanged source bytes and the manifest to private Spaces
and append Snowflake evidence. It validates keys, order, and status domains
across the worksheet but serializes only the first 25 FIPS-ordered rows as the
review sample; this is not the complete post-ingestion quality suite. Any
mismatch is retained as a failed `EVIDENCE_ONLY` run and creates no candidate.

## Required verification

- the temporary job completed and the exact prior DEV topology was restored;
- the temporary private-registry tag was removed and both base and envelope
  digests appear in retained evidence;
- one completed `EVIDENCE_ONLY` run exists for
  `cdc_tick_ixodes_county_status`;
- the request ledger contains the landing-page print and workbook checksums and
  does not claim an unobserved HTTP status;
- private artifacts contain the landing-page print, acquisition manifest, normalized
  metadata, unchanged workbook, and derived ordered sample;
- the schema lists the seven reviewed workbook columns;
- the assessment is `PENDING_REVIEW` and explicitly says `No records` is not
  evidence of absence;
- the candidate exposes the raw-access restriction, ArboNET attribution, and
  final-publication-copy obligation for the steward's decision;
- there is no tick-surveillance RAW, STAGING, CONFORMED, ANALYTICS, or
  FEATURE_STORE write; and
- the candidate appears in the DEV approval console with zero unresolved
  material-change flags.

Stop after verification. A human steward decides what happens next. Failure
evidence remains append-only; never delete it to make a retry appear clean.
