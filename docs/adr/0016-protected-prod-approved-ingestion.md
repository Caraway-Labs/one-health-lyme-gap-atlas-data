# 0016: Protected PROD Approved Ingestion

Status: Accepted
Date: 2026-09-07
Decision owner: One Health Lyme Gap Atlas product and engineering leads

## Context

The PROD CDC/Socrata `x5j9-wybp` candidate has complete evidence and an
immutable steward `APPROVED` decision. The normal PROD ingestion job is
scheduled annually, so it cannot provide a controlled immediate run. The
production App Platform runtime already holds the separate encrypted Snowflake
and Spaces settings; copying them into GitHub or a local shell would violate
the environment boundary.

## Decision

Add a manually dispatched workflow protected by the GitHub `production`
environment. It verifies that the existing `approved-source-ingestion` job is
present, uses `run-production-schedule`, and references an image digest found
in the DEV deployment history. It then clones that job as the temporary,
non-routable `PRE_DEPLOY` job `approved-source-ingestion-once` and removes its
schedule.

The pre-deploy job keeps the existing production runtime configuration and
runs the established `run-production-schedule` command unchanged. That command
fails closed unless a PROD source version is approved, performs the full RAW
load, and invokes dbt only after that load completes. A successful App Platform
deployment is the provider-backed confirmation that the pre-deploy job
completed successfully.

An exit handler restores the exact previous App Platform specification after
both success and failure. Restoration removes only the temporary topology; it
does not delete immutable artifacts, governed records, RAW data, or dbt output.

## Consequences

The protected workflow produces a reproducible release record and retains the
same DEV-tested digest. GitHub has no Snowflake or Spaces credentials, and the
temporary job has no ingress. A failed ingestion preserves whatever immutable
request and artifact evidence was recorded; operators must diagnose it through
the governed ledger rather than deleting or retrying blindly.

## Alternatives considered

Waiting for the annual schedule delays a reviewed production acceptance run.
Running from a local shell would weaken the protected audit trail and expose
production identity configuration outside its existing secret store. Rebuilding
or replacing the image was rejected because it could diverge from DEV-tested
code.

## Acceptance criteria

- A protected `production` approval is required before execution.
- The target is `oh-lyme-data-prod`; exactly one scheduled ingestion template
  exists; and no stale temporary job is accepted.
- The active PROD ingestion digest is found in DEV deployment history before
  the job is created.
- The workflow changes no pipeline command: it invokes only the existing
  `run-production-schedule` command.
- Provider deployment success and post-run provenance/dbt validation are both
  required before the run is accepted.
- The prior App Platform specification is restored on success or failure.

## Rollout, observability, and rollback

Merge after CI passes, then dispatch from `main` and obtain the protected
production approval. After the workflow succeeds, verify the source version,
ingestion run, artifact counts, quality results, RAW/CONFORMED counts, dbt
result, and restored app configuration. If the run fails, preserve evidence and
restore the app configuration before diagnosis. To halt future work, disable
the annual scheduled ingestion job; rollback never deletes retained evidence.

## Links to affected contracts and tests

- Workspace ADR 0006
- `docs/contracts/catalog-to-snowflake/source-onboarding-spec-cdc-lyme-socrata.md`
- `docs/contracts/catalog-to-snowflake/SNOWFLAKE_DATA_PROVENANCE_IMPLEMENTATION.md`
- `docs/operations/deployment-promotion.md`
- `tests/test_governed_pipeline.py`
