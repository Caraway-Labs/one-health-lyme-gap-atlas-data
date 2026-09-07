# 0015: Protected PROD CDC Evidence Capture

Status: Accepted
Date: 2026-09-07
Decision owner: One Health Lyme Gap Atlas product and engineering leads

## Context

The CDC/Socrata `x5j9-wybp` steward review in DEV is complete, but PROD has no
source version or evidence candidate. The production App Platform jobs already
hold the separate production Snowflake and Spaces credentials. Copying those
credentials into GitHub or a local operator environment would weaken the
environment boundary. Running the annual full-ingestion schedule to create a
candidate would also violate the required evidence-before-approval order.

## Decision

Add a manually dispatched GitHub workflow in the protected `production`
environment. It retrieves the existing production App Platform specification
without printing it, verifies the expected app and one discovery-job template,
and creates one temporary `PRE_DEPLOY` job named `cdc-evidence-capture`.

The temporary job clones the discovery job's image and encrypted runtime
configuration, removes its schedule, and runs only:

`uv run atlas-data pipeline cdc-sample`

That command captures the bounded CDC metadata, documentation, schema, and
ordered sample evidence required for `x5j9-wybp`; it creates a pending steward
review candidate. It does not record a decision, fetch the full source,
populate `RAW`, run dbt, or promote an image.

The workflow confirms that the deploy-time job invocation succeeded, then
restores the exact prior App Platform specification in an exit handler on both
success and failure. A failed restoration is a hard stop for all further
production activity.

## Consequences

The candidate is created by the already-isolated production runtime identity,
while GitHub receives only the existing protected DigitalOcean token and app
identifier. Provider-encrypted runtime values are never emitted or copied.
The job is non-routable and one-shot; no new recurring production workload
remains after restoration.

Evidence is append-only. If the capture command partially records evidence
before failing, retain it and investigate through the governed ledgers; do not
delete or overwrite it. The automatic restoration only removes the temporary
job topology, not evidence records.

## Alternatives considered

Local execution with production credentials was rejected because it would
blur the environment boundary and reduce the protected, source-controlled audit
trail. Reusing the annual ingestion job was rejected because it may ingest and
transform data and therefore cannot precede the production steward decision.
Adding a permanent scheduled evidence job was rejected because this is a
one-time onboarding action.

## Acceptance criteria

- GitHub requires `production` environment approval before the job can run.
- The workflow proves the target is `oh-lyme-data-prod`, uses exactly one
  existing `catalog-discovery` job as its template, and refuses a stale
  temporary job.
- Its only pipeline command is `cdc-sample`; it contains no approval,
  full-ingestion, dbt, or image-promotion command.
- The job invocation must be `SUCCEEDED` before the workflow reports success.
- The exact prior App Platform specification is restored on success and
  failure, without printing encrypted values.
- The new candidate is visible in the PROD approval console and remains
  pending until a steward records an immutable decision.

## Rollout, observability, and rollback

Merge the workflow only after its tests pass. Dispatch it from `main`; GitHub's
protected environment provides the human release approval. Review the workflow
run, DigitalOcean deployment/job-invocation record, and the PROD approval queue.
If the capture fails, preserve the evidence and use the failure record for
diagnosis. If restoration fails, stop all further production actions and restore
the prior App Platform specification before retrying. No data is deleted as a
rollback action.

## Links to affected contracts and tests

- `docs/contracts/catalog-to-snowflake/source-onboarding-spec-cdc-lyme-socrata.md`
- `docs/contracts/catalog-to-snowflake/SNOWFLAKE_DATA_PROVENANCE_IMPLEMENTATION.md`
- `docs/operations/deployment-promotion.md`
- `tests/test_governed_pipeline.py`
