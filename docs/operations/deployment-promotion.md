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

DEV is on the approved immutable-image path: a green `main` quality run builds
and deploys a private DOCR image digest to the non-routable DEV job. The
checksum-validated migration runner has registered the current two migrations
in the DEV ledger. CI validates migration source, dbt parsing, and the
container, but it deliberately does not receive Snowflake credentials or apply
Snowflake DDL/DML.

Completed controls:

1. Required quality checks include lint, formatting, typing, tests, dbt parse,
   container build, and full-history secret scanning. The scoped
   `.gitleaks.toml` exception covers only two reviewed historical non-secret
   literals.
2. A private OCI registry and GitHub `dev` / protected `production`
   environments exist.
3. `pipeline migration-plan` and explicit
   `pipeline apply-migrations --confirm` render one source-controlled migration
   set only for the DEV or PROD governed database and record checksums in that
   target's ledger.
4. DEV App Platform now uses an image digest, not a mutable GitHub source
   reference.

Still required before any production promotion can succeed:

1. Provision separate PROD Snowflake, Spaces, service identity, and a
   non-routable App Platform job, then configure the production-only secrets
   and `PROD_APP_ID` GitHub environment variable.
2. Complete the CDC steward decision, approved full-ingestion, and dbt
   acceptance path. The DEV `SOURCE_APPROVAL_CONSOLE` is deployed under
   `OH_LYME_DEV_STREAMLIT_OWNER` with the dedicated approval warehouse; the
   `x5j9-wybp` evidence-only candidate is intentionally pending a human
   decision.
3. Exercise a DEV rollback by redeploying a previously approved digest.

The `Promote governed pipeline to PROD` workflow is present and protected by
the GitHub `production` environment. It verifies that a requested digest is the
one currently deployed in DEV. It deliberately stops until distinct PROD
Snowflake/Spaces credentials and the PROD job exist; it never creates them as a
side effect of a promotion request.
