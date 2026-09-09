# 0019: Protected PROD historical CDC onboarding

Status: Accepted
Date: 2026-09-08
Decision owner: Atlas owner, approved after DEV Data Explorer review

## Context

The owner reviewed the separately published 2008–2021 `qtbi-xd4i` data in DEV
and approved proceeding to the required PROD steps. A DEV approval and source
version cannot cross the environment boundary. PROD needs its own bounded
evidence, internal review views, and immutable steward decision before any
historical acquisition can be considered.

## Decision

Promote the exact immutable image active and verified in DEV through the
protected production workflow. Add PROD-only, forward-only migrations that
extend the approval views and owner-rights decision procedure to the two
allowlisted geographic CDC eras. Deploy the approval-console source under the
PROD Streamlit owner role.

Capture `qtbi-xd4i` metadata and 25 deterministically ordered sample rows with a
temporary non-routable PRE_DEPLOY job. The workflow must verify that the supplied
digest is active in both DEV and PROD, preserve provider-encrypted settings, and
restore the prior PROD topology on success or failure. Evidence capture may
write only the existing governance evidence records and private immutable
artifacts. It cannot approve, acquire the full source, run dbt, publish a
snapshot, or create a schedule.

## Consequences

The PROD approval console can show both surveillance eras with explicit
2008–2021 limitations. The steward makes a new PROD decision; no DEV decision,
source-version identifier, RAW data, or publication pointer is copied. Full PROD
historical ingestion remains blocked until a separately reviewed implementation
and explicit post-decision operator authorization exist.

## Acceptance criteria

- V049 and V050 are excluded from DEV and included only in the PROD migration plan.
- The collector accepts `dev` and `prod` but rejects the Alpha POC or any other environment.
- PROD capture is bounded to 25 ordered rows and restores the exact prior topology.
- The approval console exposes both eras in DEV and PROD and retains the era warning.
- Tests prove that no capture workflow contains full-ingestion or dbt commands.

## Rollout, observability, and rollback

Run repository gates, merge to `main`, and validate the resulting digest in DEV.
Promote that digest through the protected production environment, apply only the
two PROD-only migrations, deploy the PROD approval console, and capture evidence.
Verify the pending candidate and its provenance through the PROD owner role.
Rollback redeploys the prior approval-app source and image digest if necessary;
append-only evidence and migration history are retained.

## Links

- Workspace ADRs 0005 and 0006
- ADR 0018
- `docs/contracts/catalog-to-snowflake/source-onboarding-spec-cdc-lyme-socrata.md`
- `docs/operations/cdc-historical-prod-onboarding.md`
