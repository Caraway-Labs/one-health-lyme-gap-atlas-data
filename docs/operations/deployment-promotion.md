# Governed Pipeline Deployment and Promotion

This runbook implements workspace ADR 0006. It applies only to the governed
pipeline; the Alpha POC loader and `ONE_HEALTH_LYME_GAP_ATLAS` database are out
of scope.

## Desired flow

1. A pull request passes the required `checks` workflow.
2. Merge to `main` builds a private OCI image tagged with the commit SHA and
   records its immutable digest.
3. The DEV deployment workflow applies only unapplied, checksum-validated DEV
   migrations, runs the DEV capability preflight, and points the DEV scheduled
   job at that digest.
4. The team reviews the DEV result, including the migration ledger and bounded
   source smoke evidence.
5. A designated approver starts the production workflow with that DEV-tested
   digest. GitHub's protected `production` environment pauses execution for
   approval.
6. The workflow checks the PROD migration ledger and capabilities, applies
   missing append-only migrations, then points the PROD scheduled job at the
   exact same digest.

## Environment boundary

| Concern | DEV | PROD |
| --- | --- | --- |
| Snowflake | `ONE_HEALTH_LYME_GAP_ATLAS_DEV` | `ONE_HEALTH_LYME_GAP_ATLAS_PROD` |
| Spaces | private `...-dev` bucket | separate private `...-prod` bucket |
| App Platform | `oh-lyme-data-dev` | separate non-routable job |
| GitHub environment | `dev` | protected `production` |
| Artifact | tested OCI digest | same OCI digest |

## Rollback

Disable the affected scheduled job if it must stop immediately. Redeploy its
last approved OCI digest; do not rebuild an old commit. Do not delete retained
artifacts or rewrite migration/ingestion lineage as part of rollback.

## Current implementation status

The DEV job presently builds from the mutable `main` branch and is updated
manually through App Platform. It is a temporary bootstrap configuration, not
the approved promotion mechanism. The work items below must be complete before
creating any PROD resources:

1. Keep the required GitHub quality check green and prevent administrator
   bypass for ordinary promotion. The scoped `.gitleaks.toml` exception covers
   only the historical commit that introduced two reviewed non-secret literals;
   it does not exempt either source file from future scanning.
2. Create the private OCI registry and GitHub `dev` and `production`
   environments.
3. Make migration execution environment-aware; current migration SQL contains
   the DEV database name and cannot be reused for PROD unchanged.
4. Replace GitHub-source App Platform specs with OCI-image-by-digest specs.
5. Implement and exercise the DEV deployment and rollback workflows.
6. Complete the Snowflake Streamlit approval deployment and the CDC sample,
   approval, full-ingestion, and dbt acceptance path.
