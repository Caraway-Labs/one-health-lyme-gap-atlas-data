# 0017: Protected PROD CDC dbt Recovery

Status: Accepted
Date: 2026-09-08
Decision owner: One Health Lyme Gap Atlas product and engineering leads

## Context

The approved PROD CDC/Socrata `x5j9-wybp` full ingestion completed and retained
5,045 source-faithful RAW rows. Its following dbt invocation failed before
Snowflake SQL because the App Platform runtime held the encrypted
`SNOWFLAKE_PRIVATE_KEY_B64` setting while dbt required a filesystem key path.
The runtime fix is reviewed and DEV-tested separately. Re-running full
ingestion would duplicate retained RAW data and create unnecessary requests.

## Decision

Add a manually dispatched workflow protected by the GitHub `production`
environment. It obtains the active immutable DEV digest, updates the existing
PROD jobs to that exact digest, and clones only the approved-source job as a
temporary non-routable `PRE_DEPLOY` job. The temporary command invokes
`pipeline run-production-cdc-dbt-recovery` with a supplied source-version ID.

That command is production-only. Before running dbt, it verifies that the
specific `cdc_lyme_x5j9_wybp` version remains `APPROVED` or `CONDITIONAL` and
has retained rows in `RAW.CDC_LYME_X5J9_WYBP`. It does not request the source,
write artifacts, create an ingestion run, or modify RAW data.

The exit handler removes the temporary job by restoring the promoted baseline
specification. It retains the newly promoted DEV-tested digest; it never
restores the prior digest merely as a side effect of removing topology.

## Consequences

The recovery is auditable, bounded to the approved source version, and avoids
duplicate acquisition. GitHub retains no production Snowflake or Spaces
credentials, and the job has no ingress. A provider deployment failure leaves
the temporary topology subject to the exit-handler restoration; operators must
inspect the governed ledger and dbt evidence before trying another recovery.

## Acceptance criteria

- GitHub `production` approval is required before execution.
- The app identity, scheduled template command, source-version syntax, and
  absence of a stale recovery job are verified before mutation.
- The digest comes from active DEV and is also found in DEV deployment history.
- Runtime verification rejects an unapproved source version or missing RAW
  rows before dbt starts.
- The workflow invokes no ingestion command and only temporary topology is
  removed afterward.
- Acceptance requires provider success plus post-run RAW, CONFORMED,
  provenance, and dbt-quality validation.
