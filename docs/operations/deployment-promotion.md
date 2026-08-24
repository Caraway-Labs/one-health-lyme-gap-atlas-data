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

The checked-in `.do/app.prod.yaml` is the production job specification. It
runs the approved CDC source on its declared annual cadence and invokes dbt
only after a full RAW load succeeds. It requires an active steward-approved
PROD source version and `ENABLE_PRODUCTION_EXECUTION=true`; it cannot consume
a DEV approval, create an approval, or run against the Alpha POC database.

## Streamlit approval-console promotion checklist

Apply this checklist independently in each environment. It records DEV lessons
that are mandatory for the later protected PROD promotion.

1. **Create under the owner role.** Create `SOURCE_APPROVAL_CONSOLE` while
   using `OH_LYME_<ENV>_STREAMLIT_OWNER`. In this Snowflake account, ownership
   cannot be transferred to a Streamlit after it is created, so creating it as
   `ACCOUNTADMIN` and attempting a later ownership grant fails.
2. **Use a dedicated deployment identity.** A PAT session is role-restricted
   and cannot use `USE ROLE` to switch to the Streamlit owner. Provision a
   separate `<ENV>` deploy service user with encrypted key-pair authentication,
   default role `OH_LYME_<ENV>_STREAMLIT_OWNER`, and only the owner role's
   warehouse/schema/stage privileges. Do not reuse the DEV identity or key in
   PROD.
3. **Grant procedure dependencies explicitly.** Owner-rights stored procedures
   need direct `SELECT`/`INSERT` privileges on every governance table they use;
   `USAGE` on the procedure and `SELECT` on views are insufficient. The app
   itself must continue to read governed views only and write exclusively via
   `SP_RECORD_SOURCE_REVIEW_DECISION`.
   Use `INSERT ... SELECT` for procedure writes that include a bound `VARIANT`
   payload such as decision conditions; this Snowflake account rejects that
   payload in the corresponding `INSERT ... VALUES` form.
   The owner role also needs direct `SELECT` and `INSERT` access to the
   migration ledger so it can apply a later owner-owned procedure migration.
   It needs `CREATE PROCEDURE` on `GOVERNANCE` as well; this lets it replace
   the approval procedure it already owns, without broad account privileges.
   Validate both direct `SELECT` and `INSERT` grants for every procedure target
   table; an `INSERT ... SELECT` branch can require both at execution time.
   Keep the source-version creation and immutable decision insert in one
   explicit transaction. If an older deployment produced an orphaned version,
   retire it with a source-controlled reconciliation migration; never delete
   or silently reuse it.
   When a migration uses `CREATE OR REPLACE VIEW`, re-grant every required
   direct view privilege afterwards: Snowflake drops existing grants on the
   replaced view.
4. **Verify before steward review.** Confirm the app owner, query warehouse,
   source-stage files, app usage grants, migration ledger, and a no-write
   authorization-negative call. Then run a fixture candidate through one valid
   decision before asking a steward to decide on a real source.
5. **Show actionable, safe errors.** Keep the friendly rejection banner and
   display the exact Snowflake error beneath it after redacting token, secret,
   password, authorization, and private-key values. Do not expose raw payloads
   or connection configuration.
6. **Promote source and grants together.** Include Streamlit code, its source
   stage upload, owner-role grants, procedure/table privileges, and deployment
   identity configuration in the protected promotion evidence. A successful
   worker-image deployment alone does not deploy or validate the approval app.
7. **Preflight every owner-rights view dependency.** `SELECT` on a view is not
   enough for an owner-rights Streamlit app: its owner needs direct `SELECT` on
   every table expanded by that view. For this console, that includes
   `CATALOG_DATASETS` (queue/detail) and `INGESTION_RUNS` (pipeline status), in
   addition to the procedure dependencies above. Maintain the grant migration
   with the view change, and execute a read-only `SELECT` against **each** of
   queue, detail, pipeline status, and history using the owner role before
   steward access is granted.
8. **Preflight creator privileges before view replacement.** The Streamlit
   owner needs `CREATE VIEW` on `GOVERNANCE` before a migration that creates or
   replaces its owner-owned views. Run the privilege check before deployment;
   do not discover the omission halfway through a migration. `SECURITY_ADMIN`
   may manage grants yet still lack `CREATE TABLE`; baseline-table repair is an
   AccountAdmin-controlled recovery operation, not a normal promotion step.
9. **Treat missing baseline tables as a stop condition in PROD.** A role's
   object listing can hide tables it is not authorized to inspect. Verify the
   V001 governance-table baseline using an authorized administrative preflight
   before promotion. If a required table is actually absent in PROD, stop and
   open a controlled recovery incident; do not fabricate source evidence or
   proceed with a steward decision. The DEV V017 recovery is limited to the
   CDC parent relation and deliberately preserves incomplete evidence rather
   than inventing a metadata digest.
10. **Use short-lived, single-role repair credentials only when necessary.**
    PAT sessions cannot switch roles and cannot create or revoke PATs for the
    same human user. Create a separate, role-restricted, time-limited token
    from a browser-authenticated session only for a documented repair; revoke
    it and remove its local token file/connection entry immediately afterward.
    Keep the normal deployment identity restricted to the Streamlit owner role.

The `Promote governed pipeline to PROD` workflow is present and protected by
the GitHub `production` environment. It verifies that a requested digest is the
one currently deployed in DEV. It deliberately stops until distinct PROD
Snowflake/Spaces credentials and the PROD job exist; it never creates them as a
side effect of a promotion request.
