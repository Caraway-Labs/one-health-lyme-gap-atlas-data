# 0020: Protected PROD historical CDC ingestion

Status: Accepted
Date: 2026-09-08
Decision owner: Atlas owner, after independent PROD steward approval

## Context

PROD evidence capture and an immutable steward decision approved CDC/Socrata
`qtbi-xd4i` as source version `5f8d78de-90f0-477e-aea4-a438e9a4ab66`.
ADR 0019 intentionally stopped before full acquisition. The existing historical
implementation and storage were DEV-only, so invoking the DEV workflow against
PROD would bypass reviewed environment, storage, deployment, and rollback controls.

## Decision

Add PROD-only, forward-only storage and explorer migrations and permit the
historical command in either isolated DEV or PROD. PROD remains fail-closed:
`ENABLE_PRODUCTION_EXECUTION=true`, the suffixed PROD database, and
`OH_LYME_PROD_PIPELINE_RUNTIME` must all agree.

Full acquisition is a manual, protected, one-shot workflow. It accepts an exact
source-version UUID and immutable image digest, verifies that digest in DEV and
PROD, clones the existing `approved-source-ingestion` job as a temporary
`PRE_DEPLOY` job, and restores the exact six-job PROD topology on success or
failure. It does not add or modify a schedule.

The existing million-row ceiling, deterministic paging, immutable artifacts,
publisher metadata and row-count reconciliation, eleven blocking quality
checks, revision-protected publication, and value-state preservation remain
unchanged. A separate protected rollback workflow can republish only an
explicit retained snapshot after revalidation and an expected-revision check.

## Consequences

Validated 2008–2021 records can be exposed in the existing PROD validation and
Data Explorer views without merging surveillance eras or inventing an analytics
measure. Runtime cannot approve sources or alter views. Streamlit receives only
the existing bounded governed views. The dedicated governed-view owner owns
views. This account currently has no permanent PROD migration-deployer role, so
V051 requires a separately authorized, one-time AccountAdmin DDL session;
AccountAdmin is never a runtime identity and V052 runs under the governed-view
owner.

## Alternatives considered

Reusing the DEV source version or workflow was rejected because approvals,
credentials, storage, and provenance are environment-specific. Adding a routine
schedule was rejected until a separately reviewed refresh policy and operational
evidence exist. Creating storage through the pipeline runtime was rejected
because it does not own the RAW schema and must not gain deployment authority.
A permanent PROD migration role is preferable future work, but creating it is
broader than this one-source release. The one-time V051 use is explicit,
bounded, and separately approved.

## Acceptance criteria

- V051 and V052 are PROD-only; V051 requires separately authorized one-time DDL
  and V052 runs as the PROD governed-view owner.
- Historical operations reject Alpha, database/role mismatch, and PROD without
  the existing production-execution setting.
- The workflow requires exact UUID/digest inputs, a DEV-tested digest, the
  approved-source template, and the exact six-job baseline.
- Eleven persisted blocking results pass before publication; failed validation
  preserves the prior pointer and append-only evidence.
- Unknown, suppressed, not-reported, explicit null, missing, and zero remain
  distinguishable through CONFORMED and the explorer.
- Rollback selects and revalidates a retained run; it never deletes evidence.

## Rollout, observability, and rollback

Merge only after repository gates. Deploy the resulting immutable image to DEV,
promote the same digest to PROD, then apply V051 through an explicitly approved
one-time AccountAdmin session and V052 with the governed-view owner. Dispatch
the protected ingestion using the approved PROD UUID. Verify run, request,
artifact, RAW, quality, snapshot, publication, CONFORMED, explorer, and
restored-topology evidence.

Do not exercise rollback until there are two distinct retained snapshots; a
same-snapshot repoint is not rollback proof. On failure, retain all evidence,
restore the app specification, and leave the prior publication active.

## Links

- Workspace ADRs 0005 and 0006
- ADRs 0018 and 0019
- `docs/contracts/catalog-to-snowflake/source-onboarding-spec-cdc-lyme-socrata.md`
- `docs/operations/cdc-historical-prod-ingestion.md`
- `.github/workflows/ingest-prod-cdc-historical.yml`
- `.github/workflows/rollback-prod-cdc-historical.yml`
